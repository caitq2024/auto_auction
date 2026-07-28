"""Multi-strategy paired comparison (doc §12.2, §14.4, §15.5 / T11).

Each candidate strategy is dropped into the SAME controlled slot of the SAME
market (common random numbers: identical experiment seed => identical traffic,
opponents, and env randomness), across multiple episodes. Ranking uses the
NeurIPS competition score; report includes business metrics, bootstrap CIs,
and paired win-rates against the first (baseline) candidate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from adsim.core.runner import EpisodeRunner
from adsim.core.scenario import ScenarioConfig
from adsim.storage.event_writer import write_run


@dataclass
class Candidate:
    name: str
    strategy: str
    kwargs: dict[str, Any] = field(default_factory=dict)


def compare_strategies(
    candidates: list[Candidate],
    controlled_slot: int = 0,
    pv_num: int = 20000,
    num_episode: int = 4,
    seed: int = 1,
    out_root: str | Path = "outputs/compare",
    scenario_overrides: dict[str, Any] | None = None,
) -> pd.DataFrame:
    rows = []
    out_root = Path(out_root)
    for cand in candidates:
        scenario = ScenarioConfig.upstream_default_48(
            scenario_id=f"compare_{cand.name}",
            seed=seed,
            pv_num=pv_num,
            num_episode=num_episode,
            controlled={controlled_slot: (cand.strategy, cand.kwargs)},
            **(scenario_overrides or {}),
        )
        runner = EpisodeRunner(scenario)
        results = [runner.run_episode(ep) for ep in range(num_episode)]
        write_run(out_root / cand.name, scenario, results, {"candidate": cand.name})
        for r in results:
            s = r.summaries[controlled_slot]
            rows.append(
                {
                    "candidate": cand.name,
                    "episode": s.episode,
                    "score": s.score,
                    "conversions": s.conversions,
                    "expected_conversions": s.expected_conversions,
                    "cost": s.cost,
                    "actual_cpa": s.actual_cpa,
                    "target_cpa": s.target_cpa,
                    "cpa_violation": max(0.0, s.actual_cpa / s.target_cpa - 1),
                    "budget_utilization": s.budget_utilization,
                    "win_pv": s.win_pv,
                    "last_compete_tick": s.last_compete_tick,
                    "wall_time_sec": r.wall_time_sec,
                }
            )
    return pd.DataFrame(rows)


def _bootstrap_ci(x: np.ndarray, n_boot: int = 2000, seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    means = rng.choice(x, size=(n_boot, len(x)), replace=True).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def summarize(df: pd.DataFrame, baseline: str | None = None) -> pd.DataFrame:
    baseline = baseline or df["candidate"].iloc[0]
    base_scores = df[df.candidate == baseline].sort_values("episode")["score"].to_numpy()
    out = []
    for name, g in df.groupby("candidate"):
        g = g.sort_values("episode")
        scores = g["score"].to_numpy()
        lo, hi = _bootstrap_ci(scores)
        paired_wins = float((scores > base_scores).mean()) if name != baseline else np.nan
        out.append(
            {
                "candidate": name,
                "episodes": len(g),
                "score_mean": scores.mean(),
                "score_std": scores.std(),
                "score_ci95": f"[{lo:.4g}, {hi:.4g}]",
                "conversions_mean": g["conversions"].mean(),
                "expected_conversions_mean": g["expected_conversions"].mean(),
                "actual_cpa_mean": g["actual_cpa"].mean(),
                "cpa_violation_mean": g["cpa_violation"].mean(),
                "budget_utilization_mean": g["budget_utilization"].mean(),
                f"paired_win_rate_vs_{baseline}": paired_wins,
            }
        )
    return (
        pd.DataFrame(out).sort_values("score_mean", ascending=False).reset_index(drop=True)
    )


def to_markdown_report(
    df: pd.DataFrame, summary: pd.DataFrame, title: str, meta: dict[str, Any]
) -> str:
    lines = [f"# {title}", ""]
    lines.append("| " + " | ".join(f"{k}: {v}" for k, v in meta.items()) + " |")
    lines.append("")
    lines.append("同一市场、同一 seed（common random numbers）下的配对比较；"
                 "排序指标为 NeurIPS competition score。")
    lines.append("")
    lines.append("## 排名")
    lines.append("")
    lines.append(summary.to_markdown(index=False, floatfmt=".4g"))
    lines.append("")
    lines.append("## 明细（per episode）")
    lines.append("")
    lines.append(
        df.sort_values(["candidate", "episode"]).to_markdown(index=False, floatfmt=".4g")
    )
    lines.append("")
    lines.append("> 所有数字为 simulated 结果，未经客户数据校准，不代表真实平台收益。")
    return "\n".join(lines)
