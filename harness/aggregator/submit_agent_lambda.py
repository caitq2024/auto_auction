"""H4 arena entry: submit-your-agent Lambda.

POST (via Function URL) {"name": "...", "runtime_arn": "arn:aws:bedrock-agentcore:..."}
  or {"name": "...", "endpoint_url": "https://..."}
-> validates, builds a standard-scenario MatrixTask (arena matrix, paired
   seed), starts the adsim-matrix Step Functions execution, returns the
   execution id. Results flow through the existing pipeline (Fargate -> S3
   -> aggregator -> leaderboards/arena_v1.json).

Guardrails: name sanitized, one submission per name per hour (S3 marker),
arena scenario fixed server-side (nobody picks an easier exam).
"""
from __future__ import annotations

import json
import re
import time

import boto3

BUCKET = "adsim-experiments-651433607849"
SFN_ARN = "arn:aws:states:us-west-2:651433607849:stateMachine:adsim-matrix"
ARENA_MATRIX = "arena_v1"
ARENA_BASE = {
    "pv_num": 500000, "episodes": 2, "controlled_slot": 0,
    "traffic_type": "replay",
    "replay_period_csvs": ["data/official/period-7.csv",
                            "data/official/period-8.csv"],
}

s3 = boto3.client("s3")
sfn = boto3.client("stepfunctions")


def _bad(msg: str, code: int = 400) -> dict:
    return {"statusCode": code, "body": json.dumps({"error": msg})}


def handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _bad("invalid JSON body")

    name = re.sub(r"[^a-zA-Z0-9_-]", "", str(body.get("name", "")))[:32]
    if not name:
        return _bad("name required (alphanumeric/_/-)")

    runtime_arn = body.get("runtime_arn")
    endpoint_url = body.get("endpoint_url")
    if runtime_arn:
        if not re.fullmatch(
                r"arn:aws:bedrock-agentcore:us-west-2:\d{12}:runtime/[\w-]+",
                runtime_arn):
            return _bad("runtime_arn malformed")
        candidate = {"name": name, "strategy": "agentcore",
                     "runtime_arn": runtime_arn}
    elif endpoint_url:
        if not endpoint_url.startswith("https://"):
            return _bad("endpoint_url must be https")
        candidate = {"name": name, "strategy": "remote",
                     "endpoint_url": endpoint_url}
    else:
        return _bad("runtime_arn or endpoint_url required")

    # rate limit: one submission per name per hour
    marker = f"arena/submissions/{name}.json"
    try:
        prev = json.loads(s3.get_object(Bucket=BUCKET, Key=marker)["Body"].read())
        if time.time() - prev.get("ts", 0) < 3600:
            return _bad(f"{name} submitted recently; wait an hour", 429)
    except s3.exceptions.NoSuchKey:
        pass
    except Exception:
        pass

    task = {"matrix_id": ARENA_MATRIX, "task_id": f"{name}_s1",
            "candidate": candidate, "base": ARENA_BASE, "seed": 1}
    exec_name = f"arena-{name}-{int(time.time())}"
    r = sfn.start_execution(stateMachineArn=SFN_ARN, name=exec_name,
                            input=json.dumps({"tasks": [task]}))
    s3.put_object(Bucket=BUCKET, Key=marker,
                  Body=json.dumps({"ts": time.time(), "execution": exec_name}).encode())
    return {"statusCode": 202, "body": json.dumps({
        "accepted": True, "execution": exec_name,
        "leaderboard": f"s3://{BUCKET}/leaderboards/{ARENA_MATRIX}.json",
        "note": "标准场景：官方 period-7/8 流量 × 500k PV × 2 episodes，同 seed 配对。"
                "跑完自动进 arena 榜单（约 15-20 分钟）。"})}
