"""H1 PoC: the bidding agent as a Bedrock AgentCore Runtime service.

Speaks the H0 AgentEndpoint contract:
    POST /invocations   {"observation": {...}, "meta": {...}}
    ->                  {"action": "set_alpha", "alpha": <float>, ...}

AgentCore Runtime hosts exactly this HTTP shape (its service contract is
POST /invocations + GET /ping), so the SAME file runs:
- locally:            uvicorn bidding_agent:app --port 9000
- on AgentCore:       agentcore launch  (containerized by the toolkit)

The simulator connects through RemoteAgent(endpoint) either way — that's
the point of H0: swapping local/AgentCore is a URL change, zero simulator
diff. Safety (clipping/fallback) stays simulator-side; this service only
proposes an alpha.

Env:
    MODEL_ID          bedrock model (default haiku 4.5)
    PROMPT_TEMPLATE   v1|v2 (default v2)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from adsim.agents.llm import PROMPT_TEMPLATES  # noqa: E402
from adsim.agents.llm_clients import BedrockClient  # noqa: E402

MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
TEMPLATE = os.environ.get("PROMPT_TEMPLATE", "v2")

app = FastAPI(title="adsim-bidding-agent", version="0.1.0")
_client = BedrockClient(model_id=MODEL_ID)
_system_prompt = PROMPT_TEMPLATES[TEMPLATE]["text"]


class Invocation(BaseModel):
    observation: dict
    meta: dict = {}


@app.get("/ping")
def ping():
    return {"status": "healthy"}


@app.post("/invocations")
def invoke(inv: Invocation):
    prompt = f"{_system_prompt}\n\nCurrent state:\n{json.dumps(inv.observation)}"
    raw = _client(prompt)
    # extract first balanced JSON object (same rule as LLMBidAgent)
    start = raw.find("{")
    depth, end = 0, -1
    in_str = escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    data = json.loads(raw[start:end])
    return {
        "action": "set_alpha",
        "alpha": data.get("alpha"),
        "confidence": data.get("confidence"),
        "reason_code": data.get("reason_code"),
        "model_id": MODEL_ID,
        "prompt_template": TEMPLATE,
        "usage": {"input_tokens": _client.total_input_tokens,
                  "output_tokens": _client.total_output_tokens,
                  "calls": _client.calls},
    }
