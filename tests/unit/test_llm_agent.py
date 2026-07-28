"""LLM agent safety pipeline tests (doc §11.2 / §15.5 LLM 阶段标准)."""
import json

import numpy as np
import pytest

from adsim.agents.llm import LLMAgentConfig, LLMBidAgent, MockLLMClient
from adsim.core.types import AdvertiserConfig

ADV = AdvertiserConfig(advertiser_id=0, budget=2900, cpa=100, category=0, strategy="llm")


def make_agent(responses, **cfg):
    agent = LLMBidAgent(MockLLMClient(responses), LLMAgentConfig(**cfg))
    agent.reset(ADV, episode=0)
    return agent


def bid_once(agent, tick=0, remaining=2900.0):
    pv = np.array([0.001, 0.002, 0.003])
    return agent.bidding(tick, pv, pv * 0.1, [], [], [], [], [], remaining_budget=remaining)


def test_valid_json_applied():
    agent = make_agent(['{"action": "set_alpha", "alpha": 72.5, "confidence": 0.8, "reason_code": "OK"}'])
    bids = bid_once(agent)
    assert agent.last_alpha == 72.5
    np.testing.assert_allclose(bids, 72.5 * np.array([0.001, 0.002, 0.003]))
    assert agent.trajectory[0].fallback is None


def test_markdown_fenced_json_accepted():
    agent = make_agent(['```json\n{"action": "set_alpha", "alpha": 10}\n```'])
    bid_once(agent)
    assert agent.last_alpha == 10


def test_alpha_clipped():
    agent = make_agent(['{"action": "set_alpha", "alpha": 99999}'], max_alpha=200.0)
    bid_once(agent)
    assert agent.last_alpha == 200.0


def test_nan_and_inf_rejected_fallback_pid():
    for bad in ['{"action": "set_alpha", "alpha": NaN}',
                '{"action": "set_alpha", "alpha": Infinity}']:
        agent = make_agent([bad])
        bid_once(agent)
        rec = agent.trajectory[0]
        assert rec.fallback == "pid"  # no previous alpha on tick 0
        assert rec.applied_alpha == 15.0  # PID base_action


def test_garbage_falls_back_then_previous_valid():
    agent = make_agent([
        '{"action": "set_alpha", "alpha": 50}',
        "sorry, I cannot help with that",
    ])
    bid_once(agent, tick=0)
    bid_once(agent, tick=1)
    assert agent.trajectory[1].fallback == "previous"
    assert agent.trajectory[1].applied_alpha == 50


def test_client_exception_handled():
    def exploding(prompt):
        raise TimeoutError("model timeout")

    agent = LLMBidAgent(exploding)
    agent.reset(ADV, 0)
    bids = bid_once(agent)
    rec = agent.trajectory[0]
    assert rec.error and "TimeoutError" in rec.error
    assert rec.fallback == "pid"
    assert np.isfinite(bids).all()


def test_trajectory_records_everything():
    agent = make_agent(['{"action": "set_alpha", "alpha": 30, "confidence": 0.9, "reason_code": "PACE_OK"}'])
    bid_once(agent)
    rec = agent.trajectory[0]
    assert rec.prompt and "Current state" in rec.prompt
    assert json.loads(rec.raw_output)["alpha"] == 30
    assert rec.latency_sec >= 0


def test_wrong_action_type_rejected():
    agent = make_agent(['{"action": "buy_everything", "alpha": 30}'])
    bid_once(agent)
    assert agent.trajectory[0].fallback == "pid"
