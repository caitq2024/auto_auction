"""Fargate task entrypoint: run ONE MatrixTask, upload artifacts to S3.

Input via env (Step Functions injects these as container overrides):
    TASK_JSON      the MatrixTask as JSON (matrix_id/task_id/candidate/base/seed)
    RESULTS_BUCKET s3 bucket for artifacts (default adsim-experiments-<acct>)

Artifacts land at s3://<bucket>/matrix/<matrix_id>/<task_id>/
    episode_summary.parquet / tick_events.parquet / resolved_scenario.yaml /
    run_meta.json / trajectory_all.jsonl (LLM runs) / task_result.json

Exit code 0 on success (Step Functions relies on it via runTask.sync).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import boto3  # noqa: E402

from adsim.core.experiment_spec import MatrixTask, run_task  # noqa: E402


def _fetch_replay_data(base: dict, bucket: str) -> None:
    """Replay traffic: download the period CSVs this task needs from
    s3://<bucket>/data/official/ to the same relative local paths the
    scenario references. ~1-2 min per 3.8GB period inside the region."""
    csvs = base.get("replay_period_csvs") or []
    if not csvs:
        return
    s3 = boto3.client("s3")
    for rel in csvs:
        local = Path(rel)
        if local.exists():
            continue
        local.parent.mkdir(parents=True, exist_ok=True)
        key = rel if not rel.startswith("data/") else rel  # keys mirror repo layout
        print(f"[run_task] fetching s3://{bucket}/{key}", flush=True)
        s3.download_file(bucket, key, str(local))


def main() -> None:
    task_raw = os.environ["TASK_JSON"]
    bucket = os.environ.get(
        "RESULTS_BUCKET", "adsim-experiments-651433607849")
    t = json.loads(task_raw)
    # optional per-task env (e.g. OPENAI_API_KEY for Mantle GPT models);
    # applied before any client construction
    for k, v in (t.pop("env_extra", None) or {}).items():
        os.environ.setdefault(k, v)
    _fetch_replay_data(t.get("base", {}), bucket)
    task = MatrixTask(
        matrix_id=t["matrix_id"], task_id=t["task_id"],
        candidate=t["candidate"], base=t.get("base", {}),
        seed=t.get("seed", 1),
        output_dir=t.get("output_dir")
        or f"outputs/matrix/{t['matrix_id']}/{t['task_id']}",
    )
    print(f"[run_task] {task.matrix_id}/{task.task_id} starting", flush=True)
    result = run_task(task)
    print(f"[run_task] done: {json.dumps(result)[:300]}", flush=True)

    out_dir = Path(task.output_dir)
    (out_dir / "task_result.json").write_text(json.dumps(result, indent=2))

    s3 = boto3.client("s3")
    prefix = f"matrix/{task.matrix_id}/{task.task_id}"
    for f in out_dir.iterdir():
        if f.is_file():
            s3.upload_file(str(f), bucket, f"{prefix}/{f.name}")
            print(f"[run_task] uploaded s3://{bucket}/{prefix}/{f.name}", flush=True)

    # step functions gets the compact result on stdout + s3 pointer
    print(json.dumps({"s3_prefix": f"s3://{bucket}/{prefix}", **result}))


if __name__ == "__main__":
    main()
