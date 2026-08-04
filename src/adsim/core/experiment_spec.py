"""H0: ExperimentSpec — one YAML defines a full experiment matrix.

The same spec runs anywhere: `adsim run-matrix spec.yaml` executes serially
on this machine; the Step Functions executor (H2) fans the identical task
list out to Fargate. Executor changes, spec doesn't.

Example spec:

    matrix_id: teacher_selection_v1
    base:
      pv_num: 500000
      episodes: 2
      seed: 1
      controlled_slot: 0
      traffic_type: parametric        # or replay
      # replay_period_csvs: [data/official/period-7.csv]
    candidates:
      - name: pid
        strategy: pid
      - name: haiku_v2
        strategy: llm
        model_id: us.anthropic.claude-haiku-4-5-20251001-v1:0
        prompt_template: v2
        max_alpha: 2000
    output_root: outputs/matrix
"""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class MatrixTask:
    """One executable unit: a candidate x seed combination."""

    matrix_id: str
    task_id: str
    candidate: dict[str, Any]
    base: dict[str, Any]
    seed: int
    output_dir: str


@dataclass
class ExperimentSpec:
    matrix_id: str
    base: dict[str, Any]
    candidates: list[dict[str, Any]]
    seeds: list[int] = field(default_factory=lambda: [1])
    output_root: str = "outputs/matrix"

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ExperimentSpec":
        raw = yaml.safe_load(Path(path).read_text())
        seeds = raw.get("seeds") or [raw.get("base", {}).get("seed", 1)]
        return cls(matrix_id=raw["matrix_id"], base=raw.get("base", {}),
                   candidates=raw["candidates"], seeds=seeds,
                   output_root=raw.get("output_root", "outputs/matrix"))

    def tasks(self) -> list[MatrixTask]:
        out = []
        for cand, seed in itertools.product(self.candidates, self.seeds):
            tid = f"{cand['name']}_s{seed}"
            out.append(MatrixTask(
                matrix_id=self.matrix_id, task_id=tid, candidate=cand,
                base=self.base, seed=seed,
                output_dir=f"{self.output_root}/{self.matrix_id}/{tid}"))
        return out


def run_task(task: MatrixTask) -> dict[str, Any]:
    """Execute one matrix task locally. Returns the controlled-slot summary."""
    from adsim.core.runner import EpisodeRunner
    from adsim.core.scenario import ScenarioConfig
    from adsim.storage.event_writer import write_run

    base, cand = task.base, task.candidate
    slot = base.get("controlled_slot", 0)
    strategy = cand["strategy"]

    if strategy == "llm":
        controlled = {slot: ("pid", {})}  # placeholder, agent injected below
    else:
        controlled = {slot: (strategy, cand.get("kwargs", {}))}

    scenario = ScenarioConfig.upstream_default_48(
        scenario_id=f"{task.matrix_id}_{task.task_id}",
        seed=task.seed,
        pv_num=base.get("pv_num", 500000),
        num_episode=base.get("episodes", 1),
        traffic_type=base.get("traffic_type", "parametric"),
        controlled=controlled,
    )
    if base.get("replay_period_csvs"):
        scenario.extra["replay_period_csvs"] = base["replay_period_csvs"]

    runner = EpisodeRunner(scenario)

    agent = None
    if strategy == "llm":
        from adsim.agents.llm import (LLMAgentConfig, LLMBidAgent,
                                      PROMPT_TEMPLATES)
        from adsim.agents.llm_clients import BedrockClient, MantleGptClient

        if cand["model_id"].startswith("openai."):
            client = MantleGptClient(model_id=cand["model_id"])
        else:
            client = BedrockClient(model_id=cand["model_id"])
        tmpl = cand.get("prompt_template")
        agent = LLMBidAgent(
            client,
            LLMAgentConfig(max_alpha=cand.get("max_alpha", 2000.0)),
            system_prompt=PROMPT_TEMPLATES[tmpl]["text"] if tmpl else None,
            prompt_version=tmpl or "default",
        )
        runner.agents[slot] = agent
        scenario.advertisers[slot].strategy = f"llm:{cand['model_id']}"
    elif strategy == "remote":
        from adsim.agents.remote import RemoteAgent

        agent = RemoteAgent(cand["endpoint_url"],
                            headers=cand.get("headers", {}))
        runner.agents[slot] = agent
        scenario.advertisers[slot].strategy = f"remote:{cand['endpoint_url']}"
    elif strategy == "agentcore":
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "harness" / "agentcore"))
        from poc_run_agentcore import AgentCoreAgent

        agent = AgentCoreAgent(cand["runtime_arn"])
        runner.agents[slot] = agent
        scenario.advertisers[slot].strategy = f"agentcore:{cand['runtime_arn'].split('/')[-1]}"

    results = []
    all_records = []
    for ep in range(scenario.num_episode):
        results.append(runner.run_episode(ep))
        if agent is not None and hasattr(agent, "trajectory"):
            all_records.append((ep, list(agent.trajectory)))
    out_dir = Path(task.output_dir)
    write_run(out_dir, scenario, results, {"matrix_task": task.task_id})
    if agent is not None and hasattr(agent, "trajectory"):
        from dataclasses import asdict
        with open(out_dir / "trajectory_all.jsonl", "w") as f:
            for ep, recs in all_records:
                for t in recs:
                    f.write(json.dumps(asdict(t)) + "\n")
        # H4: ship per-decision EMF traces to CloudWatch (best-effort)
        try:
            from adsim.storage.trace_export import export_episode_trace

            for ep, recs in all_records:
                export_episode_trace(
                    recs, matrix_id=task.matrix_id, task_id=task.task_id,
                    episode=ep, model_id=cand.get("model_id", strategy))
        except Exception as e:
            print(f"[trace_export] skipped: {type(e).__name__}: {e}")

    summaries = [r.summaries[slot] for r in results]
    scores = [s.score for s in summaries]
    return {
        "task_id": task.task_id,
        "score_mean": round(sum(scores) / len(scores), 4),
        "episodes": [{"episode": s.episode, "score": round(s.score, 4),
                      "conversions": s.conversions, "cost": round(s.cost, 2),
                      "actual_cpa": round(s.actual_cpa, 2),
                      "budget_utilization": round(s.budget_utilization, 4)}
                     for s in summaries],
        "output_dir": task.output_dir,
    }
