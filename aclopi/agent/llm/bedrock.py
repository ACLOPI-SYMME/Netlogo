from __future__ import annotations

import asyncio
from typing import Any

from aclopi.agent.llm.base import LLMClient, Messages, split_system

TOOL = "decision"


class BedrockLLM(LLMClient):
    """Bedrock Converse API (boto3), forced tool call with the answer schema. boto3 is synchronous:
    it runs in a thread (no NetLogo here, so P7 does not apply)."""

    name = "bedrock"

    def __init__(self, region: str, model: str, client: Any = None) -> None:
        self.region, self.model = region, model
        if client is None:
            import boto3  # imported only when the provider is used

            client = boto3.client("bedrock-runtime", region_name=region)
        self._client = client

    async def _complete(self, messages: Messages, schema: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        system, rest = split_system(messages)
        kwargs = {
            "modelId": self.model,
            "system": [{"text": system}],
            "messages": [{"role": m["role"], "content": [{"text": m["content"]}]} for m in rest],
            "inferenceConfig": {"maxTokens": 300, "temperature": 0},
            "toolConfig": {"tools": [{"toolSpec": {"name": TOOL, "description": "Return the decision.",
                                                   "inputSchema": {"json": schema}}}],
                           "toolChoice": {"tool": {"name": TOOL}}},
        }
        response = await asyncio.to_thread(self._client.converse, **kwargs)
        for block in response["output"]["message"]["content"]:
            if "toolUse" in block:
                return dict(block["toolUse"]["input"])
        raise ValueError("no toolUse block in the answer")
