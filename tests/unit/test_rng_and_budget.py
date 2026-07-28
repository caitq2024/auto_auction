"""RNG manager determinism tests (doc §15.3) and budget control tests."""
import numpy as np

from adsim.auction.budget_control import clear_with_budget
from adsim.auction.gsp import GspAuction
from adsim.core.rng import MOD_CONVERSION, MOD_EXPOSURE, RngManager
from adsim.core.types import TrafficBatch


def test_same_seed_same_stream():
    a = RngManager(42).stream(0, 3, MOD_EXPOSURE).random(5)
    b = RngManager(42).stream(0, 3, MOD_EXPOSURE).random(5)
    np.testing.assert_array_equal(a, b)


def test_different_seed_differs():
    a = RngManager(42).stream(0, 3, MOD_EXPOSURE).random(5)
    b = RngManager(43).stream(0, 3, MOD_EXPOSURE).random(5)
    assert not np.array_equal(a, b)


def test_streams_independent_across_tick_and_module():
    m = RngManager(42)
    assert not np.array_equal(
        m.stream(0, 3, MOD_EXPOSURE).random(5), m.stream(0, 4, MOD_EXPOSURE).random(5)
    )
    assert not np.array_equal(
        m.stream(0, 3, MOD_EXPOSURE).random(5), m.stream(0, 3, MOD_CONVERSION).random(5)
    )
    assert not np.array_equal(
        m.stream(0, 3, MOD_EXPOSURE).random(5), m.stream(1, 3, MOD_EXPOSURE).random(5)
    )


def test_legacy_mode_reproduces_fixed_seed():
    m = RngManager(42, legacy_mode=True)
    a = m.stream(0, 3, MOD_EXPOSURE).random(5)
    b = np.random.default_rng(1).random(5)
    np.testing.assert_array_equal(a, b)


def _run_budget(mode: str, budget: float, seed=11, num_pv=400, num_agent=4):
    rng = RngManager(seed)
    auction = GspAuction(0.0001, rng, num_agent)
    auction.reset(0)
    g = np.random.default_rng(0)
    batch = TrafficBatch(
        tick=0,
        pv_values=g.uniform(0.2, 0.9, (num_pv, num_agent)),
        pvalue_sigmas=np.full((num_pv, num_agent), 0.03),
    )
    bids = g.uniform(0.1, 1.0, (num_pv, num_agent))
    remaining = np.full(num_agent, budget)
    result = clear_with_budget(
        batch, bids, remaining,
        clear=lambda tb, b: auction.clear(tb, b, 0, 0),
        mode=mode, rng_manager=rng, episode=0, tick=0,
    )
    return result.real_cost_per_agent(), budget


def test_sequential_stop_never_exceeds_budget():
    cost, budget = _run_budget("sequential_stop", budget=5.0)
    assert (cost <= budget + 1e-9).all()


def test_random_drop_legacy_never_exceeds_budget():
    cost, budget = _run_budget("random_drop_legacy", budget=5.0)
    assert (cost <= budget + 1e-9).all()


def test_no_constraint_when_budget_ample():
    cost, budget = _run_budget("sequential_stop", budget=1e9)
    assert cost.sum() > 0
