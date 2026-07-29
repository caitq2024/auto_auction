"""Episode runner: the internal replacement for upstream run/run_test.py.

Differences from upstream (all documented in docs/IMPLEMENTATION_DETAILS.md):
- any number of controlled agents (ScenarioConfig.controlled_agent_ids);
- budget exhaustion via sequential_stop (default) or random_drop_legacy;
- RngManager streams instead of fixed seeds (legacy_rng=True restores them);
- per-tick observations + event summaries recorded for every advertiser;
- expected conversions tracked alongside sampled ones (doc §6.4).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from adsim.agents.registry import BidAgent, build_agent
from adsim.auction.budget_control import clear_with_budget
from adsim.auction.gsp import GspAuction
from adsim.core.rng import RngManager
from adsim.core.scenario import ScenarioConfig
from adsim.core.types import AgentObservation, EpisodeSummary, TrafficBatch
from adsim.evaluation.metrics import competition_score
from adsim.traffic.parametric import ParametricTrafficGenerator


@dataclass
class TickRecord:
    episode: int
    tick: int
    advertiser_id: int
    alpha: float | None
    bid_mean: float
    compete_pv: int
    win_pv: int
    exposed_pv: int
    cost: float
    conversions: float
    expected_conversions: float
    remaining_budget_after: float
    observation: dict[str, Any] | None = None


@dataclass
class EpisodeResult:
    summaries: list[EpisodeSummary]
    tick_records: list[TickRecord] = field(default_factory=list)
    wall_time_sec: float = 0.0


class EpisodeRunner:
    def __init__(self, scenario: ScenarioConfig):
        self.scenario = scenario
        self.rng = RngManager(scenario.seed, legacy_mode=scenario.legacy_rng)
        self.auction = GspAuction(scenario.reserve_pv_price, self.rng, scenario.num_agent)
        if scenario.traffic_type == "replay":
            from adsim.traffic.replay import ReplayTrafficGenerator

            self.traffic: object = ReplayTrafficGenerator(
                period_csvs=scenario.extra["replay_period_csvs"],
                num_agent=scenario.num_agent,
            )
        else:
            num_category = len({a.category for a in scenario.advertisers})
            self.traffic = ParametricTrafficGenerator(
                num_tick=scenario.num_tick,
                num_agent=scenario.num_agent,
                num_agent_category=scenario.num_agent // num_category,
                num_category=num_category,
                pv_num=scenario.pv_num,
            )
        self.agents: list[BidAgent] = [
            build_agent(a.strategy, a.strategy_kwargs) for a in scenario.advertisers
        ]

    def run_episode(self, episode: int, record_observations: bool = True) -> EpisodeResult:
        sc = self.scenario
        t0 = time.time()
        self.traffic.reset(episode)
        self.auction.reset(episode)
        for agent, adv in zip(self.agents, sc.advertisers):
            agent.reset(adv, episode)

        remaining = np.array([a.budget for a in sc.advertisers], dtype=float)
        cum_cost = np.zeros(sc.num_agent)
        cum_conv = np.zeros(sc.num_agent)
        cum_exp_conv = np.zeros(sc.num_agent)
        win_pv = np.zeros(sc.num_agent, dtype=int)
        exposed_pv = np.zeros(sc.num_agent, dtype=int)
        compete_pv = np.zeros(sc.num_agent, dtype=int)
        last_win_tick = np.full(sc.num_agent, -1, dtype=int)

        hist_pvalue, hist_bids, hist_auction, hist_impression, hist_lwc = [], [], [], [], []
        # market/win history per agent for observations
        won_hist: list[np.ndarray] = []
        lwc_means: list[float] = []
        tick_records: list[TickRecord] = []

        for tick in range(sc.num_tick):
            batch = self.traffic.next_tick(tick)
            num_pv = batch.num_pv

            bids = np.zeros((num_pv, sc.num_agent))
            for i, agent in enumerate(self.agents):
                if remaining[i] < sc.min_remaining_budget:
                    continue
                if hasattr(agent, "observe"):
                    # observation-driven agents (LLM) get the aggregated
                    # pre-bid state; history stats cover ticks < current
                    agent.observe(self._build_observation(
                        i, tick, batch, remaining[i], cum_cost[i], cum_conv[i],
                        won_hist or [np.zeros(sc.num_agent)], lwc_means or [0.0],
                    ))
                bids[:, i] = agent.bidding(
                    tick,
                    batch.pv_values[:, i],
                    batch.pvalue_sigmas[:, i],
                    [x[i] for x in hist_pvalue],
                    [x[i] for x in hist_bids],
                    [x[i] for x in hist_auction],
                    [x[i] for x in hist_impression],
                    hist_lwc,
                    remaining_budget=float(remaining[i]),
                )
            bids[bids < 0] = 0.0
            bids_for_ledger = bids.copy()

            result = clear_with_budget(
                batch,
                bids,
                remaining,
                clear=lambda tb, b: self.auction.clear(tb, b, episode, tick),
                mode=sc.budget_exhaustion_mode,
                rng_manager=self.rng,
                episode=episode,
                tick=tick,
            )

            cost = result.real_cost_per_agent()
            conv = result.conversion_per_agent().astype(float)
            exp_conv = result.expected_conversion.sum(axis=1)
            remaining -= cost
            cum_cost += cost
            cum_conv += conv
            cum_exp_conv += exp_conv
            tick_wins = result.xi.sum(axis=1)
            tick_exposed = result.is_exposed.sum(axis=1)
            win_pv += tick_wins.astype(int)
            exposed_pv += tick_exposed.astype(int)
            active = np.array([b.sum() > 0 for b in bids_for_ledger.T])
            compete_pv += np.where(active, num_pv, 0)
            last_win_tick[tick_exposed > 0] = tick

            hist_bids.append(bids_for_ledger.T)
            hist_lwc.append(result.least_winning_cost)
            hist_pvalue.append(np.stack((batch.pv_values.T, batch.pvalue_sigmas.T), axis=-1))
            hist_auction.append(np.stack((result.xi, result.slot, result.cost), axis=-1))
            hist_impression.append(np.stack((result.is_exposed, result.conversion), axis=-1))
            won_hist.append(tick_wins / max(num_pv, 1))
            lwc_means.append(float(result.least_winning_cost.mean()))

            for i in range(sc.num_agent):
                obs = None
                if record_observations and i in sc.controlled_agent_ids:
                    obs = self._build_observation(
                        i, tick, batch, remaining[i], cum_cost[i], cum_conv[i],
                        won_hist, lwc_means,
                    ).to_dict()
                tick_records.append(
                    TickRecord(
                        episode=episode,
                        tick=tick,
                        advertiser_id=i,
                        alpha=self.agents[i].last_alpha,
                        bid_mean=float(bids_for_ledger[:, i].mean()),
                        compete_pv=num_pv if active[i] else 0,
                        win_pv=int(tick_wins[i]),
                        exposed_pv=int(tick_exposed[i]),
                        cost=float(cost[i]),
                        conversions=float(conv[i]),
                        expected_conversions=float(exp_conv[i]),
                        remaining_budget_after=float(remaining[i]),
                        observation=obs,
                    )
                )

        summaries = []
        for i, adv in enumerate(sc.advertisers):
            cpa = cum_cost[i] / (cum_conv[i] + 1e-10)
            summaries.append(
                EpisodeSummary(
                    episode=episode,
                    advertiser_id=i,
                    strategy=adv.strategy,
                    budget=adv.budget,
                    target_cpa=adv.cpa,
                    conversions=float(cum_conv[i]),
                    expected_conversions=float(cum_exp_conv[i]),
                    cost=float(cum_cost[i]),
                    win_pv=int(exposed_pv[i]),
                    compete_pv=int(compete_pv[i]),
                    score=competition_score(float(cum_conv[i]), cpa, adv.cpa),
                    budget_utilization=float(cum_cost[i] / adv.budget),
                    last_compete_tick=int(last_win_tick[i]),
                )
            )
        return EpisodeResult(
            summaries=summaries, tick_records=tick_records,
            wall_time_sec=round(time.time() - t0, 2),
        )

    def _build_observation(
        self, i: int, tick: int, batch: TrafficBatch, remaining: float,
        cum_cost: float, cum_conv: float,
        won_hist: list[np.ndarray], lwc_means: list[float],
    ) -> AgentObservation:
        adv = self.scenario.advertisers[i]
        pvals = batch.pv_values[:, i]
        recent = slice(max(0, len(won_hist) - 3), None)
        return AgentObservation(
            tick_index=tick,
            num_tick=self.scenario.num_tick,
            initial_budget=adv.budget,
            remaining_budget=remaining,
            cumulative_cost=cum_cost,
            cumulative_conversion=cum_conv,
            target_cpa=adv.cpa,
            current_pv_count=batch.num_pv,
            current_pvalue_mean=float(pvals.mean()),
            current_pvalue_quantiles=tuple(np.percentile(pvals, [25, 50, 75]).tolist()),
            historical_win_rate=float(np.mean([w[i] for w in won_hist])),
            recent_win_rate=float(np.mean([w[i] for w in won_hist[recent]])),
            historical_market_price_mean=float(np.mean(lwc_means)),
            recent_market_price_mean=float(np.mean(lwc_means[recent])),
            previous_alpha=self.agents[i].last_alpha,
        )
