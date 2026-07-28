"""Budget exhaustion handling (doc §7.5).

- sequential_stop (default): winners consume budget in PV arrival order;
  once an agent's remaining budget is exceeded, its later bids this tick are
  zeroed and the auction re-clears (other agents may then win those PVs).
- random_drop_legacy: upstream behavior — randomly zero a proportional set of
  the over-spender's winning bids (seed=1 in legacy mode) and re-clear, in a
  loop until nobody overspends.

Both operate as: propose bids -> clear -> detect overspend -> mutate bids ->
re-clear, matching the upstream while-loop structure so results stay
comparable.
"""
from __future__ import annotations

import math
from typing import Callable

import numpy as np

from adsim.core.rng import MOD_OVERSPEND, RngManager
from adsim.core.types import AuctionResult, TrafficBatch

ClearFn = Callable[[TrafficBatch, np.ndarray], AuctionResult]


def clear_with_budget(
    traffic: TrafficBatch,
    bids: np.ndarray,
    remaining_budgets: np.ndarray,
    clear: ClearFn,
    mode: str,
    rng_manager: RngManager,
    episode: int,
    tick: int,
    max_iters: int = 50,
) -> AuctionResult:
    """bids: (num_pv, num_agent); mutated in place across re-clear rounds."""
    result = clear(traffic, bids)
    for _ in range(max_iters):
        cost = result.real_cost_per_agent()
        over_ratio = np.maximum((cost - remaining_budgets) / (cost + 1e-4), 0)
        if over_ratio.max() <= 0:
            return result
        if mode == "sequential_stop":
            _drop_sequential(bids, result, remaining_budgets)
        elif mode == "random_drop_legacy":
            _drop_random_legacy(bids, result, over_ratio, rng_manager, episode, tick)
        else:
            raise ValueError(f"unknown budget_exhaustion_mode: {mode}")
        result = clear(traffic, bids)
    raise RuntimeError("budget control failed to converge")


def _drop_sequential(
    bids: np.ndarray, result: AuctionResult, remaining_budgets: np.ndarray
) -> None:
    """Zero every over-spender's bids after the PV where its budget runs out."""
    real_cost = result.cost * result.is_exposed  # (num_agent, num_pv)
    cum = np.cumsum(real_cost, axis=1)
    total = cum[:, -1]
    for agent in np.where(total > remaining_budgets)[0]:
        cutoff = int(np.searchsorted(cum[agent], remaining_budgets[agent], side="right"))
        bids[cutoff:, agent] = 0.0


def _drop_random_legacy(
    bids: np.ndarray,
    result: AuctionResult,
    over_ratio: np.ndarray,
    rng_manager: RngManager,
    episode: int,
    tick: int,
) -> None:
    """Upstream run_test.adjust_over_cost: per slot, randomly drop a share of
    the over-spender's winning PVs. Legacy mode recreates default_rng(1) per
    agent exactly as upstream does."""
    winner = _winner_matrix(result.slot)
    for agent in np.where(over_ratio > 0)[0]:
        for slot_col in range(winner.shape[1]):
            pv_idx = np.where(winner[:, slot_col] == agent)[0]
            rng = (
                np.random.default_rng(seed=1)
                if rng_manager.legacy_mode
                else rng_manager.stream(episode, tick, f"{MOD_OVERSPEND}:{agent}:{slot_col}")
            )
            n_drop = math.ceil(pv_idx.size * over_ratio[agent])
            if n_drop > 0:
                dropped = rng.choice(pv_idx, n_drop, replace=False)
                bids[dropped, agent] = 0.0


def _winner_matrix(slot_agent_major: np.ndarray) -> np.ndarray:
    """(num_agent, num_pv) slot matrix -> (num_pv, 3) winner agent ids (-1 = none)."""
    slot = slot_agent_major.T
    num_pv = slot.shape[0]
    winner = np.full((num_pv, 3), -1, dtype=int)
    for pos in range(1, 4):
        hits = np.argwhere(slot == pos)
        if hits.size:
            winner[hits[:, 0], pos - 1] = hits[:, 1]
    return winner
