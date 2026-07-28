"""Core typed data structures for the adsim platform.

Shapes follow the upstream AuctionNet convention unless noted:
- pv_values / sigmas: (num_pv, num_agent) per tick
- bids: (num_pv, num_agent)
- auction outputs (xi, slot, cost, is_exposed, conversion): (num_agent, num_pv)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class AdvertiserConfig:
    advertiser_id: int
    budget: float
    cpa: float
    category: int
    strategy: str  # registry key, e.g. "pid", "fixed_alpha", "upstream:iql"
    strategy_kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdvertiserState:
    advertiser_id: int
    budget: float
    remaining_budget: float
    cumulative_cost: float = 0.0
    cumulative_conversion: float = 0.0

    @property
    def actual_cpa(self) -> float:
        return self.cumulative_cost / (self.cumulative_conversion + 1e-10)


@dataclass
class TrafficBatch:
    """One tick of traffic: pValue/sigma per (pv, advertiser)."""

    tick: int
    pv_values: np.ndarray  # (num_pv, num_agent)
    pvalue_sigmas: np.ndarray  # (num_pv, num_agent)

    @property
    def num_pv(self) -> int:
        return int(self.pv_values.shape[0])


@dataclass
class AuctionResult:
    """Cleared auction for one tick. All arrays are (num_agent, num_pv)."""

    xi: np.ndarray  # won any slot (0/1)
    slot: np.ndarray  # 0 = lost, 1..3 = slot index
    cost: np.ndarray  # GSP price if exposed (charged only when exposed)
    is_exposed: np.ndarray  # 0/1
    conversion: np.ndarray  # sampled conversions (0/1)
    least_winning_cost: np.ndarray  # (num_pv,)
    market_prices: np.ndarray  # (num_pv, num_slots)
    expected_conversion: np.ndarray  # (num_agent, num_pv) pValue * E[exposure|slot]

    def real_cost_per_agent(self) -> np.ndarray:
        return (self.cost * self.is_exposed).sum(axis=1)

    def conversion_per_agent(self) -> np.ndarray:
        return self.conversion.sum(axis=1)


@dataclass
class AgentObservation:
    """Aggregated per-tick observation for one advertiser (doc §8.4).

    LLM-ready: `to_dict()` yields plain floats for JSON serialization.
    """

    tick_index: int
    num_tick: int
    initial_budget: float
    remaining_budget: float
    cumulative_cost: float
    cumulative_conversion: float
    target_cpa: float
    current_pv_count: int
    current_pvalue_mean: float
    current_pvalue_quantiles: tuple[float, float, float]  # p25/p50/p75
    historical_win_rate: float
    recent_win_rate: float
    historical_market_price_mean: float
    recent_market_price_mean: float
    previous_alpha: float | None

    @property
    def tick_ratio_remaining(self) -> float:
        return (self.num_tick - self.tick_index) / self.num_tick

    @property
    def remaining_budget_ratio(self) -> float:
        return self.remaining_budget / self.initial_budget if self.initial_budget > 0 else 0.0

    @property
    def actual_cpa(self) -> float:
        return self.cumulative_cost / (self.cumulative_conversion + 1e-10)

    def to_dict(self) -> dict[str, Any]:
        return {
            "time": {
                "tick_index": self.tick_index,
                "num_tick": self.num_tick,
                "tick_ratio_remaining": round(self.tick_ratio_remaining, 4),
            },
            "budget": {
                "initial_budget": self.initial_budget,
                "remaining_budget": round(self.remaining_budget, 4),
                "remaining_budget_ratio": round(self.remaining_budget_ratio, 4),
            },
            "performance": {
                "cumulative_cost": round(self.cumulative_cost, 4),
                "cumulative_conversion": self.cumulative_conversion,
                "actual_cpa": round(self.actual_cpa, 4),
                "target_cpa": self.target_cpa,
            },
            "market": {
                "historical_win_rate": round(self.historical_win_rate, 4),
                "recent_win_rate": round(self.recent_win_rate, 4),
                "historical_market_price_mean": round(self.historical_market_price_mean, 6),
                "recent_market_price_mean": round(self.recent_market_price_mean, 6),
            },
            "traffic": {
                "current_pv_count": self.current_pv_count,
                "current_pvalue_mean": round(self.current_pvalue_mean, 8),
                "current_pvalue_quantiles": [round(q, 8) for q in self.current_pvalue_quantiles],
            },
            "action_history": {"previous_alpha": self.previous_alpha},
        }


@dataclass
class EpisodeSummary:
    """Per-(episode, advertiser) outcome with competition-style score."""

    episode: int
    advertiser_id: int
    strategy: str
    budget: float
    target_cpa: float
    conversions: float
    expected_conversions: float
    cost: float
    win_pv: int
    compete_pv: int
    score: float
    budget_utilization: float
    last_compete_tick: int

    @property
    def actual_cpa(self) -> float:
        return self.cost / (self.conversions + 1e-10)
