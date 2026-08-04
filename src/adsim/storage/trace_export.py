"""H4: export decision traces to CloudWatch (EMF metrics + structured logs).

Design choice: we emit CloudWatch **EMF** (Embedded Metric Format) lines to a
log group. One putLogEvents call per episode gives us:
- structured per-decision records (searchable in Logs Insights, joins the
  AgentCore Runtime's own logs in the same console)
- auto-extracted metrics (latency/fallback/alpha) under namespace `adsim`,
  no separate PutMetricData calls

This complements — not replaces — the JSONL trajectory on S3 (source of
truth for SFT/replay). trace_id/span_id fields (H0) tie the three views
together: S3 JSONL <-> CloudWatch EMF <-> AgentCore Runtime logs.
"""
from __future__ import annotations

import json
import time

import boto3

LOG_GROUP = "/adsim/decisions"
NAMESPACE = "adsim"


def export_episode_trace(
    records: list,  # list[LLMCallRecord]
    *,
    matrix_id: str,
    task_id: str,
    episode: int,
    model_id: str,
    region: str = "us-west-2",
) -> int:
    """Ship one episode's decision records as EMF log events. Returns count."""
    logs = boto3.client("logs", region_name=region)
    try:
        logs.create_log_group(logGroupName=LOG_GROUP)
    except Exception:
        pass  # exists
    stream = f"{matrix_id}/{task_id}/ep{episode}"
    try:
        logs.create_log_stream(logGroupName=LOG_GROUP, logStreamName=stream)
    except Exception:
        pass

    now_ms = int(time.time() * 1000)
    events = []
    for r in records:
        emf = {
            "_aws": {
                "Timestamp": now_ms,
                "CloudWatchMetrics": [{
                    "Namespace": NAMESPACE,
                    "Dimensions": [["matrix_id", "model_id"]],
                    "Metrics": [
                        {"Name": "decision_latency_sec", "Unit": "Seconds"},
                        {"Name": "fallback", "Unit": "Count"},
                        {"Name": "applied_alpha", "Unit": "None"},
                    ],
                }],
            },
            "matrix_id": matrix_id,
            "model_id": model_id,
            "task_id": task_id,
            "episode": episode,
            "tick": r.tick,
            "decision_latency_sec": r.latency_sec,
            "fallback": 1 if r.fallback else 0,
            "fallback_kind": r.fallback,
            "applied_alpha": r.applied_alpha,
            "parsed_alpha": r.parsed_alpha,
            "error": r.error,
            "trace_id": r.trace_id,
            "span_id": r.span_id,
        }
        events.append({"timestamp": now_ms, "message": json.dumps(emf)})
    if events:
        logs.put_log_events(logGroupName=LOG_GROUP, logStreamName=stream,
                            logEvents=events)
    return len(events)
