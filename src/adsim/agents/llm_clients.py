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
        temperature: float = 0.2,
        timeout_sec: float = 30.0,
    ):
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
        resp = self._client.converse(
            modelId=self.model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={
                "maxTokens": self.max_tokens,
                "temperature": self.temperature,
            },
        )
        usage = resp.get("usage", {})
        self.total_input_tokens += usage.get("inputTokens", 0)
        self.total_output_tokens += usage.get("outputTokens", 0)
        self.calls += 1
        return resp["output"]["message"]["content"][0]["text"]
