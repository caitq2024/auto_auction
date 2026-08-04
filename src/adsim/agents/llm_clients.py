"""Real LLM clients for LLMBidAgent (any (prompt: str) -> str callable).

BedrockClient uses boto3 with the caller's AWS credentials (IAM role).
BearerTokenClient uses a user-supplied Bedrock API key over plain HTTPS —
this is the BYO-key path for the self-serve demo (pattern borrowed from
agentic_advertising/src/adbudget/bedrock_client.py): the key lives only in
memory for the duration of the experiment, is never logged or persisted.

Newer Claude models (opus-4-8+, opus-5, sonnet-5, fable-5) reject sampling
params — both clients omit temperature for them.
"""
from __future__ import annotations

# Models offered in the self-serve demo (subset of Bedrock catalog that the
# team account has access to; per-1M-token USD prices for cost display).
SELF_SERVE_MODELS = {
    "claude-fable-5": ("global.anthropic.claude-fable-5", 10.0, 50.0),
    "claude-haiku-4-5": ("us.anthropic.claude-haiku-4-5-20251001-v1:0", 1.0, 5.0),
    "claude-sonnet-4-6": ("global.anthropic.claude-sonnet-4-6", 3.0, 15.0),
    "claude-sonnet-5": ("global.anthropic.claude-sonnet-5", 3.0, 15.0),
    "claude-opus-4-8": ("global.anthropic.claude-opus-4-8", 5.0, 25.0),
    "claude-opus-5": ("global.anthropic.claude-opus-5", 5.0, 25.0),
    "nova-2-lite": ("global.amazon.nova-2-lite-v1:0", 0.06, 0.24),
    "deepseek-r1": ("us.deepseek.r1-v1:0", 1.35, 5.4),
}

_NO_TEMPERATURE_MARKERS = ("opus-4-8", "opus-5", "sonnet-5", "fable-5")
# Reasoning models emit a reasoningContent block BEFORE the text block; a
# 300-token budget truncates mid-reasoning and no text is ever produced,
# silently driving every call to fallback. Give them room.
# opus-5 also emits reasoningContent under complex prompts (observed 2026-08-04)
_REASONING_MARKERS = ("fable-5", "deepseek", "r1-v1", "opus-5")
_REASONING_MIN_TOKENS = 2500


def _effective_max_tokens(model_id: str, requested: int) -> int:
    if any(m in model_id for m in _REASONING_MARKERS):
        return max(requested, _REASONING_MIN_TOKENS)
    return requested

def _extract_text(resp: dict) -> str:
    """First text block from a Converse response. Reasoning models (deepseek-r1,
    Claude with extended thinking) put a reasoningContent block first — never
    assume content[0] is text."""
    for block in resp.get("output", {}).get("message", {}).get("content", []):
        if "text" in block:
            return block["text"]
    raise RuntimeError("model returned no text block (reasoning-only response?)")



class BedrockClient:
    def __init__(
        self,
        model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region: str = "us-west-2",
        max_tokens: int = 300,
        temperature: float | None = 0.2,
        timeout_sec: float = 30.0,
    ):
        if any(m in model_id for m in _NO_TEMPERATURE_MARKERS):
            temperature = None
        if any(m in model_id for m in _REASONING_MARKERS):
            timeout_sec = max(timeout_sec, 120.0)  # reasoning takes 30-90s
        import boto3
        from botocore.config import Config

        self.model_id = model_id
        self.max_tokens = _effective_max_tokens(model_id, max_tokens)
        self.temperature = temperature
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(read_timeout=timeout_sec, retries={"max_attempts": 2}),
        )
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        import time as _time

        import botocore.exceptions

        inference_config = {"maxTokens": self.max_tokens}
        if self.temperature is not None:
            inference_config["temperature"] = self.temperature
        # Bedrock capacity errors (ServiceUnavailable/Throttling) are common
        # on large models; retry with exponential backoff on top of botocore's
        # built-in retries.
        last_err: Exception | None = None
        for attempt in range(5):
            try:
                resp = self._client.converse(
                    modelId=self.model_id,
                    messages=[{"role": "user", "content": [{"text": prompt}]}],
                    inferenceConfig=inference_config,
                )
                break
            except botocore.exceptions.ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                if code not in ("ServiceUnavailableException", "ThrottlingException",
                                "InternalServerException", "ModelErrorException"):
                    raise
                last_err = e
                _time.sleep(2**attempt)
            except botocore.exceptions.ReadTimeoutError as e:
                last_err = e
                _time.sleep(2**attempt)
        else:
            raise last_err  # type: ignore[misc]
        usage = resp.get("usage", {})
        self.total_input_tokens += usage.get("inputTokens", 0)
        self.total_output_tokens += usage.get("outputTokens", 0)
        self.calls += 1
        return _extract_text(resp)


class BearerTokenClient:
    """Bedrock Converse over HTTPS with a user-supplied API key.

    The key is held in memory only; it is never logged, persisted, or echoed.
    """

    def __init__(
        self,
        model_id: str,
        api_key: str,
        region: str = "us-west-2",
        max_tokens: int = 300,
        temperature: float | None = 0.2,
        timeout_sec: float = 60.0,
    ):
        self.model_id = model_id
        self._key = api_key.strip()
        self.region = region
        self.max_tokens = _effective_max_tokens(model_id, max_tokens)
        self.temperature = None if any(
            m in model_id for m in _NO_TEMPERATURE_MARKERS) else temperature
        if any(m in model_id for m in _REASONING_MARKERS):
            timeout_sec = max(timeout_sec, 120.0)
        self.timeout_sec = timeout_sec
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        import json
        import time as _time
        import urllib.error
        import urllib.parse
        import urllib.request

        infer: dict = {"maxTokens": self.max_tokens}
        if self.temperature is not None:
            infer["temperature"] = self.temperature
        body = json.dumps({
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": infer,
        }).encode()
        url = (f"https://bedrock-runtime.{self.region}.amazonaws.com/model/"
               f"{urllib.parse.quote(self.model_id, safe='')}/converse")
        last_err: Exception | None = None
        for attempt in range(4):
            req = urllib.request.Request(
                url, data=body, method="POST",
                headers={"Authorization": f"Bearer {self._key}",
                         "Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as r:
                    resp = json.loads(r.read())
                usage = resp.get("usage", {})
                self.total_input_tokens += usage.get("inputTokens", 0)
                self.total_output_tokens += usage.get("outputTokens", 0)
                self.calls += 1
                return _extract_text(resp)
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 503):
                    last_err = e
                    _time.sleep(2**attempt)
                    continue
                if e.code in (401, 403):
                    raise PermissionError(
                        "Bedrock key 无效或该账号未开通此模型的 model access"
                    ) from None  # never chain the raw error (it may echo headers)
                raise RuntimeError(f"Bedrock HTTP {e.code}") from None
        raise RuntimeError(f"Bedrock capacity error after retries: {last_err}")


class MantleGptClient:
    """GPT-5.6 (sol/terra/luna) via Bedrock Mantle Responses API.

    NOT bedrock-runtime: only https://bedrock-mantle.<region>.api.aws/openai/v1
    /responses works for these models (InvokeModel/Converse/ChatCompletions all
    fail). Auth is a long-lived Bedrock API key (env OPENAI_API_KEY or
    AWS_BEARER_TOKEN_BEDROCK). sol is us-east-1/2 only; terra/luna also us-west-2.
    """

    def __init__(
        self,
        model_id: str = "openai.gpt-5.6-terra",
        region: str | None = None,
        api_key: str | None = None,
        max_tokens: int = 2500,   # gpt-5.6 spends output budget on reasoning
        timeout_sec: float = 120.0,
    ):
        import os

        self.model_id = model_id
        if region is None:
            region = "us-east-1" if model_id.endswith("-sol") else "us-west-2"
        self.region = region
        self._key = (api_key or os.environ.get("OPENAI_API_KEY")
                     or os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")).strip()
        if not self._key:
            raise ValueError("Mantle API key missing (OPENAI_API_KEY / AWS_BEARER_TOKEN_BEDROCK)")
        self.max_tokens = max_tokens
        self.timeout_sec = timeout_sec
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        import json
        import time as _time
        import urllib.error
        import urllib.request

        body = json.dumps({"model": self.model_id, "input": prompt,
                           "max_output_tokens": self.max_tokens}).encode()
        url = f"https://bedrock-mantle.{self.region}.api.aws/openai/v1/responses"
        last_err: Exception | None = None
        for attempt in range(4):
            req = urllib.request.Request(
                url, data=body, method="POST",
                headers={"Authorization": f"Bearer {self._key}",
                         "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as r:
                    d = json.loads(r.read())
                u = d.get("usage", {})
                self.total_input_tokens += u.get("input_tokens", 0)
                self.total_output_tokens += u.get("output_tokens", 0)
                self.calls += 1
                texts = [c["text"] for o in d.get("output", [])
                         if o.get("type") == "message"
                         for c in o.get("content", []) if c.get("type") == "output_text"]
                if texts:
                    return texts[0]
                if d.get("output_text"):
                    return d["output_text"]
                raise RuntimeError("mantle response had no output_text")
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    # skill notes: transient auth failures happen — retry once
                    if attempt == 0:
                        last_err = e
                        _time.sleep(2)
                        continue
                    raise PermissionError("Mantle API key invalid/region mismatch") from None
                if e.code in (429, 500, 503):
                    last_err = e
                    _time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"Mantle HTTP {e.code}") from None
        raise RuntimeError(f"Mantle error after retries: {last_err}")
