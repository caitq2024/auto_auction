"""End-to-end determinism (doc §15.3): same scenario+seed => identical
summaries; different seed => different outcomes."""
from dataclasses import asdict

import pytest

from adsim.core.runner import EpisodeRunner
from adsim.core.scenario import ScenarioConfig


def run_once(seed: int, pv_num: int = 2000):
    sc = ScenarioConfig.upstream_default_48(
        scenario_id=f"det_{seed}", seed=seed, pv_num=pv_num,
        controlled={0: ("pid", {})},
    )
    res = EpisodeRunner(sc).run_episode(0, record_observations=False)
    return [asdict(s) for s in res.summaries]


@pytest.mark.slow
def test_same_seed_identical():
    assert run_once(7) == run_once(7)


@pytest.mark.slow
def test_different_seed_differs():
    a, b = run_once(7), run_once(8)
    assert any(x["conversions"] != y["conversions"] or x["cost"] != y["cost"]
               for x, y in zip(a, b))
