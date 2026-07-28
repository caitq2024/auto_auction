"""Aggregate experiment outputs into demo/public/demo_data.json for the SPA.

Sources (all already on disk, no recomputation):
- comparison runs (outputs/compare_*): leaderboard + per-tick replay curves
- LLM baselines (outputs/llm_baseline_*): decision-trace trajectories

Usage:
    python scripts/export_demo.py --out demo/public/demo_data.json
"""
import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# scenario key -> (dir, label, pv_num, display names for candidates)
COMPARISONS = {
    "fullscale_500k": {
        "dir": "outputs/compare_fullscale_v2",
        "label": "500k PV 全规模（论文标准市场）",
        "pv_num": 500000,
        "episodes": 2,
        "names": {
            "pid": "PID",
            "upstream_iql": "IQL (官方RL)",
            "dt_model_diroutputs/dt_baseline_500k/saved_model/DTtest": "DT (自训 500k)",
            "dt_model_diroutputs": "DT (自训 500k)",  # in case rglob resolves partial path
        },
    },
    "midscale_50k": {
        "dir": "outputs/compare_dt_v1",
        "label": "50k PV 快速实验",
        "pv_num": 50000,
        "episodes": 4,
        "names": {"pid": "PID", "upstream_iql": "IQL (官方RL)", "dt": "DT (自训 50k)"},
    },
}

LLM_RUNS = {
    "haiku_v3": {
        "dir": "outputs/llm_baseline_haiku_v3",
        "label": "Claude Haiku 4.5 (prompt-only)",
        "model": "us.anthropic.claude-haiku-4-5",
        "pv_num": 50000,
    },
    "opus48_v3": {
        "dir": "outputs/llm_baseline_opus48_v3",
        "label": "Claude Opus 4.8 (prompt-only)",
        "model": "us.anthropic.claude-opus-4-8",
        "pv_num": 50000,
    },
}

CONTROLLED_SLOT = 0


def export_comparison(key: str, cfg: dict) -> dict:
    base = ROOT / cfg["dir"]
    candidates = []
    # candidate names may contain '/', nesting their output dirs — find leaves
    cand_dirs = sorted({p.parent for p in base.rglob("episode_summary.parquet")})
    for cand_dir in cand_dirs:
        summary = pd.read_parquet(cand_dir / "episode_summary.parquet")
        ticks = pd.read_parquet(cand_dir / "tick_events.parquet")
        s = summary[summary.advertiser_id == CONTROLLED_SLOT]
        t = ticks[ticks.advertiser_id == CONTROLLED_SLOT]
        raw_name = str(cand_dir.relative_to(base))
        display = cfg["names"].get(raw_name, raw_name)
        episodes = []
        for ep, g in t.groupby("episode"):
            g = g.sort_values("tick")
            srow = s[s.episode == ep].iloc[0]
            episodes.append({
                "episode": int(ep),
                "score": round(float(srow.score), 4),
                "conversions": float(srow.conversions),
                "cost": round(float(srow.cost), 2),
                "actual_cpa": round(float(srow.actual_cpa), 2),
                "budget_utilization": round(float(srow.budget_utilization), 4),
                "ticks": {
                    "tick": g.tick.tolist(),
                    "alpha": [None if pd.isna(a) else round(float(a), 2) for a in g.alpha],
                    "cost": [round(float(c), 2) for c in g.cost],
                    "cum_cost": [round(float(c), 2) for c in g.cost.cumsum()],
                    "conversions": [float(c) for c in g.conversions],
                    "cum_conversions": [float(c) for c in g.conversions.cumsum()],
                    "win_pv": [int(w) for w in g.exposed_pv],
                    "remaining_budget": [round(float(r), 2) for r in g.remaining_budget_after],
                },
            })
        scores = [e["score"] for e in episodes]
        candidates.append({
            "id": raw_name,
            "name": display,
            "score_mean": round(sum(scores) / len(scores), 4),
            "conversions_mean": round(sum(e["conversions"] for e in episodes) / len(episodes), 2),
            "actual_cpa_mean": round(sum(e["actual_cpa"] for e in episodes) / len(episodes), 2),
            "budget_utilization_mean": round(
                sum(e["budget_utilization"] for e in episodes) / len(episodes), 4),
            "episodes": episodes,
        })
    candidates.sort(key=lambda c: -c["score_mean"])
    meta_files = list(base.rglob("run_meta.json"))
    meta = json.loads(meta_files[0].read_text()) if meta_files else {}
    return {
        "key": key,
        "label": cfg["label"],
        "pv_num": cfg["pv_num"],
        "budget": 2900.0,
        "target_cpa": 100.0,
        "seed": meta.get("seed", 1),
        "candidates": candidates,
    }


def export_llm_run(key: str, cfg: dict) -> dict:
    base = ROOT / cfg["dir"]
    episodes = []
    for traj_file in sorted(base.glob("trajectory_ep*.jsonl")):
        ep = int(traj_file.stem.replace("trajectory_ep", ""))
        calls = [json.loads(line) for line in traj_file.open()]
        episodes.append({
            "episode": ep,
            "calls": [{
                "tick": c["tick"],
                # keep observation (parsed from prompt tail) light: extract the state JSON
                "observation": _extract_obs(c["prompt"]),
                "raw_output": (c["raw_output"] or "")[:1500],
                "parsed_alpha": c["parsed_alpha"],
                "applied_alpha": c["applied_alpha"],
                "fallback": c["fallback"],
                "latency_sec": c["latency_sec"],
                "error": (c["error"] or None) and c["error"][:200],
            } for c in calls],
            "fallback_rate": round(
                sum(1 for c in calls if c["fallback"]) / max(len(calls), 1), 4),
            "mean_latency_sec": round(
                sum(c["latency_sec"] for c in calls) / max(len(calls), 1), 2),
        })
    meta_file = base / "run_meta.json"
    meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
    return {
        "key": key,
        "label": cfg["label"],
        "model": cfg["model"],
        "pv_num": cfg["pv_num"],
        "total_input_tokens": meta.get("total_input_tokens"),
        "total_output_tokens": meta.get("total_output_tokens"),
        "episodes": episodes,
    }


def _extract_obs(prompt: str) -> dict | None:
    marker = "Current state:\n"
    i = prompt.rfind(marker)
    if i < 0:
        return None
    try:
        return json.loads(prompt[i + len(marker):])
    except json.JSONDecodeError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "demo/public/demo_data.json"))
    args = ap.parse_args()

    data = {
        "generated_from": "auction-sim-platform experiments (simulated results only)",
        "comparisons": [export_comparison(k, c) for k, c in COMPARISONS.items()
                        if (ROOT / c["dir"]).exists()],
        "llm_runs": [export_llm_run(k, c) for k, c in LLM_RUNS.items()
                     if (ROOT / c["dir"]).exists()],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False))
    print(f"{out} written, {out.stat().st_size/1e6:.1f}MB")
    print(f"comparisons: {[c['key'] for c in data['comparisons']]}")
    print(f"llm_runs: {[r['key'] for r in data['llm_runs']]}")


if __name__ == "__main__":
    main()
