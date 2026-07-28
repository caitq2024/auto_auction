"""Event Ledger (doc §8.5): tick-level parquet + episode summary + metadata."""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from adsim.core.runner import EpisodeResult
from adsim.core.scenario import ScenarioConfig


def write_run(
    out_dir: str | Path,
    scenario: ScenarioConfig,
    results: list[EpisodeResult],
    extra_meta: dict[str, Any] | None = None,
) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    ticks = pd.DataFrame(
        [
            {**{k: v for k, v in asdict(t).items() if k != "observation"},
             "observation_json": json.dumps(t.observation) if t.observation else None}
            for r in results
            for t in r.tick_records
        ]
    )
    ticks.to_parquet(out / "tick_events.parquet", index=False)

    summary = pd.DataFrame(
        [{**asdict(s), "actual_cpa": s.actual_cpa} for r in results for s in r.summaries]
    )
    summary.to_parquet(out / "episode_summary.parquet", index=False)
    summary.to_csv(out / "episode_summary.csv", index=False)

    scenario.dump(out / "resolved_scenario.yaml")
    meta = {
        "scenario_id": scenario.scenario_id,
        "seed": scenario.seed,
        "episodes": len(results),
        "wall_time_sec": [r.wall_time_sec for r in results],
        "internal_commit": _git_rev(Path(__file__).resolve().parents[3]),
        **(extra_meta or {}),
    }
    (out / "run_meta.json").write_text(json.dumps(meta, indent=2, default=str))
    return out


def _git_rev(repo: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"
