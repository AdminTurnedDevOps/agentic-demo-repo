#!/usr/bin/env python3
"""
This server implements 5 tools with different authorization requirements:
1. echo - Public tool, any authenticated user
2. get_user_info - Returns info about the authenticated user from JWT
3. list_files - Requires 'files:read' or 'files.read' scope
4. delete_file - Requires 'files:delete' or 'files.delete' scope AND 'admin' role
5. system_status - Requires 'admin' role

The server expects agentgateway to handle JWT validation and pass user info
via headers or request context.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

from mcp.server import Server
from mcp.server.streamable_http import StreamableHTTPServerTransport
from mcp.types import (
    Tool,
    TextContent,
    CallToolRequest,
    CallToolResult,
)
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import Response

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize MCP server
mcp_server = Server("mcp-oauth-demo")

# Simulated file system for demo
DEMO_FILES = [
    {"name": "README.md", "size": "1.2 KB", "modified": "2025-01-15"},
    {"name": "config.yaml", "size": "3.4 KB", "modified": "2025-01-14"},
    {"name": "data.json", "size": "15.7 KB", "modified": "2025-01-13"},
]


def extract_user_from_headers(headers: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    Extract user information from headers set by agentgateway.

    agentgateway can be configured to pass JWT claims as headers.
    Common headers:
    - X-JWT-Claim-Sub: Subject (user ID)
    - X-JWT-Claim-Email: User email
    - X-JWT-Claim-Preferred-Username: Username
    - X-Forwarded-User: User identifier
    """
    user_info = {}

    # Try to extract common user identifiers
    if "x-jwt-claim-sub" in headers:
        user_info["sub"] = headers["x-jwt-claim-sub"]
    if "x-jwt-claim-email" in headers:
        user_info["email"] = headers["x-jwt-claim-email"]
    if "x-jwt-claim-preferred-username" in headers:
        user_info["preferred_username"] = headers["x-jwt-claim-preferred-username"]
    if "x-forwarded-user" in headers:
        user_info["user"] = headers["x-forwarded-user"]
    if "authorization" in headers:
        user_info["has_token"] = True

    logger.info(f"Request headers: {headers}")

    return user_info if user_info else None


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available MCP tools with their schemas."""
    return [
        Tool(
            name="echo",
            description="Echo back a message. This is a public tool that any authenticated user can call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message to echo back"
                    }
                },
                "required": ["message"]
            }
        ),
        Tool(
            name="get_user_info",
            description="Get information about the currently authenticated user from their JWT token.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="list_files",
            description="List files in the system. Requires 'files:read' or 'files.read' scope.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Optional path to list files from",
                        "default": "/"
                    }
                }
            }
        ),
        Tool(
            name="delete_file",
            description="Delete a file from the system. Requires 'files:delete' or 'files.delete' scope AND 'admin' role.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Name of the file to delete"
                    }
                },
                "required": ["filename"]
            }
        ),
        Tool(
            name="system_status",
            description="Get system status information. Requires 'admin' role.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls with the provided arguments."""
    logger.info(f"Tool called: {name} with arguments: {arguments}")

    # Note: JWT validation and authorization is handled by agentgateway
    # If this code runs, the request was already authorized
    # We can still access user info from headers if agentgateway is configured to pass them

    if name == "echo":
        message = arguments.get("message", "")
        return [
            TextContent(
                type="text",
                text=f"Echo: {message}"
            )
        ]

    elif name == "get_user_info":
        user_info = {
            "message": "User info would be extracted from JWT claims passed by agentgateway",
            "note": "agentgateway can be configured to pass JWT claims as X-JWT-Claim-* headers",
            "example_claims": {
                "sub": "user-12345",
                "email": "user@example.com",
                "roles": ["user"]
            }
        }
        return [
            TextContent(
                type="text",
                text=json.dumps(user_info, indent=2)
            )
        ]

    elif name == "list_files":
        path = arguments.get("path", "/")
        result = {
            "path": path,
            "files": DEMO_FILES,
            "total": len(DEMO_FILES),
            "timestamp": datetime.utcnow().isoformat()
        }
        return [
            TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )
        ]

    elif name == "delete_file":
        filename = arguments.get("filename", "")
        result = {
            "status": "success",
            "message": f"File '{filename}' would be deleted (simulated)",
            "note": "This tool requires files:delete scope AND admin role",
            "timestamp": datetime.utcnow().isoformat()
        }
        return [
            TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )
        ]

    elif name == "system_status":
        status = {
            "status": "healthy",
            "uptime": "2h 34m",
            "version": "1.0.0",
            "memory_usage": "45%",
            "cpu_usage": "12%",
            "timestamp": datetime.utcnow().isoformat(),
            "note": "This tool requires admin role"
        }
        return [
            TextContent(
                type="text",
                text=json.dumps(status, indent=2)
            )
        ]

    else:
        raise ValueError(f"Unknown tool: {name}")


transport = StreamableHTTPServerTransport()


async def health_check(request: Request):
    """Health check endpoint for Kubernetes probes."""
    return Response(
        content=json.dumps({
            "status": "healthy",
            "service": "mcp-oauth-demo",
            "timestamp": datetime.utcnow().isoformat()
        }),
        media_type="application/json"
    )


app = Starlette(
    debug=True,
    routes=[
        Mount("/mcp", app=transport.get_asgi_app(mcp_server)),
        Route("/health", endpoint=health_check),
    ]
)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")

    logger.info(f"Starting MCP OAuth Demo Server on {host}:{port}")
    logger.info("Available endpoints:")
    logger.info(f"  - MCP (Streamable HTTP): http://{host}:{port}/mcp")
    logger.info(f"  - Health: http://{host}:{port}/health")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )
