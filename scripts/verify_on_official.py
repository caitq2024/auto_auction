"""Task 4: cross-check strategy ranking on OFFICIAL data distribution.

Replays each strategy's alpha SEQUENCE (as recorded in our 500k simulator
comparison runs) against official period CSVs via threshold replay. This
freezes opponents (offline caveat) but answers the key question: do the
alpha trajectories our strategies produce remain sensibly ranked under the
official price/pValue distribution?

Also includes an adaptive PID run *natively* on official data (it only needs
budget feedback, no model), as a same-distribution reference.

Usage:
    python scripts/verify_on_official.py --period data/official/period-7.csv
"""
import argparse
import json
from pathlib import Path

import pandas as pd

from adsim.evaluation.threshold_replay import replay_advertiser

ROOT = Path(__file__).resolve().parents[1]

# alpha trajectories from the 500k simulator comparison (episode 0, slot 0)
ALPHA_SOURCES = {
    "PID": "outputs/compare_fullscale_v2/pid/tick_events.parquet",
    "IQL": "outputs/compare_fullscale_v2/upstream_iql/tick_events.parquet",
    "DT(自产数据)": "outputs/compare_fullscale_v2/dt_model_diroutputs/dt_baseline_500k/saved_model/DTtest/tick_events.parquet",
}
LLM_TRAJS = {
    "LLM Opus4.8": "outputs/llm_baseline_opus48_500k/trajectory_ep0.jsonl",
    "LLM Haiku4.5": "outputs/llm_baseline_haiku_500k/trajectory_ep0.jsonl",
}


def alpha_seq_from_parquet(path: Path) -> list[float]:
    """Per-tick alpha. Upstream-adapter agents (IQL etc.) don't expose
    last_alpha — the alpha column is NaN for them. Reconstruct the effective
    alpha from bid_mean / current_pvalue_mean instead of treating NaN as 0
    (which silently zeroed IQL's whole trajectory in the first version of
    this script)."""
    t = pd.read_parquet(path)
    t = t[(t.advertiser_id == 0) & (t.episode == 0)].sort_values("tick")
    seq: list[float] = []
    for _, r in t.iterrows():
        if pd.notna(r.alpha):
            seq.append(float(r.alpha))
            continue
        obs = json.loads(r.observation_json) if r.observation_json else None
        pv_mean = obs["traffic"]["current_pvalue_mean"] if obs else None
        seq.append(float(r.bid_mean / pv_mean) if pv_mean else 0.0)
    return seq


def alpha_seq_from_jsonl(path: Path) -> list[float]:
    return [json.loads(l)["applied_alpha"] for l in open(path)]


def replay_sequence(df: pd.DataFrame, seq: list[float], budget: float, cpa: float):
    return replay_advertiser(
        df, lambda t, s: seq[t] if t < len(seq) else seq[-1],
        budget=budget, target_cpa=cpa, seed=1,
    )


def adaptive_pid(df: pd.DataFrame, budget: float, cpa: float):
    state = {"alpha": 15.0, "last_remaining": budget}

    def pid_alpha(t, s):
        if t > 0:
            last_cost = state["last_remaining"] - s.remaining_budget
            ticks_left = 48 - t
            if s.remaining_budget > 0:
                ratio = last_cost * ticks_left / s.remaining_budget
                if ratio < 0.7:
                    state["alpha"] *= 1.2
                elif ratio > 1.1:
                    state["alpha"] *= 0.7
        state["last_remaining"] = s.remaining_budget
        return state["alpha"]

    return replay_advertiser(df, pid_alpha, budget=budget, target_cpa=cpa, seed=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="data/official/period-7.csv")
    ap.add_argument("--advertiser", type=int, default=0)
    args = ap.parse_args()

    cols = ["advertiserNumber", "timeStepIndex", "pValue", "pValueSigma",
            "leastWinningCost", "budget", "CPAConstraint"]
    df = pd.read_csv(ROOT / args.period, usecols=cols)
    adv = df[df.advertiserNumber == args.advertiser]
    budget = float(adv.budget.iloc[0])
    cpa = float(adv.CPAConstraint.iloc[0])
    print(f"official {Path(args.period).name} adv{args.advertiser}: "
          f"budget={budget} target_cpa={cpa} pv={len(adv)}\n")

    rows = []
    for name, src in ALPHA_SOURCES.items():
        p = ROOT / src
        if not p.exists():
            continue
        r = replay_sequence(adv, alpha_seq_from_parquet(p), budget, cpa)
        rows.append((f"{name} [模拟器alpha序列回放]", r))
    for name, src in LLM_TRAJS.items():
        p = ROOT / src
        if not p.exists():
            continue
        r = replay_sequence(adv, alpha_seq_from_jsonl(p), budget, cpa)
        rows.append((f"{name} [模拟器alpha序列回放]", r))
    rows.append(("PID [官方数据原生自适应]", adaptive_pid(adv, budget, cpa)))

    rows.sort(key=lambda x: -x[1].score_expected)
    print(f"{'strategy':<36} {'score_e':>8} {'E[conv]':>8} {'cost':>9} {'cpa_e':>8} {'util':>6}")
    for name, r in rows:
        print(f"{name:<36} {r.score_expected:>8.2f} {r.conversions_expected:>8.2f} "
              f"{r.cost:>9.1f} {r.cpa_expected:>8.1f} {r.cost/budget:>6.1%}")
    print("\n注意口径:threshold replay 对手冻结、期望转化;与在线模拟分数不可直接比大小,")
    print("只看相对排序是否与自产数据结论一致。")


if __name__ == "__main__":
    main()
