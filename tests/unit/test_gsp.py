"""Hand-calculated GSP unit tests (doc §15.1)."""
import numpy as np
import pytest

from adsim.auction.gsp import GspAuction
from adsim.core.rng import RngManager
from adsim.core.types import TrafficBatch


def make_auction(num_agent=5, reserve=0.0001, seed=7):
    return GspAuction(reserve, RngManager(seed), num_agent)


def clear_single_pv(bids_row, num_agent=5, reserve=0.0001):
    auction = make_auction(num_agent, reserve)
    auction.reset(0)
    batch = TrafficBatch(
        tick=0,
        pv_values=np.full((1, num_agent), 0.5),
        pvalue_sigmas=np.full((1, num_agent), 0.01),
    )
    bids = np.array([bids_row], dtype=float)
    return auction.clear(batch, bids, episode=0, tick=0)


def test_doc_example_slots_and_prices():
    # doc §15.1: bids = [0.9, 0.8, 0.6, 0.4, 0.2]
    r = clear_single_pv([0.9, 0.8, 0.6, 0.4, 0.2])
    assert r.slot[:, 0].tolist() == [1, 2, 3, 0, 0]
    # GSP next-price: slot1 pays 0.8, slot2 pays 0.6, slot3 pays 0.4
    np.testing.assert_allclose(r.cost[0, 0], 0.8)
    np.testing.assert_allclose(r.cost[1, 0], 0.6)
    np.testing.assert_allclose(r.cost[2, 0], 0.4)
    # losers pay nothing
    assert r.cost[3, 0] == 0 and r.cost[4, 0] == 0
    assert r.xi[:, 0].tolist() == [1, 1, 1, 0, 0]
    # least winning cost = 4th highest bid (floored at reserve)
    np.testing.assert_allclose(r.least_winning_cost[0], 0.4)


def test_reserve_price_floor():
    r = clear_single_pv([0.9, 0.00005, 0.00002, 0.00001, 0.0], reserve=0.0001)
    # next prices below reserve are floored; price == reserve marks unsold,
    # so slots whose GSP price hits the floor get zeroed (upstream quirk).
    assert r.cost[0, 0] == 0.0
    assert r.slot[0, 0] == 0


def test_no_win_no_cost_no_conversion():
    r = clear_single_pv([0.9, 0.8, 0.6, 0.4, 0.2])
    for loser in (3, 4):
        assert r.cost[loser, 0] == 0
        assert r.is_exposed[loser, 0] == 0
        assert r.conversion[loser, 0] == 0


def test_unexposed_no_conversion():
    # run many PVs; wherever is_exposed == 0, conversion must be 0
    auction = make_auction()
    auction.reset(0)
    rng = np.random.default_rng(0)
    batch = TrafficBatch(
        tick=0,
        pv_values=rng.uniform(0.3, 0.9, (200, 5)),
        pvalue_sigmas=np.full((200, 5), 0.05),
    )
    bids = rng.uniform(0, 1, (200, 5))
    r = auction.clear(batch, bids, 0, 0)
    assert (r.conversion[r.is_exposed == 0] == 0).all()


def test_raising_own_bid_never_lowers_rank():
    base = [0.5, 0.8, 0.6, 0.4, 0.2]
    r1 = clear_single_pv(base)
    rank_before = r1.slot[0, 0] if r1.slot[0, 0] > 0 else 99
    for higher in (0.65, 0.85, 1.5):
        row = list(base)
        row[0] = higher
        r2 = clear_single_pv(row)
        rank_after = r2.slot[0, 0] if r2.slot[0, 0] > 0 else 99
        assert rank_after <= rank_before
        rank_before = rank_after


def test_gsp_price_not_above_own_bid():
    r = clear_single_pv([0.9, 0.8, 0.6, 0.4, 0.2])
    winners = r.slot[:, 0] > 0
    own_bids = np.array([0.9, 0.8, 0.6, 0.4, 0.2])
    assert (r.cost[winners, 0] <= own_bids[winners] + 1e-12).all()


def test_slot_range():
    rng = np.random.default_rng(3)
    auction = make_auction()
    auction.reset(0)
    batch = TrafficBatch(
        tick=0,
        pv_values=rng.uniform(0, 0.9, (100, 5)),
        pvalue_sigmas=np.full((100, 5), 0.05),
    )
    r = auction.clear(batch, rng.uniform(0, 1, (100, 5)), 0, 0)
    assert set(np.unique(r.slot)).issubset({0, 1, 2, 3})
