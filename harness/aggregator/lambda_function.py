"""H3 aggregator Lambda: matrix results on S3 -> leaderboard JSON.

Trigger: S3 ObjectCreated on matrix/*/task_result.json (also runnable
manually with {"matrix_id": "..."}).

For the touched matrix_id, lists every task_result.json under
matrix/<matrix_id>/, merges them into one ranked leaderboard document and
writes it to:
    s3://<bucket>/leaderboards/<matrix_id>.json      (per-matrix)
    s3://<bucket>/leaderboards/index.json            (list of matrices)

The frontend (or export_demo.py) consumes these directly — no EC2 involved.
Pure stdlib, no layers needed.
"""
from __future__ import annotations

import json
import os
import urllib.parse
from datetime import datetime, timezone

import boto3

BUCKET = os.environ.get("RESULTS_BUCKET", "adsim-experiments-651433607849")
s3 = boto3.client("s3")


def _aggregate(matrix_id: str) -> dict:
    prefix = f"matrix/{matrix_id}/"
    paginator = s3.get_paginator("list_objects_v2")
    candidates = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            if not obj["Key"].endswith("/task_result.json"):
                continue
            body = json.loads(
                s3.get_object(Bucket=BUCKET, Key=obj["Key"])["Body"].read())
            eps = body.get("episodes", [])
            n = max(len(eps), 1)
            candidates.append({
                "task_id": body.get("task_id"),
                "score_mean": body.get("score_mean"),
                "conversions_mean": round(sum(e["conversions"] for e in eps) / n, 2),
                "actual_cpa_mean": round(sum(e["actual_cpa"] for e in eps) / n, 2),
                "budget_utilization_mean": round(
                    sum(e["budget_utilization"] for e in eps) / n, 4),
                "episodes": eps,
                "s3_prefix": f"s3://{BUCKET}/{obj['Key'].rsplit('/', 1)[0]}",
            })
    candidates.sort(key=lambda c: -(c["score_mean"] or 0))
    return {
        "matrix_id": matrix_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "num_candidates": len(candidates),
        "candidates": candidates,
    }


def _update_index(matrix_id: str) -> None:
    key = "leaderboards/index.json"
    try:
        idx = json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    except Exception:
        idx = {"matrices": []}
    if matrix_id not in idx["matrices"]:
        idx["matrices"].append(matrix_id)
        idx["matrices"].sort()
    s3.put_object(Bucket=BUCKET, Key=key, Body=json.dumps(idx).encode(),
                  ContentType="application/json")


def handler(event, context):
    matrix_ids = set()
    if "matrix_id" in event:  # manual invoke
        matrix_ids.add(event["matrix_id"])
    for rec in event.get("Records", []):  # s3 trigger
        key = urllib.parse.unquote_plus(rec["s3"]["object"]["key"])
        parts = key.split("/")
        if len(parts) >= 3 and parts[0] == "matrix":
            matrix_ids.add(parts[1])
    results = {}
    for mid in matrix_ids:
        board = _aggregate(mid)
        out_key = f"leaderboards/{mid}.json"
        s3.put_object(Bucket=BUCKET, Key=out_key,
                      Body=json.dumps(board, ensure_ascii=False).encode(),
                      ContentType="application/json")
        _update_index(mid)
        results[mid] = {"candidates": board["num_candidates"],
                        "key": out_key}
        print(f"[aggregator] wrote s3://{BUCKET}/{out_key} "
              f"({board['num_candidates']} candidates)")
    return {"aggregated": results}
