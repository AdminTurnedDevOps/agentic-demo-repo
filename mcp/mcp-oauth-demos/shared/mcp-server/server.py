#!/usr/bin/env python3
"""
MCP Server for OAuth Security Demo using FastMCP.

This server implements 5 tools with different authorization requirements:
1. echo - Public tool, any authenticated user
2. get_user_info - Returns info about the authenticated user from JWT
3. list_files - Requires 'files:read' or 'files.read' scope
4. delete_file - Requires 'files:delete' or 'files.delete' scope AND 'admin' role
5. system_status - Requires 'admin' role

Uses Streamable HTTP transport (not deprecated SSE).
"""

import json
import os
from datetime import datetime

from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("mcp-oauth-demo")

# Simulated file system for demo
DEMO_FILES = [
    {"name": "README.md", "size": "1.2 KB", "modified": "2025-01-15"},
    {"name": "config.yaml", "size": "3.4 KB", "modified": "2025-01-14"},
    {"name": "data.json", "size": "15.7 KB", "modified": "2025-01-13"},
]


@mcp.tool()
def echo(message: str) -> str:
    """Echo back a message. This is a public tool that any authenticated user can call."""
    return f"Echo: {message}"


@mcp.tool()
def get_user_info() -> str:
    """Get information about the currently authenticated user from their JWT token."""
    user_info = {
        "message": "User info would be extracted from JWT claims passed by agentgateway",
        "note": "agentgateway can be configured to pass JWT claims as X-JWT-Claim-* headers",
        "example_claims": {
            "sub": "user-12345",
            "email": "user@example.com",
            "roles": ["user"]
        }
    }
    return json.dumps(user_info, indent=2)


@mcp.tool()
def list_files(path: str = "/") -> str:
    """List files in the system. Requires 'files:read' or 'files.read' scope."""
    result = {
        "path": path,
        "files": DEMO_FILES,
        "total": len(DEMO_FILES),
        "timestamp": datetime.utcnow().isoformat()
    }
    return json.dumps(result, indent=2)


@mcp.tool()
def delete_file(filename: str) -> str:
    """Delete a file from the system. Requires 'files:delete' or 'files.delete' scope AND 'admin' role."""
    result = {
        "status": "success",
        "message": f"File '{filename}' would be deleted (simulated)",
        "note": "This tool requires files:delete scope AND admin role",
        "timestamp": datetime.utcnow().isoformat()
    }
    return json.dumps(result, indent=2)


@mcp.tool()
def system_status() -> str:
    """Get system status information. Requires 'admin' role."""
    status = {
        "status": "healthy",
        "uptime": "2h 34m",
        "version": "1.0.0",
        "memory_usage": "45%",
        "cpu_usage": "12%",
        "timestamp": datetime.utcnow().isoformat(),
        "note": "This tool requires admin role"
    }
    return json.dumps(status, indent=2)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")

    print(f"Starting MCP OAuth Demo Server on {host}:{port}")
    print("Available endpoints:")
    print(f"  - MCP (Streamable HTTP): http://{host}:{port}/mcp")

    # Run using streamable HTTP transport
    mcp.run(transport="streamable-http", host=host, port=port)
