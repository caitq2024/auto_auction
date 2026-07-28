"""Parity: internal runner (legacy_rng + random_drop_legacy) vs the Phase 0
upstream anchor (outputs/phase0/online_pid_pv5000_ep1_seed1.json).

Target: player conversions (reward) and cost match the upstream run of the
same scenario (PID player at slot 0, 5000 PV, episode 0, neuripsPvGen).

Known accounting difference (documented): upstream counts compete_pv for all
ticks; we count only ticks where the agent actually bid. Not asserted here.
"""
import json
from pathlib import Path

import pytest

from adsim.core.runner import EpisodeRunner
from adsim.core.scenario import ScenarioConfig

ROOT = Path(__file__).resolve().parents[2]
ANCHOR = ROOT / "outputs" / "phase0" / "online_pid_pv5000_ep1_seed1.json"


@pytest.fixture(scope="module")
def internal_result():
    scenario = ScenarioConfig.upstream_default_48(
        scenario_id="parity_pid_5k",
        seed=1,
        pv_num=5000,
        legacy_rng=True,
        budget_exhaustion_mode="random_drop_legacy",
        controlled={0: ("pid", {})},
    )
    return EpisodeRunner(scenario).run_episode(0, record_observations=False)


@pytest.mark.skipif(not ANCHOR.exists(), reason="phase0 anchor missing")
def test_player_conversions_match_upstream(internal_result):
    anchor = json.loads(ANCHOR.read_text())["result"]
    s0 = internal_result.summaries[0]
    assert s0.conversions == float(anchor["reward"])


@pytest.mark.skipif(not ANCHOR.exists(), reason="phase0 anchor missing")
def test_player_cost_matches_upstream(internal_result):
    anchor = json.loads(ANCHOR.read_text())["result"]
    cost = internal_result.summaries[0].cost
    assert abs(cost - float(anchor["allCost"])) < 1.0, (cost, anchor["allCost"])


@pytest.mark.skipif(not ANCHOR.exists(), reason="phase0 anchor missing")
def test_player_win_pv_close(internal_result):
    anchor = json.loads(ANCHOR.read_text())["result"]
    s0 = internal_result.summaries[0]
    up = float(anchor["allWinPv"])
    assert abs(s0.win_pv - up) / max(up, 1) < 0.02, (s0.win_pv, up)
