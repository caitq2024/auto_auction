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

# LLM baseline runs whose controlled-slot summaries join a comparison's
# leaderboard: comparison key -> list of (run dir, display name)
LLM_INTO_LEADERBOARD = {
    "fullscale_500k": [("outputs/llm_baseline_haiku_500k", "LLM Haiku 4.5")],
    "midscale_50k": [
        ("outputs/llm_baseline_haiku_v3", "LLM Haiku 4.5"),
        ("outputs/llm_baseline_opus48_v3", "LLM Opus 4.8"),
    ],
}

LLM_RUNS = {
    "haiku_500k": {
        "dir": "outputs/llm_baseline_haiku_500k",
        "label": "Claude Haiku 4.5 · 500k 市场",
        "model": "us.anthropic.claude-haiku-4-5",
        "pv_num": 500000,
    },
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


def _candidate_from_dir(cand_dir: Path, raw_name: str, display: str) -> dict:
    summary = pd.read_parquet(cand_dir / "episode_summary.parquet")
    ticks = pd.read_parquet(cand_dir / "tick_events.parquet")
    s = summary[summary.advertiser_id == CONTROLLED_SLOT]
    t = ticks[ticks.advertiser_id == CONTROLLED_SLOT]
    return _build_candidate(raw_name, display, s, t)


def export_comparison(key: str, cfg: dict) -> dict:
    base = ROOT / cfg["dir"]
    candidates = []
    # candidate names may contain '/', nesting their output dirs — find leaves
    cand_dirs = sorted({p.parent for p in base.rglob("episode_summary.parquet")})
    for cand_dir in cand_dirs:
        raw_name = str(cand_dir.relative_to(base))
        display = cfg["names"].get(raw_name, raw_name)
        candidates.append(_candidate_from_dir(cand_dir, raw_name, display))
    for run_dir, display in LLM_INTO_LEADERBOARD.get(key, []):
        p = ROOT / run_dir
        if (p / "episode_summary.parquet").exists():
            candidates.append(_candidate_from_dir(p, run_dir, display))
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


def _build_candidate(raw_name: str, display: str, s: pd.DataFrame, t: pd.DataFrame) -> dict:
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
    return {
        "id": raw_name,
        "name": display,
        "score_mean": round(sum(scores) / len(scores), 4),
        "conversions_mean": round(sum(e["conversions"] for e in episodes) / len(episodes), 2),
        "actual_cpa_mean": round(sum(e["actual_cpa"] for e in episodes) / len(episodes), 2),
        "budget_utilization_mean": round(
            sum(e["budget_utilization"] for e in episodes) / len(episodes), 4),
        "episodes": episodes,
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


def export_sample_rows() -> list[dict]:
    """A few representative auction-log rows for the explainer module."""
    log = ROOT / "third_party/AuctionNet/data/log/0.csv"
    if not log.exists():
        return []
    # scan in chunks until each case type is found (early ticks have low bids)
    win_conv = win_noconv = lose = None
    cols = ["advertiserNumber", "timeStepIndex", "pValue", "bid",
            "leastWinningCost", "adSlot", "cost", "isExposed", "conversionAction", "xi"]
    for chunk in pd.read_csv(log, usecols=cols, chunksize=500000):
        df = chunk[chunk.advertiserNumber == CONTROLLED_SLOT]
        if win_conv is None:
            m = df[(df.isExposed == 1) & (df.conversionAction == 1)]
            if len(m):
                win_conv = m.iloc[[0]]
        if win_noconv is None:
            m = df[(df.isExposed == 1) & (df.conversionAction == 0) & (df.cost > 0.1)]
            if len(m):
                win_noconv = m.iloc[[0]]
        if lose is None:
            m = df[(df.xi == 0) & (df.bid > 0.03)]
            if len(m):
                lose = m.iloc[[0]]
        if win_conv is not None and win_noconv is not None and lose is not None:
            break
    empty = pd.DataFrame()
    win_conv = win_conv if win_conv is not None else empty
    win_noconv = win_noconv if win_noconv is not None else empty
    lose = lose if lose is not None else empty
    cases = []
    for frame, label, note in [
        (win_conv, "赢得曝光且带来转化", "出价高于市场价获得坑位并曝光；按 pValue 抽样出了一次真实转化——花 cost 换 1 个转化"),
        (win_noconv, "赢得曝光但没有转化", "同样赢了并付了钱，但转化是概率事件（pValue 只有千分之一量级），大多数曝光不转化"),
        (lose, "出价太低，竞价失败", "bid 低于当时的最低获胜价（leastWinningCost），没有坑位、不花钱也没有转化"),
    ]:
        if len(frame) == 0:
            continue
        r = frame.iloc[0]
        cases.append({
            "label": label,
            "note": note,
            "row": {
                "timeStepIndex": int(r.timeStepIndex),
                "pValue": round(float(r.pValue), 6),
                "bid": round(float(r.bid), 4),
                "leastWinningCost": round(float(r.leastWinningCost), 4),
                "adSlot": int(r.adSlot),
                "isExposed": int(r.isExposed),
                "cost": round(float(r.cost), 4),
                "conversionAction": int(r.conversionAction),
            },
        })
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "demo/public/demo_data.json"))
    args = ap.parse_args()

    data = {
        "generated_from": "auction-sim-platform experiments (simulated results only)",
        "sample_rows": export_sample_rows(),
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
