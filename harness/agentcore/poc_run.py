"""H1 PoC driver: run one episode with the bidding agent behind an endpoint.

Measures the H1 gate metric — per-decision latency vs local in-process
baseline — and dumps the trajectory for trace-quality comparison.

Usage:
    python harness/agentcore/poc_run.py --endpoint http://localhost:9000/invocations
    python harness/agentcore/poc_run.py --endpoint <agentcore-url> --pv-num 50000
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from adsim.agents.remote import RemoteAgent  # noqa: E402
from adsim.core.runner import EpisodeRunner  # noqa: E402
from adsim.core.scenario import ScenarioConfig  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--pv-num", type=int, default=50000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="outputs/agentcore_poc")
    args = ap.parse_args()

    agent = RemoteAgent(args.endpoint)
    sc = ScenarioConfig.upstream_default_48(
        scenario_id="agentcore_poc", seed=args.seed, pv_num=args.pv_num,
        num_episode=1, controlled={0: ("pid", {})},
    )
    runner = EpisodeRunner(sc)
    runner.agents[0] = agent

    t0 = time.time()
    res = runner.run_episode(0)
    s = res.summaries[0]
    lat = [t.latency_sec for t in agent.trajectory]
    fb = sum(1 for t in agent.trajectory if t.fallback)

    out = Path(ROOT / args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "trajectory.jsonl", "w") as f:
        for t in agent.trajectory:
            f.write(json.dumps(asdict(t)) + "\n")

    report = {
        "endpoint": args.endpoint,
        "score": round(s.score, 2),
        "conversions": s.conversions,
        "actual_cpa": round(s.actual_cpa, 1),
        "budget_utilization": round(s.budget_utilization, 3),
        "decisions": len(lat),
        "fallback_rate": round(fb / max(len(lat), 1), 3),
        "latency_mean_sec": round(sum(lat) / max(len(lat), 1), 3),
        "latency_p95_sec": round(sorted(lat)[int(len(lat) * 0.95)] if lat else 0, 3),
        "wall_sec": round(time.time() - t0),
    }
    (out / "poc_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
