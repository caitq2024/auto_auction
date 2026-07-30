"""adsim CLI.

  adsim run <scenario.yaml> [--out DIR]
  adsim compare --candidates pid fixed_alpha:alpha=120 upstream:iql \
      [--pv-num N] [--episodes K] [--seed S] [--slot I] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _parse_candidate(spec: str):
    from adsim.evaluation.compare import Candidate

    if ":" in spec and "=" in spec.split(":", 1)[1]:
        strategy, kv = spec.split(":", 1)
        kwargs = {}
        for pair in kv.split(","):
            k, v = pair.split("=")
            try:
                kwargs[k] = float(v)
            except ValueError:
                kwargs[k] = v
        name = f"{strategy}_" + "_".join(f"{k}{v}" for k, v in kwargs.items())
        return Candidate(name=name, strategy=strategy, kwargs=kwargs)
    return Candidate(name=spec.replace(":", "_"), strategy=spec)


def cmd_run(args: argparse.Namespace) -> None:
    from adsim.core.runner import EpisodeRunner
    from adsim.core.scenario import ScenarioConfig
    from adsim.storage.event_writer import write_run

    scenario = ScenarioConfig.from_yaml(args.scenario)
    runner = EpisodeRunner(scenario)
    results = [runner.run_episode(ep) for ep in range(scenario.num_episode)]
    out = write_run(args.out or f"outputs/{scenario.scenario_id}", scenario, results)
    for r in results:
        for s in r.summaries:
            if s.advertiser_id in scenario.controlled_agent_ids:
                print(json.dumps({
                    "episode": s.episode, "advertiser": s.advertiser_id,
                    "strategy": s.strategy, "score": round(s.score, 6),
                    "conversions": s.conversions, "cost": round(s.cost, 2),
                    "cpa": round(s.actual_cpa, 2), "target_cpa": s.target_cpa,
                }))
    print(f"outputs -> {out}")


def cmd_compare(args: argparse.Namespace) -> None:
    from adsim.evaluation.compare import compare_strategies, summarize, to_markdown_report

    candidates = [_parse_candidate(c) for c in args.candidates]
    df = compare_strategies(
        candidates,
        controlled_slot=args.slot,
        pv_num=args.pv_num,
        num_episode=args.episodes,
        seed=args.seed,
        out_root=args.out,
    )
    summary = summarize(df)
    report = to_markdown_report(
        df, summary, "策略对比报告",
        {"pv_num": args.pv_num, "episodes": args.episodes, "seed": args.seed,
         "controlled_slot": args.slot},
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "comparison_report.md").write_text(report)
    df.to_csv(out / "comparison_detail.csv", index=False)
    print(summary.to_string(index=False))
    print(f"\nreport -> {out / 'comparison_report.md'}")


def cmd_run_matrix(args: argparse.Namespace) -> None:
    from adsim.core.experiment_spec import ExperimentSpec, run_task

    spec = ExperimentSpec.from_yaml(args.spec)
    tasks = spec.tasks()
    print(f"matrix {spec.matrix_id}: {len(tasks)} tasks")
    results = []
    for i, task in enumerate(tasks, 1):
        print(f"[{i}/{len(tasks)}] {task.task_id} ...")
        try:
            r = run_task(task)
            print(f"    score_mean={r['score_mean']}")
            results.append(r)
        except Exception as e:
            print(f"    FAILED: {type(e).__name__}: {e}")
            results.append({"task_id": task.task_id, "error": str(e)[:300]})
    out = Path(spec.output_root) / spec.matrix_id / "matrix_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"results -> {out}")


def main() -> None:
    p = argparse.ArgumentParser(prog="adsim")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run")
    pr.add_argument("scenario")
    pr.add_argument("--out", default=None)
    pr.set_defaults(fn=cmd_run)

    pc = sub.add_parser("compare")
    pc.add_argument("--candidates", nargs="+", required=True)
    pc.add_argument("--pv-num", type=int, default=20000)
    pc.add_argument("--episodes", type=int, default=4)
    pc.add_argument("--seed", type=int, default=1)
    pc.add_argument("--slot", type=int, default=0)
    pc.add_argument("--out", default="outputs/compare")
    pc.set_defaults(fn=cmd_compare)

    pm = sub.add_parser("run-matrix")
    pm.add_argument("spec")
    pm.set_defaults(fn=cmd_run_matrix)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
