"""RNG manager (doc §7.4): hierarchical SeedSequence-derived streams.

Two modes:
- strict (default): every (episode, tick, module) gets an independent child
  stream derived from the experiment seed. Same experiment seed => bitwise
  reproducible; different seeds => independent streams; no module ever reuses
  another module's stream.
- legacy: reproduces upstream AuctionNet's fixed-seed behavior so parity
  tests can align bitwise (BiddingEnv.DEFAULT_SEED=1 per call,
  adjust_over_cost seed=1, trunc values via hash((adv,tick,ep))+1019).
"""
from __future__ import annotations

import numpy as np

# Module names used by the simulator; kept as constants to avoid typo-drift.
MOD_EXPOSURE = "exposure"
MOD_CONVERSION = "conversion"
MOD_VALUES = "values"
MOD_OVERSPEND = "overspend"
MOD_TRAFFIC = "traffic"

_LEGACY_MAGIC = 1019  # upstream BiddingEnv.MAGIC_NUMBER
_LEGACY_DEFAULT_SEED = 1  # upstream BiddingEnv.DEFAULT_SEED / adjust_over_cost


class RngManager:
    def __init__(self, experiment_seed: int, legacy_mode: bool = False):
        self.experiment_seed = experiment_seed
        self.legacy_mode = legacy_mode

    def stream(self, episode: int, tick: int, module: str) -> np.random.Generator:
        """Independent generator for (episode, tick, module)."""
        if self.legacy_mode:
            # Upstream re-creates default_rng(seed=1) on every call for
            # exposure/conversion/values/overspend, ignoring episode/tick.
            return np.random.default_rng(_LEGACY_DEFAULT_SEED)
        return np.random.default_rng(
            np.random.SeedSequence(
                entropy=self.experiment_seed,
                spawn_key=(episode, tick, _stable_hash(module)),
            )
        )

    def legacy_trunc_values(self, advertiser_index: int, episode: int) -> tuple[float, float]:
        """Upstream BiddingEnv.generate_trunc_values for tick 0 (used by reset).

        NOTE: relies on Python's hash() of an int tuple, which is stable for
        ints (no PYTHONHASHSEED randomization applies to ints).
        """
        seed = (hash((advertiser_index, 0, episode)) + _LEGACY_MAGIC) & ((1 << 32) - 1)
        rng = np.random.default_rng(seed)
        return float(rng.random()), float(rng.random())

    def trunc_values(self, advertiser_index: int, episode: int) -> tuple[float, float]:
        if self.legacy_mode:
            return self.legacy_trunc_values(advertiser_index, episode)
        rng = np.random.default_rng(
            np.random.SeedSequence(
                entropy=self.experiment_seed,
                spawn_key=(episode, advertiser_index, _stable_hash("trunc")),
            )
        )
        return float(rng.random()), float(rng.random())


def _stable_hash(s: str) -> int:
    # Python's hash() of str is salted per-process; use a fixed FNV-1a instead.
    h = 2166136261
    for ch in s.encode():
        h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    return h
