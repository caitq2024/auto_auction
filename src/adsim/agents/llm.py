"""LLM bid agent (doc §11): one structured decision per tick.

Protocol: the model receives the serialized AgentObservation (JSON) plus a
fixed instruction prompt, and must return
    {"action": "set_alpha", "alpha": <float>, "confidence": <0-1>,
     "reason_code": "<UPPER_SNAKE>"}

Safety pipeline (doc §11.2), all enforced here, never inside the auction core:
  parse JSON -> schema check -> NaN/Inf check -> clip to [min_alpha, max_alpha]
  -> on any failure or timeout, fallback chain:
     previous valid alpha -> internal PID -> safe fixed alpha.

Every call is recorded (raw model output, parsed action, fallback used,
latency) into `trajectory` for SFT/GRPO export.

The client is pluggable: any callable (prompt: str) -> str. Tests use
MockLLMClient; a real client (Claude API / vLLM endpoint on the p5 box) just
needs to satisfy the same signature.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

import numpy as np

from adsim.agents.registry import PidAgent
from adsim.core.types import AdvertiserConfig, AgentObservation

LLMClient = Callable[[str], str]

SYSTEM_PROMPT_V1 = """You are an auto-bidding agent in a repeated ad auction. \
Each decision step you receive your current state as JSON. Choose one bid \
multiplier `alpha`: your bid on every impression this step will be \
alpha * predicted_conversion_probability. Higher alpha wins more traffic but \
spends budget faster and can violate your CPA (cost-per-acquisition) target; \
score is conversions, penalized by (target_cpa/actual_cpa)^2 when \
actual_cpa > target_cpa. Budget must last all 48 steps.

Scale hint: predicted conversion probabilities are tiny (mean around \
`traffic.current_pvalue_mean`, typically 1e-4 to 1e-3) while winning market \
prices are around 0.1-1.0 per impression, so competitive alpha values are \
typically in the tens to low hundreds. Watch `market.recent_win_rate`: if it \
stays 0 your alpha is too low to win anything.

Respond with ONLY a JSON object:
{"action": "set_alpha", "alpha": <number>, "confidence": <0..1>, \
"reason_code": "<SHORT_UPPER_SNAKE_REASON>"}"""

# v2 = v1 + explicit pacing discipline (measured: Haiku 5.74->6.55,
# Opus budget-util 35%->99% at 500k)
SYSTEM_PROMPT_V2 = """You are an auto-bidding agent in a repeated ad auction. \
Each decision step you receive your current state as JSON. Choose one bid \
multiplier `alpha`: your bid on every impression this step will be \
alpha * predicted_conversion_probability. Higher alpha wins more traffic but \
spends budget faster and can violate your CPA (cost-per-acquisition) target; \
score is conversions, penalized by (target_cpa/actual_cpa)^2 when \
actual_cpa > target_cpa. Budget must last all 48 steps.

Scale hint: predicted conversion probabilities are tiny (mean around \
`traffic.current_pvalue_mean`, typically 1e-4 to 1e-3) while winning market \
prices are around 0.1-1.0 per impression, so competitive alpha values are \
typically in the tens to low hundreds. Watch `market.recent_win_rate`: if it \
stays 0 your alpha is too low to win anything.

CRITICAL — unspent budget is pure loss: an episode that ends with budget \
left scored fewer conversions than it could have. The single most common \
mistake is bidding too timidly. Pacing rule of thumb: by step t you should \
have spent roughly t/48 of the initial budget; compare \
`budget.remaining_budget_ratio` with `time.tick_ratio_remaining` every step — \
if remaining_budget_ratio is HIGHER, you are behind pace: raise alpha \
decisively (x1.3-x2, not +5). Only back off when actual_cpa exceeds \
target_cpa AND you are on/ahead of pace. Ending the day with more than ~10% \
budget unspent is a failure mode, not prudence. A good alpha found via \
`historical_win_rate` feedback beats a "safe" low alpha that wins nothing.

Respond with ONLY a JSON object:
{"action": "set_alpha", "alpha": <number>, "confidence": <0..1>, \
"reason_code": "<SHORT_UPPER_SNAKE_REASON>"}"""

# platform default
SYSTEM_PROMPT = SYSTEM_PROMPT_V2

PROMPT_TEMPLATES = {
    "v1": {"label": "v1 基础版（规则 + 尺度提示）", "text": SYSTEM_PROMPT_V1},
    "v2": {"label": "v2 pacing 版（v1 + 花钱纪律，当前默认）", "text": SYSTEM_PROMPT_V2},
}


@dataclass
class LLMCallRecord:
    tick: int
    prompt: str
    raw_output: str | None
    parsed_alpha: float | None
    applied_alpha: float
    fallback: str | None  # None | "previous" | "pid" | "fixed"
    latency_sec: float
    error: str | None = None
    # OTEL-compatible ids (H0): JSONL export today; OTLP/AgentCore
    # Observability exporter in H4
    trace_id: str | None = None
    span_id: str | None = None


@dataclass
class LLMAgentConfig:
    min_alpha: float = 0.0
    max_alpha: float = 200.0
    safe_fixed_alpha: float = 15.0
    timeout_sec: float = 30.0


class LLMBidAgent:
    def __init__(
        self,
        client: LLMClient,
        config: LLMAgentConfig | None = None,
        prompt_version: str = "v1",
        system_prompt: str | None = None,
    ):
        self.client = client
        self.config = config or LLMAgentConfig()
        self.prompt_version = prompt_version
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self.last_alpha: float | None = None
        self.advertiser: AdvertiserConfig | None = None
        self._pid_fallback = PidAgent()
        self.trajectory: list[LLMCallRecord] = []
        self._observation: AgentObservation | None = None

    def observe(self, observation: AgentObservation) -> None:
        """Runner (or rollout driver) supplies the aggregated observation
        before calling bidding()."""
        self._observation = observation

    def reset(self, advertiser: AdvertiserConfig, episode: int) -> None:
        import secrets

        self.advertiser = advertiser
        self.last_alpha = None
        self._pid_fallback.reset(advertiser, episode)
        self.trajectory = []
        self._observation = None
        self._trace_id = secrets.token_hex(16)  # one trace per episode

    def bidding(
        self, tick, pv_values, pvalue_sigmas, history_pvalue_infos, history_bids,
        history_auction_results, history_impression_results,
        history_least_winning_costs, remaining_budget,
    ) -> np.ndarray:
        alpha = self._decide(tick, remaining_budget)
        self.last_alpha = alpha
        return alpha * pv_values

    # -- decision pipeline ------------------------------------------------
    def _decide(self, tick: int, remaining_budget: float) -> float:
        prompt = self._build_prompt(tick, remaining_budget)
        t0 = time.time()
        raw: str | None = None
        error: str | None = None
        parsed: float | None = None
        try:
            raw = self.client(prompt)
            parsed = self._parse_and_validate(raw)
        except Exception as e:  # timeout, network, parse — all go to fallback
            error = f"{type(e).__name__}: {e}"
        latency = time.time() - t0

        if parsed is not None:
            applied = float(np.clip(parsed, self.config.min_alpha, self.config.max_alpha))
            fallback = None
        else:
            applied, fallback = self._fallback(tick, remaining_budget)

        import secrets

        self.trajectory.append(
            LLMCallRecord(
                tick=tick, prompt=prompt, raw_output=raw, parsed_alpha=parsed,
                applied_alpha=applied, fallback=fallback, latency_sec=round(latency, 3),
                error=error,
                trace_id=getattr(self, "_trace_id", None), span_id=secrets.token_hex(8),
            )
        )
        return applied

    def _build_prompt(self, tick: int, remaining_budget: float) -> str:
        obs: dict[str, Any]
        if self._observation is not None and self._observation.tick_index == tick:
            obs = self._observation.to_dict()
        else:  # minimal fallback observation if runner didn't call observe()
            adv = self.advertiser
            obs = {
                "time": {"tick_index": tick, "num_tick": 48},
                "budget": {
                    "initial_budget": adv.budget if adv else None,
                    "remaining_budget": remaining_budget,
                },
                "performance": {"target_cpa": adv.cpa if adv else None},
                "action_history": {"previous_alpha": self.last_alpha},
            }
        return f"{self.system_prompt}\n\nCurrent state:\n{json.dumps(obs)}"

    def _parse_and_validate(self, raw: str) -> float | None:
        data = json.loads(self._extract_first_json_object(raw))
        if not isinstance(data, dict) or data.get("action") != "set_alpha":
            return None
        alpha = data.get("alpha")
        if not isinstance(alpha, (int, float)) or isinstance(alpha, bool):
            return None
        if math.isnan(alpha) or math.isinf(alpha):
            return None
        return float(alpha)

    @staticmethod
    def _extract_first_json_object(raw: str) -> str:
        """Return the first balanced {...} block — models often wrap the JSON
        in markdown fences or append prose after it."""
        start = raw.find("{")
        if start < 0:
            raise ValueError("no JSON object in model output")
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(raw)):
            ch = raw[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return raw[start : i + 1]
        raise ValueError("unbalanced JSON object in model output")

    def _fallback(self, tick: int, remaining_budget: float) -> tuple[float, str]:
        if self.last_alpha is not None:
            return self.last_alpha, "previous"
        try:
            alpha = self._pid_fallback.compute_alpha(tick, remaining_budget)
            return float(np.clip(alpha, self.config.min_alpha, self.config.max_alpha)), "pid"
        except Exception:
            return self.config.safe_fixed_alpha, "fixed"


class MockLLMClient:
    """Deterministic scripted client for tests: returns queued responses,
    then repeats the last one."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        idx = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[idx]
