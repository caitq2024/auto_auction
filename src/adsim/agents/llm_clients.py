"""Real LLM clients for LLMBidAgent (any (prompt: str) -> str callable).

BedrockClient uses the AWS Bedrock Converse API. Model choice guidance:
- claude-haiku-4-5: cheap/fast, fine for pipeline validation
- claude-sonnet-5 / claude-opus-5: teacher-quality decisions (doc §11.4)
"""
from __future__ import annotations


class BedrockClient:
    def __init__(
        self,
        model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region: str = "us-west-2",
        max_tokens: int = 300,
        temperature: float | None = 0.2,
        timeout_sec: float = 30.0,
    ):
        # Newer Claude models (opus-4-8+) reject the temperature param.
        if any(m in model_id for m in ("opus-4-8", "opus-5", "sonnet-5", "fable-5")):
            temperature = None
        import boto3
        from botocore.config import Config

        self.model_id = model_id
        self.max_tokens = max_tokens
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
                if code not in ("ServiceUnavailableException", "ThrottlingException"):
                    raise
                last_err = e
                _time.sleep(2**attempt)
        else:
            raise last_err  # type: ignore[misc]
        usage = resp.get("usage", {})
        self.total_input_tokens += usage.get("inputTokens", 0)
        self.total_output_tokens += usage.get("outputTokens", 0)
        self.calls += 1
        return resp["output"]["message"]["content"][0]["text"]
