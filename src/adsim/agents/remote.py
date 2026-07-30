"""H0: AgentEndpoint protocol + RemoteAgent.

The AgentEndpoint contract (runtime-agnostic):
    POST <endpoint>  body: {"observation": {...}, "meta": {...}}
    resp: {"action": "set_alpha", "alpha": <number>, ...}

Anything that speaks this — a local FastAPI wrapper around LLMBidAgent, an
AgentCore Runtime agent behind InvokeAgentRuntime, a vLLM policy server —
plugs into the simulator via RemoteAgent without simulator changes.

Safety boundary stays HERE (simulator side), exactly like LLMBidAgent:
schema/NaN checks, alpha clipping, and the fallback chain never move into
the remote runtime.
"""
from __future__ import annotations

import json
import math
import time
import urllib.request
from dataclasses import asdict

import numpy as np

from adsim.agents.llm import LLMAgentConfig, LLMCallRecord
from adsim.agents.registry import PidAgent
from adsim.core.types import AdvertiserConfig, AgentObservation


class RemoteAgent:
    """Simulator-side client for any AgentEndpoint."""

    def __init__(
        self,
        endpoint_url: str,
        config: LLMAgentConfig | None = None,
        headers: dict[str, str] | None = None,
        timeout_sec: float = 60.0,
    ):
        self.endpoint_url = endpoint_url
        self.config = config or LLMAgentConfig()
        self.headers = headers or {}
        self.timeout_sec = timeout_sec
        self.last_alpha: float | None = None
        self.advertiser: AdvertiserConfig | None = None
        self._pid_fallback = PidAgent()
        self.trajectory: list[LLMCallRecord] = []
        self._observation: AgentObservation | None = None
        self._episode_meta: dict = {}

    def observe(self, observation: AgentObservation) -> None:
        self._observation = observation

    def reset(self, advertiser: AdvertiserConfig, episode: int) -> None:
        self.advertiser = advertiser
        self.last_alpha = None
        self._pid_fallback.reset(advertiser, episode)
        self.trajectory = []
        self._observation = None
        self._episode_meta = {"episode": episode, "advertiser_id": advertiser.advertiser_id}

    def bidding(
        self, tick, pv_values, pvalue_sigmas, history_pvalue_infos, history_bids,
        history_auction_results, history_impression_results,
        history_least_winning_costs, remaining_budget,
    ) -> np.ndarray:
        alpha = self._decide(tick, remaining_budget)
        self.last_alpha = alpha
        return alpha * pv_values

    def _decide(self, tick: int, remaining_budget: float) -> float:
        obs: dict
        if self._observation is not None and self._observation.tick_index == tick:
            obs = self._observation.to_dict()
        else:
            adv = self.advertiser
            obs = {"time": {"tick_index": tick, "num_tick": 48},
                   "budget": {"initial_budget": adv.budget if adv else None,
                              "remaining_budget": remaining_budget},
                   "performance": {"target_cpa": adv.cpa if adv else None},
                   "action_history": {"previous_alpha": self.last_alpha}}
        payload = json.dumps({"observation": obs,
                              "meta": {**self._episode_meta, "tick": tick}}).encode()
        t0 = time.time()
        raw: str | None = None
        error: str | None = None
        parsed: float | None = None
        try:
            req = urllib.request.Request(
                self.endpoint_url, data=payload, method="POST",
                headers={"Content-Type": "application/json", **self.headers})
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as r:
                raw = r.read().decode()
            data = json.loads(raw)
            alpha = data.get("alpha")
            if (isinstance(alpha, (int, float)) and not isinstance(alpha, bool)
                    and math.isfinite(alpha)):
                parsed = float(alpha)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"[:200]
        latency = time.time() - t0

        if parsed is not None:
            applied = float(np.clip(parsed, self.config.min_alpha, self.config.max_alpha))
            fallback = None
        elif self.last_alpha is not None:
            applied, fallback = self.last_alpha, "previous"
        else:
            try:
                applied = float(np.clip(
                    self._pid_fallback.compute_alpha(tick, remaining_budget),
                    self.config.min_alpha, self.config.max_alpha))
                fallback = "pid"
            except Exception:
                applied, fallback = self.config.safe_fixed_alpha, "fixed"

        self.trajectory.append(LLMCallRecord(
            tick=tick, prompt=payload.decode(), raw_output=raw, parsed_alpha=parsed,
            applied_alpha=applied, fallback=fallback, latency_sec=round(latency, 3),
            error=error))
        return applied
