"""Call dealer-leads-mcp over Streamable HTTP through its Service (waypoint).

The inbound UI JWT is captured in cli.py and forwarded as Authorization so
AccessPolicy UserGroup matching at the MCP waypoint sees preferred_username.
"""

from __future__ import annotations

import json
import os
from contextvars import ContextVar
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.environ.get(
    "MCP_URL",
    "http://dealer-leads-mcp.dealeriq.svc.cluster.local:3000/mcp",
)

_authorization: ContextVar[str | None] = ContextVar("dealeriq_authorization", default=None)


def set_authorization_header(value: str | None) -> None:
    _authorization.set(value)


def _mcp_headers() -> dict[str, str]:
    auth = _authorization.get()
    if not auth:
        return {}
    return {"Authorization": auth}


def _content_to_str(result: Any) -> str:
    if result is None:
        return ""
    content = getattr(result, "content", result)
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for item in content:
            text = getattr(item, "text", None)
            if text:
                parts.append(text)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    if hasattr(result, "structuredContent") and result.structuredContent is not None:
        return json.dumps(result.structuredContent)
    return str(content)


async def call_mcp_tool(name: str, arguments: dict[str, Any] | None = None) -> str:
    args = arguments or {}
    async with streamablehttp_client(MCP_URL, headers=_mcp_headers()) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            return _content_to_str(result)
