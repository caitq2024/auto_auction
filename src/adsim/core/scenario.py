"""ScenarioConfig: YAML -> fully-resolved, dumpable experiment definition.

Replaces upstream's hardcoded 48-element budget/CPA tables and gin config.
Every run must persist `resolved_dict()` alongside outputs (doc §10).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from adsim.core.types import AdvertiserConfig

# Upstream Controller.calculate_budget() / get_cpa_constraints(), collected
# here as *data* so the default scenario reproduces the upstream market.
UPSTREAM_BUDGETS = [
    2900, 4350, 3000, 2400, 4800, 2000, 2050, 3500,
    4600, 2000, 2800, 2350, 2050, 2900, 4750, 3450,
    2000, 3500, 2200, 2700, 3100, 2100, 4850, 4100,
    2000, 4800, 3050, 4250, 2850, 2250, 2000, 3900,
    2000, 3250, 4450, 3550, 2700, 2100, 4650, 2000,
    3400, 2650, 2300, 4100, 4800, 4450, 2000, 2050,
]
UPSTREAM_CPAS = [
    100, 70, 90, 110, 60, 130, 120, 80,
    70, 130, 100, 110, 120, 90, 60, 80,
    130, 80, 110, 100, 90, 120, 60, 70,
    120, 60, 90, 70, 100, 110, 130, 80,
    120, 90, 70, 80, 100, 110, 60, 130,
    90, 100, 110, 80, 60, 70, 130, 120,
]
# Upstream Controller.initialize_agents(): per-category strategy mix,
# even categories use row 0, odd categories row 1. onlinelp takes
# episode=category (col 3) and episode=category+1 (col 4).
UPSTREAM_STRATEGY_MIX = [
    ["pid", "upstream:iql", "upstream:td3_bc", "onlinelp", "onlinelp+1",
     "upstream:cql", "upstream:bc", "upstream:mopo"],
    ["pid", "upstream:bcq", "upstream:mopo", "onlinelp", "onlinelp+1",
     "upstream:td3_bc", "upstream:iql", "upstream:combo"],
]


@dataclass
class ScenarioConfig:
    scenario_id: str
    seed: int
    num_episode: int = 1
    num_tick: int = 48
    pv_num: int = 500000
    reserve_pv_price: float = 0.0001
    min_remaining_budget: float = 0.1
    budget_exhaustion_mode: str = "sequential_stop"  # or random_drop_legacy
    legacy_rng: bool = False
    traffic_type: str = "parametric"  # upstream NeurIPSPvGen adapter
    advertisers: list[AdvertiserConfig] = field(default_factory=list)
    controlled_agent_ids: list[int] = field(default_factory=lambda: [0])
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def num_agent(self) -> int:
        return len(self.advertisers)

    @classmethod
    def upstream_default_48(
        cls,
        scenario_id: str = "auctionnet_default_48",
        seed: int = 1,
        controlled: dict[int, tuple[str, dict[str, Any]]] | None = None,
        **overrides: Any,
    ) -> "ScenarioConfig":
        """The upstream 48-agent market; `controlled` swaps strategies in:
        {agent_id: (strategy_name, strategy_kwargs)}."""
        advertisers = []
        for i in range(48):
            category = i // 8
            strategy = UPSTREAM_STRATEGY_MIX[category % 2][i % 8]
            kwargs: dict[str, Any] = {}
            if strategy == "onlinelp":
                kwargs = {"episode": category}
                strategy = "upstream:onlinelp"
            elif strategy == "onlinelp+1":
                kwargs = {"episode": category + 1}
                strategy = "upstream:onlinelp"
            if controlled and i in controlled:
                strategy, kwargs = controlled[i]
            advertisers.append(
                AdvertiserConfig(
                    advertiser_id=i,
                    budget=float(UPSTREAM_BUDGETS[i]),
                    cpa=float(UPSTREAM_CPAS[i]),
                    category=category,
                    strategy=strategy,
                    strategy_kwargs=kwargs,
                )
            )
        cfg = cls(
            scenario_id=scenario_id,
            seed=seed,
            advertisers=advertisers,
            controlled_agent_ids=sorted(controlled) if controlled else [0],
        )
        for k, v in overrides.items():
            if not hasattr(cfg, k):
                raise KeyError(f"unknown scenario field: {k}")
            setattr(cfg, k, v)
        return cfg

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ScenarioConfig":
        raw = yaml.safe_load(Path(path).read_text())
        base = raw.pop("base", None)
        if base == "upstream_default_48":
            controlled_raw = raw.pop("controlled", {}) or {}
            controlled = {
                int(k): (v["strategy"], v.get("kwargs", {}))
                for k, v in controlled_raw.items()
            }
            return cls.upstream_default_48(controlled=controlled or None, **raw)
        advertisers = [AdvertiserConfig(**a) for a in raw.pop("advertisers", [])]
        return cls(advertisers=advertisers, **raw)

    def resolved_dict(self) -> dict[str, Any]:
        return asdict(self)

    def dump(self, path: str | Path) -> None:
        Path(path).write_text(yaml.safe_dump(self.resolved_dict(), sort_keys=False))
