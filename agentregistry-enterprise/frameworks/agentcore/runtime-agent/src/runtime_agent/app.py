"""HTTP Strands agent for AgentCore Runtime.

AgentRegistry chat sends the user text as a plain-text body. Curl and the
harness path send JSON ``{"prompt": "<user text>"}``. Both are accepted.

The reply is plain text. A JSON object body is shown in the chat UI as a
tool card ("Unknown Source") because the UI treats JSON objects as data parts.
"""

import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ValidationError
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


def prompt_from_body(raw: bytes) -> str:
    """Read a prompt from JSON or from the plain text AgentRegistry chat sends.

    Non-harness HTTP agents receive the A2A text part unchanged, with
    content type text/plain. Declaring a JSON body model turns that into
    FastAPI's 422, which AgentCore surfaces as a 424.
    """
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    try:
        body = InvocationBody.model_validate_json(text)
    except (ValidationError, ValueError):
        return text
    return extract_prompt(body)


def extract_prompt(body: InvocationBody) -> str:
    """Pull user text out of the JSON payload shapes."""
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


def run_prompt(prompt: str) -> str:
    """Run one conversational turn and return the reply text."""
    if not prompt:
        raise HTTPException(status_code=400, detail="provide a non-empty prompt")
    try:
        result = get_agent()(prompt)
    except Exception as error:
        logger.exception("Agent invocation failed")
        raise HTTPException(status_code=500, detail="agent invocation failed") from error
    return reply_text(result.message)


@app.post("/invocations", response_class=PlainTextResponse)
async def invoke(request: Request) -> PlainTextResponse:
    """Accept plain text or a JSON prompt envelope and answer in plain text."""
    return PlainTextResponse(run_prompt(prompt_from_body(await request.body())))
