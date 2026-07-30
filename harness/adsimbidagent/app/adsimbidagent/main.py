"""adsim bidding agent on Bedrock AgentCore Runtime (H1 PoC).

Speaks the H0 AgentEndpoint contract over AgentCore's invocation payload:
    invoke payload: {"observation": {...}, "meta": {...}}
    response:       {"action": "set_alpha", "alpha": <float>, ...}

Decision = one Bedrock converse call with the platform's v2 pacing prompt.
No conversation state is needed (the observation is self-contained), so no
session cache. Safety (clipping/fallback) stays on the simulator side —
this service only proposes an alpha.

Env: MODEL_ID (default haiku 4.5), PROMPT_TEMPLATE (v1|v2, default v2).
"""
import json
import os

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()
log = app.logger

MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
PROMPT_TEMPLATE = os.environ.get("PROMPT_TEMPLATE", "v2")
_NO_TEMPERATURE = ("opus-4-8", "opus-5", "sonnet-5", "fable-5")

_bedrock = boto3.client("bedrock-runtime",
                        region_name=os.environ.get("AWS_REGION", "us-west-2"))

PROMPT_V1 = """You are an auto-bidding agent in a repeated ad auction. \
Each decision step you receive your current state as JSON. Choose one bid \
multiplier `alpha`: your bid on every impression this step will be \
alpha * predicted_conversion_probability. Higher alpha wins more traffic but \
spends budget faster and can violate your CPA (cost-per-acquisition) target; \
score is conversions, penalized by (target_cpa/actual_cpa)^2 when \
actual_cpa > target_cpa. Budget must last all 48 steps.

Scale hint: predicted conversion probabilities are tiny (mean around \
`traffic.current_pvalue_mean`, typically 1e-4 to 1e-3) while winning market \
prices are around 0.1-1.0 per impression, so competitive alpha values are \
typically in the tens to low hundreds. Watch `market.recent_win_rate`: if it \
stays 0 your alpha is too low to win anything.

Respond with ONLY a JSON object:
{"action": "set_alpha", "alpha": <number>, "confidence": <0..1>, \
"reason_code": "<SHORT_UPPER_SNAKE_REASON>"}"""

PROMPT_V2 = PROMPT_V1.replace(
    "Respond with ONLY a JSON object:",
    """CRITICAL — unspent budget is pure loss: an episode that ends with budget \
left scored fewer conversions than it could have. The single most common \
mistake is bidding too timidly. Pacing rule of thumb: by step t you should \
have spent roughly t/48 of the initial budget; compare \
`budget.remaining_budget_ratio` with `time.tick_ratio_remaining` every step — \
if remaining_budget_ratio is HIGHER, you are behind pace: raise alpha \
decisively (x1.3-x2, not +5). Only back off when actual_cpa exceeds \
target_cpa AND you are on/ahead of pace. Ending the day with more than ~10% \
budget unspent is a failure mode, not prudence.

Respond with ONLY a JSON object:""")

SYSTEM_PROMPT = PROMPT_V2 if PROMPT_TEMPLATE == "v2" else PROMPT_V1


def _first_json_object(raw: str) -> dict:
    start = raw.find("{")
    depth, in_str, escape = 0, False, False
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
                return json.loads(raw[start:i + 1])
    raise ValueError("no balanced JSON object in model output")


@app.entrypoint
def invoke(payload, context):
    observation = payload.get("observation", {})
    prompt = f"{SYSTEM_PROMPT}\n\nCurrent state:\n{json.dumps(observation)}"
    infer = {"maxTokens": 300}
    if not any(m in MODEL_ID for m in _NO_TEMPERATURE):
        infer["temperature"] = 0.2
    resp = _bedrock.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig=infer,
    )
    text = next(b["text"] for b in resp["output"]["message"]["content"]
                if "text" in b)
    data = _first_json_object(text)
    usage = resp.get("usage", {})
    log.info("tick=%s alpha=%s in=%s out=%s",
             payload.get("meta", {}).get("tick"), data.get("alpha"),
             usage.get("inputTokens"), usage.get("outputTokens"))
    return {
        "action": "set_alpha",
        "alpha": data.get("alpha"),
        "confidence": data.get("confidence"),
        "reason_code": data.get("reason_code"),
        "model_id": MODEL_ID,
        "prompt_template": PROMPT_TEMPLATE,
        "usage": {"input_tokens": usage.get("inputTokens"),
                  "output_tokens": usage.get("outputTokens")},
    }


if __name__ == "__main__":
    app.run()
