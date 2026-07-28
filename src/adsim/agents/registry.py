"""Bid agent registry.

All agents implement the upstream `bidding(...)` call signature so upstream
checkpointed strategies plug in unchanged, plus a `reset()`. Alpha-style
agents (PID, fixed, LLM later) go through ScalarAlphaAgent, which records
`last_alpha` for the Event Ledger and observation history.

Strategy names:
- "fixed_alpha"  kwargs: alpha
- "pid"          re-implementation of upstream PID (pure pacing logic)
- "upstream:iql" / ":bc" / ":bcq" / ":cql" / ":td3_bc" / ":mopo" / ":combo"
                 / ":onlinelp"  — wraps third_party/AuctionNet strategies
                 (TorchScript checkpoints load fine under torch 2.x/py311)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from adsim.core.types import AdvertiserConfig

_AUCTIONNET = Path(__file__).resolve().parents[3] / "third_party" / "AuctionNet"


class BidAgent(Protocol):
    last_alpha: float | None

    def reset(self, advertiser: AdvertiserConfig, episode: int) -> None: ...

    def bidding(
        self,
        tick: int,
        pv_values: np.ndarray,
        pvalue_sigmas: np.ndarray,
        history_pvalue_infos: list,
        history_bids: list,
        history_auction_results: list,
        history_impression_results: list,
        history_least_winning_costs: list,
        remaining_budget: float,
    ) -> np.ndarray: ...


class ScalarAlphaAgent:
    """Base: one alpha per tick, bids = alpha * pValue."""

    def __init__(self) -> None:
        self.last_alpha: float | None = None
        self.advertiser: AdvertiserConfig | None = None

    def reset(self, advertiser: AdvertiserConfig, episode: int) -> None:
        self.advertiser = advertiser
        self.last_alpha = None

    def compute_alpha(self, tick: int, remaining_budget: float, **ctx: Any) -> float:
        raise NotImplementedError

    def bidding(
        self, tick, pv_values, pvalue_sigmas, history_pvalue_infos, history_bids,
        history_auction_results, history_impression_results,
        history_least_winning_costs, remaining_budget,
    ) -> np.ndarray:
        alpha = self.compute_alpha(tick, remaining_budget)
        self.last_alpha = float(alpha)
        return alpha * pv_values


class FixedAlphaAgent(ScalarAlphaAgent):
    def __init__(self, alpha: float = 80.0):
        super().__init__()
        self.alpha = alpha

    def compute_alpha(self, tick: int, remaining_budget: float, **ctx: Any) -> float:
        return self.alpha


class PidAgent(ScalarAlphaAgent):
    """Re-implementation of upstream PidBiddingStrategy (pacing heuristic):
    start at base_action; scale x1.2 when under-pacing (<0.7 of even pace),
    x0.7 when over-pacing (>1.1)."""

    def __init__(self, base_action: float = 15.0):
        super().__init__()
        self.base_action = base_action
        self._alpha = base_action
        self._last_remaining: float | None = None

    def reset(self, advertiser: AdvertiserConfig, episode: int) -> None:
        super().reset(advertiser, episode)
        self._alpha = self.base_action
        self._last_remaining = advertiser.budget

    def compute_alpha(self, tick: int, remaining_budget: float, **ctx: Any) -> float:
        assert self._last_remaining is not None
        if tick > 0:
            last_cost = self._last_remaining - remaining_budget
            ticks_left = 48 - tick
            if remaining_budget > 0:
                if last_cost * ticks_left / remaining_budget < 0.7:
                    self._alpha *= 1.2
                elif last_cost * ticks_left / remaining_budget > 1.1:
                    self._alpha *= 0.7
        self._last_remaining = remaining_budget
        return self._alpha


_UPSTREAM_CLASSES = {
    "iql": ("iql_bidding_strategy", "IqlBiddingStrategy"),
    "bc": ("bc_bidding_strategy", "BcBiddingStrategy"),
    "bcq": ("bcq_bidding_strategy", "BcqBiddingStrategy"),
    "cql": ("cql_bidding_strategy", "CqlBiddingStrategy"),
    "td3_bc": ("td3_bc_bidding_strategy", "TD3_BCBiddingStrategy"),
    "mopo": ("mbrl_mopo_bidding_strategy", "MbrlMopoBiddingStrategy"),
    "combo": ("mbrl_combomicro_bidding_strategy", "MbrlComboMicroBiddingStrategy"),
    "onlinelp": ("onlinelp_bidding_strategy", "OnlineLpBiddingStrategy"),
    "pid": ("pid_bidding_strategy", "PidBiddingStrategy"),
}


class UpstreamAgentAdapter:
    """Wraps a third_party/AuctionNet simul_bidding_env strategy instance.

    The upstream strategy keeps its own remaining_budget; the runner passes
    the authoritative value each tick and we sync it before delegating.
    """

    def __init__(self, kind: str, **kwargs: Any):
        if str(_AUCTIONNET) not in sys.path:
            sys.path.insert(0, str(_AUCTIONNET))
        module_name, cls_name = _UPSTREAM_CLASSES[kind]
        import importlib

        mod = importlib.import_module(f"simul_bidding_env.strategy.{module_name}")
        cls = getattr(mod, cls_name)
        if kind == "pid":
            kwargs.setdefault("exp_tempral_ratio", np.ones(48))
        self._impl = cls(**kwargs)
        self.kind = kind
        self.last_alpha: float | None = None  # upstream agents don't expose alpha

    def reset(self, advertiser: AdvertiserConfig, episode: int) -> None:
        self._impl.budget = advertiser.budget
        self._impl.cpa = advertiser.cpa
        self._impl.category = advertiser.category
        self._impl.reset()

    def bidding(
        self, tick, pv_values, pvalue_sigmas, history_pvalue_infos, history_bids,
        history_auction_results, history_impression_results,
        history_least_winning_costs, remaining_budget,
    ) -> np.ndarray:
        self._impl.remaining_budget = remaining_budget
        return np.asarray(
            self._impl.bidding(
                tick, pv_values, pvalue_sigmas, history_pvalue_infos, history_bids,
                history_auction_results, history_impression_results,
                history_least_winning_costs,
            )
        )


def build_agent(strategy: str, kwargs: dict[str, Any]) -> BidAgent:
    if strategy == "fixed_alpha":
        return FixedAlphaAgent(**kwargs)
    if strategy == "pid":
        return PidAgent(**kwargs)
    if strategy == "dt":
        from adsim.agents.dt import DtAgent

        return DtAgent(**kwargs)
    if strategy.startswith("upstream:"):
        return UpstreamAgentAdapter(strategy.split(":", 1)[1], **kwargs)
    raise KeyError(f"unknown strategy: {strategy}")
