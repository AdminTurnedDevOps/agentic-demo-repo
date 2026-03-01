from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any

import requests
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from openfga_client import OpenFGAClient
from policy_mapping import OBJECT_TO_TOOL, TOOL_TO_OBJECT, TOOL_TO_UPSTREAM

APP_CONFIG = os.getenv("APP_CONFIG", "/app/config.yaml")
JWT_HS256_SECRET = os.getenv("JWT_HS256_SECRET", "rebac-demo-shared-secret-please-change")
JWT_ISS = os.getenv("JWT_ISS", "rebac.demo.local")
JWT_AUD = os.getenv("JWT_AUD", "mcp-rebac-demo")

with open(APP_CONFIG, "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

OPENFGA_URL = os.getenv("OPENFGA_URL", cfg["openfga"]["url"])
OPENFGA_STORE_ID = os.getenv("OPENFGA_STORE_ID", cfg["openfga"]["store_id"])
OPENFGA_MODEL_ID = os.getenv("OPENFGA_MODEL_ID", cfg["openfga"]["model_id"])

UPSTREAMS = cfg["upstreams"]

if not OPENFGA_STORE_ID or not OPENFGA_MODEL_ID:
    raise RuntimeError("OPENFGA_STORE_ID and OPENFGA_MODEL_ID must be set")

fga = OpenFGAClient(OPENFGA_URL, OPENFGA_STORE_ID, OPENFGA_MODEL_ID)
app = FastAPI(title="rebac-auth-adapter")


def _b64url_decode(data: str) -> bytes:
    data += "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def parse_and_verify_jwt(auth_header: str | None) -> dict[str, Any]:
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")

    token = auth_header.split(" ", 1)[1]
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="invalid token format")

    h_b64, p_b64, s_b64 = parts
    unsigned = f"{h_b64}.{p_b64}".encode("utf-8")
    expected = hmac.new(JWT_HS256_SECRET.encode("utf-8"), unsigned, hashlib.sha256).digest()
    actual = _b64url_decode(s_b64)

    if not hmac.compare_digest(expected, actual):
        raise HTTPException(status_code=401, detail="invalid token signature")

    payload = json.loads(_b64url_decode(p_b64).decode("utf-8"))
    if payload.get("iss") != JWT_ISS:
        raise HTTPException(status_code=401, detail="invalid issuer")

    aud = payload.get("aud")
    if isinstance(aud, list):
        if JWT_AUD not in aud:
            raise HTTPException(status_code=401, detail="invalid audience")
    elif aud != JWT_AUD:
        raise HTTPException(status_code=401, detail="invalid audience")

    return payload


def contextual_tuples_from_claims(claims: dict[str, Any]) -> list[dict[str, str]]:
    tuples: list[dict[str, str]] = []
    sub = claims.get("sub")
    team = claims.get("team")
    if sub and team:
        tuples.append({"user": f"user:{sub}", "relation": "member", "object": f"team:{team}"})

    for project in claims.get("approver_projects", []) or []:
        tuples.append(
            {
                "user": f"user:{sub}",
                "relation": "approver",
                "object": f"project:{project}",
            }
        )
    return tuples


def upstream_call(upstream: str, payload: dict[str, Any], auth_header: str | None) -> dict[str, Any]:
    headers = {"content-type": "application/json"}
    if auth_header:
        headers["authorization"] = auth_header
    resp = requests.post(upstream, json=payload, headers=headers, timeout=5)
    resp.raise_for_status()
    return resp.json()


@app.get("/")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "rebac-auth-adapter"}


@app.post("/extauth")
async def extauth(request: Request):
    auth = request.headers.get("authorization")
    claims = parse_and_verify_jwt(auth)
    body = await request.body()

    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except json.JSONDecodeError:
        payload = {}

    method = payload.get("method")
    if method != "tools/call":
        return JSONResponse(status_code=200, content={"allow": True})

    tool_name = (payload.get("params") or {}).get("name")
    object_id = TOOL_TO_OBJECT.get(tool_name or "")
    if not object_id:
        return JSONResponse(status_code=403, content={"allow": False, "reason": "unknown_tool"})

    allowed = fga.check(
        user=f"user:{claims['sub']}",
        relation="invoke",
        obj=object_id,
        contextual=contextual_tuples_from_claims(claims),
    )
    if not allowed:
        return JSONResponse(status_code=403, content={"allow": False, "reason": "forbidden"})

    return JSONResponse(status_code=200, content={"allow": True})


@app.post("/mcp")
async def mcp_proxy(request: Request):
    auth = request.headers.get("authorization")
    claims = parse_and_verify_jwt(auth)
    payload = await request.json()
    method = payload.get("method")
    msg_id = payload.get("id")

    contextual = contextual_tuples_from_claims(claims)
    subject = f"user:{claims['sub']}"

    if method == "initialize":
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "rebac-adapter", "version": "0.1.0"},
                },
            }
        )

    if method == "tools/list":
        visible = set(fga.list_objects(subject, "discover", "tool", contextual=contextual))

        tools: list[dict[str, Any]] = []
        for name, upstream_key in TOOL_TO_UPSTREAM.items():
            obj = TOOL_TO_OBJECT[name]
            if obj not in visible:
                continue
            upstream = UPSTREAMS[upstream_key]
            resp = upstream_call(upstream, {"jsonrpc": "2.0", "id": 900, "method": "tools/list"}, auth)
            for tool in (resp.get("result") or {}).get("tools", []):
                if tool.get("name") == name:
                    tools.append(tool)

        return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools}})

    if method == "tools/call":
        params = payload.get("params") or {}
        tool_name = params.get("name")
        object_id = TOOL_TO_OBJECT.get(tool_name or "")
        if not object_id:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32602, "message": "unknown tool"},
                },
                status_code=400,
            )

        allowed = fga.check(subject, "invoke", object_id, contextual=contextual)
        if not allowed:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32001, "message": "forbidden"},
                },
                status_code=403,
            )

        upstream = UPSTREAMS[TOOL_TO_UPSTREAM[tool_name]]
        resp = upstream_call(upstream, payload, auth)
        return JSONResponse(resp)

    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": "method not found"},
        },
        status_code=404,
    )
