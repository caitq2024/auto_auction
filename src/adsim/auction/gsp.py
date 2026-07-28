"""Three-slot GSP auction core, independent re-implementation of upstream
`simul_bidding_env/Environment/BiddingEnv.py` with the RNG routed through
RngManager so that strict mode gets proper per-(episode,tick,module) streams
while legacy mode reproduces upstream bitwise.

Upstream quirks preserved in BOTH modes (they are mechanism semantics, not RNG):
- market_prices[pv] = 2nd..4th highest bids, floored at reserve_pv_price;
  slot k pays market_prices[k-1] (GSP next-price).
- exposure: slot coefficient [1.0, 0.8, 0.6] as Bernoulli p; if slot 2 on a
  PV is not exposed, slot 3 on that PV is forced unexposed (continuity rule).
- unsold detection: a slot whose price equals exactly reserve_pv_price is
  treated as unsold and fully zeroed (xi/slot/cost/exposure/conversion).
  This also cancels genuinely-won slots whose next price coincides with the
  reserve — documented upstream quirk, kept for parity.
- conversion values sampled from truncnorm around pValue with per-advertiser
  truncation bounds drawn at episode reset.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import truncnorm

from adsim.core.rng import MOD_CONVERSION, MOD_EXPOSURE, MOD_VALUES, RngManager
from adsim.core.types import AuctionResult, TrafficBatch

NUM_SLOTS = 3
SLOT_COEFFICIENTS = np.array([1.0, 0.8, 0.6])


class GspAuction:
    def __init__(self, reserve_pv_price: float, rng_manager: RngManager, num_agent: int):
        self.reserve_pv_price = reserve_pv_price
        self.rng = rng_manager
        self.num_agent = num_agent
        # per-advertiser truncnorm bounds, refreshed each episode
        self._trunc_values: list[tuple[float, float]] = [(1.0, 0.01)] * num_agent

    def reset(self, episode: int) -> None:
        self._trunc_values = [
            self.rng.trunc_values(i, episode) for i in range(self.num_agent)
        ]

    def clear(self, traffic: TrafficBatch, bids: np.ndarray, episode: int, tick: int) -> AuctionResult:
        """bids: (num_pv, num_agent). Returns per-agent-major AuctionResult."""
        pv_values, sigmas = traffic.pv_values, traffic.pvalue_sigmas

        sorted_idx = np.argsort(-bids, axis=1)[:, :NUM_SLOTS]
        sorted_bids = -np.sort(-bids, axis=1)[:, : NUM_SLOTS + 1]
        market_prices = sorted_bids[:, 1 : NUM_SLOTS + 1].copy()
        market_prices[market_prices < self.reserve_pv_price] = self.reserve_pv_price

        slot = np.zeros_like(bids, dtype=int)
        np.put_along_axis(slot, sorted_idx, np.arange(1, NUM_SLOTS + 1)[None, :], axis=1)
        xi = (slot > 0).astype(int)

        rows = np.indices(slot.shape)[0]
        cost = market_prices[rows, slot - 1]
        cost[slot == 0] = 0.0

        exposure_p = SLOT_COEFFICIENTS[slot - 1]
        exposure_p[slot == 0] = 0.0
        rng_exp = self.rng.stream(episode, tick, MOD_EXPOSURE)
        is_exposed = rng_exp.binomial(n=1, p=np.clip(exposure_p, 0, 1))
        is_exposed = self._enforce_slot_continuity(is_exposed, slot)

        values = self._sample_values(pv_values, sigmas, episode, tick)
        rng_conv = self.rng.stream(episode, tick, MOD_CONVERSION)
        conversion = rng_conv.binomial(n=1, p=np.clip(values, 0, 1)) * is_exposed

        # expected-conversion accounting (doc §6.4), pre-unsold-zeroing on
        # purpose is wrong — compute after zeroing below.

        is_unsold = cost == self.reserve_pv_price
        xi[is_unsold] = 0
        slot[is_unsold] = 0
        cost[is_unsold] = 0.0
        is_exposed[is_unsold] = 0
        conversion[is_unsold] = 0

        exposure_p_final = SLOT_COEFFICIENTS[slot - 1]
        exposure_p_final[slot == 0] = 0.0
        expected_conversion = np.clip(pv_values, 0, 1) * exposure_p_final

        least_winning_cost = market_prices[:, -1]
        return AuctionResult(
            xi=xi.T,
            slot=slot.T,
            cost=cost.T,
            is_exposed=is_exposed.T,
            conversion=conversion.T,
            least_winning_cost=least_winning_cost,
            market_prices=market_prices,
            expected_conversion=expected_conversion.T,
        )

    @staticmethod
    def _enforce_slot_continuity(is_exposed: np.ndarray, slot: np.ndarray) -> np.ndarray:
        unexposed_slot2 = (slot == 2) & (is_exposed == 0)
        force = unexposed_slot2.any(axis=1).reshape(-1, 1) & (slot == 3)
        is_exposed[force] = 0
        return is_exposed

    def _sample_values(
        self, pv_values: np.ndarray, sigmas: np.ndarray, episode: int, tick: int
    ) -> np.ndarray:
        v1 = np.array([t[0] for t in self._trunc_values]).reshape(1, -1)
        v2 = np.array([t[1] for t in self._trunc_values]).reshape(1, -1)
        rng = self.rng.stream(episode, tick, MOD_VALUES)
        return truncnorm.rvs(-2 * v1, 2 * v2, loc=pv_values, scale=sigmas, random_state=rng)
