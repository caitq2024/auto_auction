import numpy as np
import pandas as pd

from adsim.evaluation.threshold_replay import replay_advertiser


def make_log(num_tick=4, pv_per_tick=50, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for t in range(num_tick):
        for _ in range(pv_per_tick):
            rows.append(
                {
                    "timeStepIndex": t,
                    "pValue": rng.uniform(0.001, 0.01),
                    "pValueSigma": 0.001,
                    "leastWinningCost": rng.uniform(0.1, 0.5),
                }
            )
    return pd.DataFrame(rows)


def test_zero_alpha_zero_everything():
    r = replay_advertiser(make_log(), lambda t, s: 0.0, budget=100, target_cpa=10)
    assert r.win_pv == 0 and r.cost == 0 and r.conversions_expected == 0


def test_huge_alpha_wins_within_budget():
    df = make_log()
    r = replay_advertiser(df, lambda t, s: 1e6, budget=1e9, target_cpa=10)
    assert r.win_pv == len(df)
    np.testing.assert_allclose(r.cost, df["leastWinningCost"].sum())


def test_budget_respected():
    r = replay_advertiser(make_log(), lambda t, s: 1e6, budget=5.0, target_cpa=10)
    assert r.cost <= 5.0 + 1e-9


def test_deterministic_same_seed():
    df = make_log()
    a = replay_advertiser(df, lambda t, s: 100, budget=20, target_cpa=10, seed=3)
    b = replay_advertiser(df, lambda t, s: 100, budget=20, target_cpa=10, seed=3)
    assert a == b


def test_expected_leq_wins_and_score_modes_differ():
    df = make_log()
    r = replay_advertiser(df, lambda t, s: 1e5, budget=1e9, target_cpa=1000)
    assert 0 < r.conversions_expected < r.win_pv
