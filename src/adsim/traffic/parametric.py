"""ParametricTrafficGenerator: adapter over upstream NeurIPSPvGen.

Imports upstream lazily from third_party/AuctionNet (read-only). The upstream
module is importable under Python 3.11 (only run/run_test.py is 3.9-bound).

Fixes applied at the adapter layer (never in upstream files):
- reset() forwards constructor args (upstream bug: pv_num reverts to 500000);
- the module-level `SEED=1019` global seeding still happens at import time
  (upstream behavior, harmless for us: our auction core uses RngManager, and
  the generator itself derives everything from `episode`, not global state).

NOTE on seeds: upstream NeurIPSPvGen derives all randomness from `episode`
alone — two experiments with different experiment seeds see identical traffic
for the same episode index. We keep that for legacy parity but add
`episode_offset` so strict-mode experiments can decorrelate traffic by seed:
effective_episode = episode + episode_offset (traffic CRN pairing across
strategies is then a matter of sharing the offset — doc §12.2).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from adsim.core.types import TrafficBatch

_AUCTIONNET = Path(__file__).resolve().parents[3] / "third_party" / "AuctionNet"


def _import_upstream_pvgen():
    if str(_AUCTIONNET) not in sys.path:
        sys.path.insert(0, str(_AUCTIONNET))
    from simul_bidding_env.PvGenerator.NeurIPSPvGen import NeurIPSPvGen

    return NeurIPSPvGen


class ParametricTrafficGenerator:
    def __init__(
        self,
        num_tick: int,
        num_agent: int,
        num_agent_category: int,
        num_category: int,
        pv_num: int,
        episode_offset: int = 0,
    ):
        self._cls = _import_upstream_pvgen()
        self._kwargs = dict(
            num_tick=num_tick,
            num_agent=num_agent,
            num_agent_category=num_agent_category,
            num_category=num_category,
            pv_num=pv_num,
        )
        self.episode_offset = episode_offset
        self._gen = None

    def reset(self, episode: int) -> None:
        # Fresh instance per episode with args forwarded (adapter-level fix
        # for the upstream reset() arg-loss bug).
        self._gen = self._cls(episode=episode + self.episode_offset, **self._kwargs)

    def next_tick(self, tick: int) -> TrafficBatch:
        assert self._gen is not None, "call reset() first"
        return TrafficBatch(
            tick=tick,
            pv_values=np.asarray(self._gen.pv_values[tick]),
            pvalue_sigmas=np.asarray(self._gen.pValueSigmas[tick]),
        )
