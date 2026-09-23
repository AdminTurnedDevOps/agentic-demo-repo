"""HTTP Strands agent for AgentCore Runtime.

AgentRegistry's chat UI posts ``{"prompt": "<user text>"}`` and reads a
string ``{"output": "<reply>"}``. This app also accepts the nested
``{"input": {"prompt": "..."}}`` shape used by curl.
"""

import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from strands import Agent
from strands.models import BedrockModel

from runtime_agent.tools import calculate, current_time

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "global.anthropic.claude-sonnet-4-6"
SYSTEM_PROMPT = (
    "You are a concise assistant running on Amazon Bedrock AgentCore. "
    "Answer the user's message directly. "
    "Call current_time when they ask for the time or date. "
    "Call calculate for arithmetic instead of doing it yourself."
)

app = FastAPI(title="AgentRegistry AgentCore Runtime Agent", version="0.1.0")

# One agent per warm microVM. AgentCore isolates each runtime session in its
# own container, so keeping messages here is per-conversation memory.
_agent: Agent | None = None


class InvocationBody(BaseModel):
    """Either the AgentRegistry prompt contract or the nested input contract."""

    prompt: str | None = None
    input: str | dict[str, Any] | None = None
    text: str | None = None


def extract_prompt(body: InvocationBody) -> str:
    """Pull user text out of the payload shapes AgentRegistry and curl send."""
    if isinstance(body.prompt, str) and body.prompt.strip():
        return body.prompt.strip()
    if isinstance(body.input, str) and body.input.strip():
        return body.input.strip()
    if isinstance(body.input, dict):
        nested = body.input.get("prompt") or body.input.get("text")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    if isinstance(body.text, str) and body.text.strip():
        return body.text.strip()
    return ""


def reply_text(message: Any) -> str:
    """Flatten a Strands message into the string AgentRegistry displays."""
    if isinstance(message, str):
        return message
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
            if isinstance(text, str) and text:
                parts.append(text)
        if parts:
            return "\n".join(parts)
    return str(message)


def build_agent() -> Agent:
    model_id = os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    model = BedrockModel(model_id=model_id, region_name=region) if region else BedrockModel(model_id=model_id)
    return Agent(
        model=model,
        tools=[current_time, calculate],
        system_prompt=SYSTEM_PROMPT,
        callback_handler=None,
    )


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


@app.get("/ping")
def ping() -> dict[str, str]:
    """Health response required by AgentCore Runtime."""
    return {"status": "Healthy"}


@app.post("/invocations")
def invoke(body: InvocationBody) -> dict[str, str]:
    """Run one conversational turn and return ``{"output": "<text>"}``."""
    prompt = extract_prompt(body)
    if not prompt:
        raise HTTPException(status_code=400, detail="provide a non-empty prompt")
    try:
        result = get_agent()(prompt)
    except Exception as error:
        logger.exception("Agent invocation failed")
        raise HTTPException(status_code=500, detail="agent invocation failed") from error
    return {"output": reply_text(result.message)}
