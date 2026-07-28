"""Batch rollout collection + SFT export (doc Phase 4, T13).

collect_rollouts: run an LLM (or any observation-driven) agent over multiple
episodes/seeds in the standard market, gathering LLMCallRecords + outcomes.

export_sft: convert teacher trajectories into chat-format JSONL
(one {"messages": [...], "meta": {...}} per decision) for SFT of a student
model. Only non-fallback decisions from episodes above a score threshold are
kept — we distill what the teacher did well, not its failure modes.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from adsim.agents.llm import LLMBidAgent
from adsim.core.runner import EpisodeRunner
from adsim.core.scenario import ScenarioConfig


def collect_rollouts(
    agent: LLMBidAgent,
    slot: int = 0,
    pv_num: int = 50000,
    episodes: int = 2,
    seed: int = 1,
    out_dir: str | Path = "outputs/rollouts",
    scenario_overrides: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Returns one record per episode: summary + full decision trajectory."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    scenario = ScenarioConfig.upstream_default_48(
        scenario_id=f"rollout_s{seed}",
        seed=seed,
        pv_num=pv_num,
        num_episode=episodes,
        controlled={slot: ("pid", {})},
        **(scenario_overrides or {}),
    )
    runner = EpisodeRunner(scenario)
    runner.agents[slot] = agent

    records = []
    for ep in range(episodes):
        res = runner.run_episode(ep)
        s = res.summaries[slot]
        rec = {
            "seed": seed,
            "episode": ep,
            "score": s.score,
            "conversions": s.conversions,
            "cost": s.cost,
            "actual_cpa": s.actual_cpa,
            "target_cpa": s.target_cpa,
            "budget_utilization": s.budget_utilization,
            "trajectory": [asdict(t) for t in agent.trajectory],
        }
        records.append(rec)
        with open(out / f"rollout_seed{seed}_ep{ep}.json", "w") as f:
            json.dump(rec, f)
    return records


def export_sft(
    rollout_files: list[str | Path],
    out_path: str | Path,
    min_score: float = 0.0,
    include_fallback: bool = False,
) -> int:
    """Rollout JSONs -> SFT chat JSONL. Returns number of examples written."""
    n = 0
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as out:
        for path in rollout_files:
            rec = json.loads(Path(path).read_text())
            if rec["score"] < min_score:
                continue
            for t in rec["trajectory"]:
                if t["fallback"] and not include_fallback:
                    continue
                if t["raw_output"] is None or t["parsed_alpha"] is None:
                    continue
                # student learns the CLEAN action JSON, not the teacher's prose
                completion = json.dumps({
                    "action": "set_alpha",
                    "alpha": t["applied_alpha"],
                })
                out.write(json.dumps({
                    "messages": [
                        {"role": "user", "content": t["prompt"]},
                        {"role": "assistant", "content": completion},
                    ],
                    "meta": {
                        "seed": rec["seed"],
                        "episode": rec["episode"],
                        "tick": t["tick"],
                        "episode_score": rec["score"],
                        "teacher_raw_alpha": t["parsed_alpha"],
                    },
                }) + "\n")
                n += 1
    return n
