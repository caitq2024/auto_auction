"""ThresholdReplayEvaluator: clean-room re-implementation of the AIGB
threshold offline evaluation (win iff bid >= leastWinningCost, cost =
leastWinningCost). Written from the rule's mathematical definition — no AIGB
source copied (that repo has no LICENSE).

Reports BOTH conversion accountings (doc §6.4):
- expected: sum of clip(pValue,0,1) over won PVs (deterministic, low variance)
- sampled: upstream-style truncnorm value draw + Bernoulli (set sample=True)

Overspend handling follows the upstream random-drop loop when
mode="random_drop_legacy" (needed for parity with Phase 0 anchors), or a
deterministic sequential stop when mode="sequential_stop".
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from adsim.evaluation.metrics import competition_score


@dataclass
class ReplayResult:
    conversions_sampled: float
    conversions_expected: float
    cost: float
    win_pv: int
    total_pv: int
    cpa_sampled: float
    cpa_expected: float
    score_sampled: float
    score_expected: float


def replay_advertiser(
    df: pd.DataFrame,
    alpha_fn,
    budget: float,
    target_cpa: float,
    min_remaining_budget: float = 0.1,
    mode: str = "random_drop_legacy",
    seed: int = 1,
) -> ReplayResult:
    """df: one advertiser's PV log with columns timeStepIndex, pValue,
    pValueSigma, leastWinningCost. alpha_fn(tick, state) -> alpha.
    state exposes remaining_budget / cum_cost / cum_conv_expected."""
    rng = np.random.default_rng(seed)
    remaining = budget
    cum_cost = 0.0
    conv_sampled = 0.0
    conv_expected = 0.0
    win_total = 0
    total_pv = 0

    class _State:
        pass

    state = _State()
    for tick, g in df.sort_values("timeStepIndex").groupby("timeStepIndex"):
        pvalue = g["pValue"].to_numpy()
        sigma = g["pValueSigma"].to_numpy()
        lwc = g["leastWinningCost"].to_numpy()
        total_pv += len(g)
        if remaining < min_remaining_budget:
            continue
        state.remaining_budget = remaining
        state.cum_cost = cum_cost
        state.cum_conv_expected = conv_expected
        alpha = float(alpha_fn(int(tick), state))
        bids = alpha * pvalue

        win = bids >= lwc
        cost_arr = lwc * win
        over = max((cost_arr.sum() - remaining) / (cost_arr.sum() + 1e-4), 0)
        while over > 0:
            win_idx = np.where(win)[0]
            if mode == "random_drop_legacy":
                drop = rng.choice(win_idx, math.ceil(win_idx.size * over), replace=False)
            else:  # sequential_stop: drop from the tail of arrival order
                n_drop = math.ceil(win_idx.size * over)
                drop = win_idx[-n_drop:]
            bids[drop] = 0
            win = bids >= lwc
            cost_arr = lwc * win
            over = max((cost_arr.sum() - remaining) / (cost_arr.sum() + 1e-4), 0)

        tick_cost = float(cost_arr.sum())
        remaining -= tick_cost
        cum_cost += tick_cost
        win_total += int(win.sum())
        conv_expected += float(np.clip(pvalue, 0, 1)[win].sum())
        values = np.clip(rng.normal(pvalue, sigma), 0, 1) * win
        conv_sampled += float(rng.binomial(1, values).sum())

    cpa_s = cum_cost / (conv_sampled + 1e-10)
    cpa_e = cum_cost / (conv_expected + 1e-10)
    return ReplayResult(
        conversions_sampled=conv_sampled,
        conversions_expected=conv_expected,
        cost=cum_cost,
        win_pv=win_total,
        total_pv=total_pv,
        cpa_sampled=cpa_s,
        cpa_expected=cpa_e,
        score_sampled=competition_score(conv_sampled, cpa_s, target_cpa),
        score_expected=competition_score(conv_expected, cpa_e, target_cpa),
    )
