import logging
import os
import time
import uuid
from functools import lru_cache
from typing import Any

import httpx
import jwt
from fastapi import FastAPI, HTTPException, Request
from jwt import PyJWKClient


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
LOGGER = logging.getLogger("llm-obo-proxy")

TENANT_ID = os.environ["TENANT_ID"]
EXPECTED_AUDIENCES = {
    item.strip()
    for item in os.getenv("EXPECTED_AUDIENCES", "").split(",")
    if item.strip()
}
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
ANTHROPIC_API_URL = os.getenv("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages")
DEFAULT_MAX_TOKENS = int(os.getenv("DEFAULT_MAX_TOKENS", "1024"))
HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "60"))

ALLOWED_ISSUERS = {
    f"https://login.microsoftonline.com/{TENANT_ID}/v2.0",
    f"https://sts.windows.net/{TENANT_ID}/",
}
JWKS_URI = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"

app = FastAPI(title="llm-obo-proxy")


@lru_cache(maxsize=1)
def jwk_client() -> PyJWKClient:
    return PyJWKClient(JWKS_URI)


@lru_cache(maxsize=1)
def anthropic_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS)


def decode_bearer_token(authorization_header: str | None) -> dict[str, Any]:
    if not authorization_header or not authorization_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")

    token = authorization_header.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="empty bearer token")

    try:
        signing_key = jwk_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={
                "require": ["aud", "exp", "iat", "iss"],
                "verify_aud": False,
                "verify_iss": False,
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail=f"invalid bearer token: {exc}") from exc

    issuer = claims.get("iss")
    audience = claims.get("aud")

    if issuer not in ALLOWED_ISSUERS:
        raise HTTPException(status_code=401, detail=f"unexpected issuer: {issuer}")

    if EXPECTED_AUDIENCES and audience not in EXPECTED_AUDIENCES:
        raise HTTPException(status_code=403, detail=f"unexpected audience: {audience}")

    return claims


def normalize_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    parts.append(str(item["text"]))
                elif item.get("content"):
                    parts.append(str(item["content"]))
            elif item is not None:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    if content is None:
        return ""
    return str(content)


def to_anthropic_payload(request_body: dict[str, Any]) -> dict[str, Any]:
    system_messages: list[str] = []
    messages: list[dict[str, Any]] = []

    for message in request_body.get("messages", []):
        role = message.get("role", "user")
        text = normalize_text(message.get("content"))
        if not text:
            continue
        if role == "system":
            system_messages.append(text)
            continue
        if role not in {"user", "assistant"}:
            role = "user"
        messages.append(
            {
                "role": role,
                "content": [{"type": "text", "text": text}],
            }
        )

    if not messages:
        raise HTTPException(status_code=400, detail="at least one non-system message is required")

    payload: dict[str, Any] = {
        "model": ANTHROPIC_MODEL,
        "messages": messages,
        "max_tokens": int(
            request_body.get("max_completion_tokens")
            or request_body.get("max_tokens")
            or DEFAULT_MAX_TOKENS
        ),
    }

    if system_messages:
        payload["system"] = "\n\n".join(system_messages)

    if request_body.get("temperature") is not None:
        payload["temperature"] = request_body["temperature"]

    return payload


def anthropic_to_openai_response(
    anthropic_response: dict[str, Any], requested_model: str
) -> dict[str, Any]:
    text_parts = []
    for part in anthropic_response.get("content", []):
        if part.get("type") == "text" and part.get("text"):
            text_parts.append(part["text"])

    output_text = "".join(text_parts)
    usage = anthropic_response.get("usage", {})
    finish_reason = anthropic_response.get("stop_reason") or "stop"
    if finish_reason == "end_turn":
        finish_reason = "stop"
    elif finish_reason == "max_tokens":
        finish_reason = "length"

    prompt_tokens = int(usage.get("input_tokens", 0))
    completion_tokens = int(usage.get("output_tokens", 0))

    return {
        "id": anthropic_response.get("id", f"chatcmpl-{uuid.uuid4().hex}"),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": requested_model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": output_text,
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> dict[str, Any]:
    claims = decode_bearer_token(request.headers.get("authorization"))
    request_body = await request.json()

    if request_body.get("stream"):
        raise HTTPException(status_code=400, detail="streaming is not supported by this proxy")

    payload = to_anthropic_payload(request_body)
    requested_model = str(request_body.get("model") or ANTHROPIC_MODEL)

    LOGGER.info(
        "validated token for oid=%s aud=%s scp=%s",
        claims.get("oid"),
        claims.get("aud"),
        claims.get("scp"),
    )

    response = await anthropic_client().post(
        ANTHROPIC_API_URL,
        headers={
            "content-type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        json=payload,
    )

    if response.status_code >= 400:
        LOGGER.error("anthropic upstream failed: %s %s", response.status_code, response.text)
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text,
        )

    return anthropic_to_openai_response(response.json(), requested_model)
