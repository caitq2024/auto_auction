"""H1 PoC on the REAL AgentCore Runtime: full episode, gate metrics.

Uses a thin client subclass of RemoteAgent that swaps HTTP POST for
InvokeAgentRuntime (SigV4), keeping the simulator/safety path identical.

Usage:
    python harness/agentcore/poc_run_agentcore.py \
        --runtime-arn arn:aws:bedrock-agentcore:...:runtime/adsim_bidding_agent-xxx
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import boto3  # noqa: E402

from adsim.agents.remote import RemoteAgent  # noqa: E402
from adsim.core.runner import EpisodeRunner  # noqa: E402
from adsim.core.scenario import ScenarioConfig  # noqa: E402


class AgentCoreAgent(RemoteAgent):
    """RemoteAgent whose transport is InvokeAgentRuntime instead of raw HTTP."""

    def __init__(self, runtime_arn: str, **kwargs):
        super().__init__(endpoint_url=runtime_arn, **kwargs)
        self._client = boto3.client("bedrock-agentcore", region_name="us-west-2")
        self._session_id = f"adsim-poc-{uuid.uuid4().hex}"

    def _decide(self, tick: int, remaining_budget: float) -> float:
        import math

        import numpy as np

        from adsim.agents.llm import LLMCallRecord

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
                              "meta": {**self._episode_meta, "tick": tick}})
        t0 = time.time()
        raw: str | None = None
        error: str | None = None
        parsed: float | None = None
        try:
            r = self._client.invoke_agent_runtime(
                agentRuntimeArn=self.endpoint_url, qualifier="DEFAULT",
                runtimeSessionId=self._session_id, payload=payload)
            raw = r["response"].read().decode()
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
            tick=tick, prompt=payload, raw_output=raw, parsed_alpha=parsed,
            applied_alpha=applied, fallback=fallback,
            latency_sec=round(latency, 3), error=error))
        return applied


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime-arn", required=True)
    ap.add_argument("--pv-num", type=int, default=50000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="outputs/agentcore_poc_real")
    args = ap.parse_args()

    agent = AgentCoreAgent(args.runtime_arn)
    sc = ScenarioConfig.upstream_default_48(
        scenario_id="agentcore_poc_real", seed=args.seed, pv_num=args.pv_num,
        num_episode=1, controlled={0: ("pid", {})},
    )
    runner = EpisodeRunner(sc)
    runner.agents[0] = agent

    t0 = time.time()
    res = runner.run_episode(0)
    s = res.summaries[0]
    lat = [t.latency_sec for t in agent.trajectory]
    fb = sum(1 for t in agent.trajectory if t.fallback)

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "trajectory.jsonl", "w") as f:
        for t in agent.trajectory:
            f.write(json.dumps(asdict(t)) + "\n")
    report = {
        "runtime_arn": args.runtime_arn,
        "score": round(s.score, 2), "conversions": s.conversions,
        "actual_cpa": round(s.actual_cpa, 1),
        "budget_utilization": round(s.budget_utilization, 3),
        "decisions": len(lat), "fallback_rate": round(fb / max(len(lat), 1), 3),
        "latency_mean_sec": round(sum(lat) / max(len(lat), 1), 3),
        "latency_p95_sec": round(sorted(lat)[int(len(lat) * 0.95)] if lat else 0, 3),
        "wall_sec": round(time.time() - t0),
    }
    (out / "poc_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
