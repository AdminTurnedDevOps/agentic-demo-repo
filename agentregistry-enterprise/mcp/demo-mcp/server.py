"""Minimal MCP server for AgentRegistry demo.

Provides a few simple tools: get current time, generate a random number,
and reverse a string. Runs over stdio.
"""

import json
import random
import sys
from datetime import datetime, timezone


def handle_request(request: dict) -> dict:
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "demo-tools", "version": "1.0.0"},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "get_time",
                        "description": "Get the current UTC time",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "random_number",
                        "description": "Generate a random number between min and max",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "min": {"type": "integer", "description": "Minimum value", "default": 1},
                                "max": {"type": "integer", "description": "Maximum value", "default": 100},
                            },
                        },
                    },
                    {
                        "name": "reverse_string",
                        "description": "Reverse a string",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string", "description": "The string to reverse"},
                            },
                            "required": ["text"],
                        },
                    },
                ]
            },
        }

    if method == "tools/call":
        tool_name = request.get("params", {}).get("name", "")
        arguments = request.get("params", {}).get("arguments", {})

        if tool_name == "get_time":
            result = datetime.now(timezone.utc).isoformat()
        elif tool_name == "random_number":
            lo = arguments.get("min", 1)
            hi = arguments.get("max", 100)
            result = str(random.randint(lo, hi))
        elif tool_name == "reverse_string":
            result = arguments.get("text", "")[::-1]
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": result}]},
        }

    if method == "notifications/initialized":
        return None  # notification, no response

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
