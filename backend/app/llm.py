"""Thin wrapper over Bedrock: structured JSON calls via forced tool use, and Titan embeddings."""
import json
import logging
import random
import time
from dataclasses import dataclass

from botocore.exceptions import ClientError

from .aws import bedrock
from .config import settings

log = logging.getLogger("lectern.llm")

RETRYABLE = {"ThrottlingException", "ServiceUnavailableException", "ModelNotReadyException", "InternalServerException"}


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0

    def add(self, other: "Usage") -> None:
        self.tokens_in += other.tokens_in
        self.tokens_out += other.tokens_out


class LLMError(RuntimeError):
    pass


def _with_retries(fn, attempts: int = 6):
    for i in range(attempts):
        try:
            return fn()
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code not in RETRYABLE or i == attempts - 1:
                raise
            delay = min(30, 2 ** i) + random.random()
            log.warning("bedrock %s, retrying in %.1fs", code, delay)
            time.sleep(delay)


def call_json(
    *,
    system: str,
    prompt: str,
    schema: dict,
    tool_name: str,
    max_tokens: int = 4000,
    temperature: float = 0.3,
    background: bool = False,
) -> tuple[dict, Usage]:
    """Ask the model to answer by calling a single tool whose input matches `schema`."""
    request = dict(
        modelId=settings.text_model,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
        toolConfig={
            "tools": [{"toolSpec": {"name": tool_name, "description": f"Return the {tool_name} result.",
                                    "inputSchema": {"json": schema}}}],
            "toolChoice": {"tool": {"name": tool_name}},
        },
    )
    if background and settings.build_service_tier:
        request["serviceTier"] = {"type": settings.build_service_tier}

    def run():
        try:
            return bedrock().converse(**request)
        except ClientError as e:
            # Fall back to the default tier if flex isn't available for this model/region.
            if "serviceTier" in request and e.response["Error"]["Code"] == "ValidationException":
                log.warning("flex tier rejected (%s); using default tier", e.response["Error"]["Message"])
                request.pop("serviceTier")
                return bedrock().converse(**request)
            raise

    resp = _with_retries(run)
    usage = Usage(resp["usage"]["inputTokens"], resp["usage"]["outputTokens"])
    for block in resp["output"]["message"]["content"]:
        if "toolUse" in block:
            data = block["toolUse"]["input"]
            if isinstance(data, str):
                data = json.loads(data)
            return data, usage
    text = " ".join(b.get("text", "") for b in resp["output"]["message"]["content"])
    raise LLMError(f"model did not return structured output (stop={resp.get('stopReason')}): {text[:300]}")


def embed(text: str) -> list[float]:
    body = json.dumps({"inputText": text[:30000], "dimensions": 1024, "normalize": True})

    def run():
        return bedrock().invoke_model(modelId=settings.embed_model, body=body,
                                      contentType="application/json", accept="application/json")

    resp = _with_retries(run)
    return json.loads(resp["body"].read())["embedding"]
