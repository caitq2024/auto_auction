"""ReplayTrafficGenerator: official pre-generated dataset as the traffic
source for ONLINE simulation.

Reads a period CSV (18-col official schema; one row per PV x advertiser) and
rebuilds per-tick (num_pv, num_agent) pValue/sigma matrices. Opponents still
bid and react live — only the traffic (which impressions arrive, with which
predicted conversion probabilities) is replayed. This runs the full
multi-agent market on the deep-generative-model traffic distribution that
the official dataset was produced from, at full 500k scale (the bundled
ModelPvGen checkpoint caps at 105k PV/episode; the dataset has no such cap).

Episodes map to periods: episode i uses periods[i % len(periods)].

Loading a 3.8GB CSV takes ~1 min; matrices for one period hold ~500k x 48
floats x 2 (~380MB), cached per generator instance.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from adsim.core.types import TrafficBatch

_COLS = ["advertiserNumber", "timeStepIndex", "pvIndex", "pValue", "pValueSigma"]


class ReplayTrafficGenerator:
    def __init__(self, period_csvs: list[str | Path], num_agent: int = 48):
        if not period_csvs:
            raise ValueError("period_csvs must not be empty")
        self.period_csvs = [Path(p) for p in period_csvs]
        for p in self.period_csvs:
            if not p.exists():
                raise FileNotFoundError(p)
        self.num_agent = num_agent
        self._cache: dict[Path, tuple[list[np.ndarray], list[np.ndarray]]] = {}
        self._current: tuple[list[np.ndarray], list[np.ndarray]] | None = None

    def _load(self, path: Path) -> tuple[list[np.ndarray], list[np.ndarray]]:
        if path in self._cache:
            return self._cache[path]
        df = pd.read_csv(path, usecols=_COLS)
        pv_values: list[np.ndarray] = []
        sigmas: list[np.ndarray] = []
        for tick in range(int(df.timeStepIndex.max()) + 1):
            g = df[df.timeStepIndex == tick]
            # rows are PV x advertiser; pivot to (num_pv, num_agent)
            pv = g.pivot_table(index="pvIndex", columns="advertiserNumber",
                               values="pValue", aggfunc="first").sort_index()
            sg = g.pivot_table(index="pvIndex", columns="advertiserNumber",
                               values="pValueSigma", aggfunc="first").sort_index()
            pv_values.append(pv.to_numpy(dtype=float))
            sigmas.append(sg.to_numpy(dtype=float))
        # keep at most one period cached (they're ~380MB each)
        self._cache.clear()
        self._cache[path] = (pv_values, sigmas)
        return self._cache[path]

    def reset(self, episode: int) -> None:
        path = self.period_csvs[episode % len(self.period_csvs)]
        self._current = self._load(path)

    def next_tick(self, tick: int) -> TrafficBatch:
        assert self._current is not None, "call reset() first"
        pv_values, sigmas = self._current
        if tick >= len(pv_values):
            # dataset periods have exactly 48 ticks; guard anyway
            return TrafficBatch(tick=tick,
                                pv_values=np.zeros((0, self.num_agent)),
                                pvalue_sigmas=np.zeros((0, self.num_agent)))
        return TrafficBatch(tick=tick, pv_values=pv_values[tick],
                            pvalue_sigmas=sigmas[tick])
