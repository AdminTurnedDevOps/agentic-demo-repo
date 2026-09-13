#!/usr/bin/env python3
"""ExtMCP policy server for the GitHub Copilot MCP guardrails demo.

Implements agentgateway.dev.ext_mcp.ExtMcp:
  CheckRequest  — deny GitHub write tools and out-of-allowlist owners
  CheckResponse — strip denied tools from tools/list and mark survivors

Proto: https://github.com/agentgateway/agentgateway/blob/main/crates/protos/proto/ext_mcp.proto
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("extmcp")

# GitHub Copilot MCP write / mutation tools. Names are the un-prefixed MCP
# tool names agentgateway forwards to ExtMCP (backend name is in service_names).
DENIED_TOOLS = frozenset(
    {
        "add_comment_to_pending_review",
        "add_issue_comment",
        "assign_copilot_to_issue",
        "create_branch",
        "create_or_update_file",
        "create_pull_request",
        "create_pull_request_with_copilot",
        "create_repository",
        "delete_file",
        "fork_repository",
        "issue_write",
        "merge_pull_request",
        "pull_request_review_write",
        "push_files",
        "request_copilot_review",
        "sub_issue_write",
        "update_pull_request",
        "update_pull_request_branch",
    }
)

DESC_SUFFIX = " [guarded]"


def allowed_owners() -> set[str]:
    raw = os.environ.get("ALLOWED_OWNERS", "").strip()
    if not raw:
        return set()
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def decode_json(raw: bytes | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def tool_name(params: dict[str, Any]) -> str:
    name = params.get("name")
    return name if isinstance(name, str) else ""


def tool_arguments(params: dict[str, Any]) -> dict[str, Any]:
    args = params.get("arguments")
    return args if isinstance(args, dict) else {}


def is_denied_tool(name: str) -> bool:
    if not name:
        return False
    if name in DENIED_TOOLS:
        return True
    return name.endswith("_write")


def owner_deny_reason(arguments: dict[str, Any], owners: set[str]) -> str | None:
    if not owners:
        return None
    owner = arguments.get("owner")
    if not isinstance(owner, str) or not owner:
        return None
    if owner.lower() in owners:
        return None
    return f"owner {owner} is not in ALLOWED_OWNERS"


def request_deny_reason(method: str, params: dict[str, Any], owners: set[str]) -> str | None:
    if method != "tools/call":
        return None
    name = tool_name(params)
    if is_denied_tool(name):
        return f"tool {name} is not allowed"
    return owner_deny_reason(tool_arguments(params), owners)


def mutate_tools_list(result: dict[str, Any]) -> dict[str, Any]:
    tools = result.get("tools")
    if not isinstance(tools, list):
        return result
    filtered: list[Any] = []
    for item in tools:
        if not isinstance(item, dict):
            filtered.append(item)
            continue
        name = item.get("name")
        if isinstance(name, str) and is_denied_tool(name):
            continue
        desc = item.get("description")
        base = desc if isinstance(desc, str) else ""
        if not base.endswith(DESC_SUFFIX):
            item["description"] = base + DESC_SUFFIX
        filtered.append(item)
    result["tools"] = filtered
    return result


def ensure_stubs(workdir: str) -> None:
    pb2 = os.path.join(workdir, "ext_mcp_pb2.py")
    grpc_pb2 = os.path.join(workdir, "ext_mcp_pb2_grpc.py")
    proto = os.path.join(workdir, "ext_mcp.proto")
    if os.path.exists(pb2) and os.path.exists(grpc_pb2):
        return
    if not os.path.exists(proto):
        raise FileNotFoundError(f"missing {proto}")
    from grpc_tools import protoc

    rc = protoc.main(
        [
            "protoc",
            f"-I{workdir}",
            f"--python_out={workdir}",
            f"--grpc_python_out={workdir}",
            proto,
        ]
    )
    if rc != 0:
        raise RuntimeError(f"protoc failed with exit {rc}")


class ExtMcpServicer:
    def CheckRequest(self, request, context):  # noqa: N802
        import ext_mcp_pb2

        method = request.method
        params = decode_json(request.mcp_request)
        owners = allowed_owners()
        reason = request_deny_reason(method, params, owners)
        log.info(
            "CheckRequest method=%s services=%s tool=%s deny=%s",
            method,
            list(request.service_names),
            tool_name(params) or "-",
            reason or "no",
        )
        result = ext_mcp_pb2.McpRequestResult()
        if reason:
            result.error.code = ext_mcp_pb2.AuthorizationError.PERMISSION_DENIED
            result.error.reason = reason
            return result
        getattr(result, "pass_").CopyFrom(ext_mcp_pb2.Pass())
        return result

    def CheckResponse(self, request, context):  # noqa: N802
        import ext_mcp_pb2

        method = request.method
        log.info(
            "CheckResponse method=%s services=%s",
            method,
            list(request.service_names),
        )
        result = ext_mcp_pb2.McpResponseResult()
        if method != "tools/list":
            getattr(result, "pass_").CopyFrom(ext_mcp_pb2.Pass())
            return result
        payload = decode_json(request.mcp_response)
        if not payload:
            getattr(result, "pass_").CopyFrom(ext_mcp_pb2.Pass())
            return result
        mutated = mutate_tools_list(payload)
        result.mutated = json.dumps(mutated, separators=(",", ":")).encode()
        return result


class HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/healthz", "/ready"):
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()


def serve_health(port: int) -> None:
    httpd = HTTPServer(("0.0.0.0", port), HealthHandler)
    log.info("health listening on :%s", port)
    httpd.serve_forever()


def main() -> None:
    workdir = os.path.dirname(os.path.abspath(__file__))
    if workdir not in sys.path:
        sys.path.insert(0, workdir)
    ensure_stubs(workdir)

    from concurrent import futures

    import grpc
    import ext_mcp_pb2_grpc

    health_port = int(os.environ.get("HEALTH_PORT", "8080"))
    listen = os.environ.get("EXTMCP_LISTEN", "0.0.0.0:9001")
    threading.Thread(target=serve_health, args=(health_port,), daemon=True).start()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    ext_mcp_pb2_grpc.add_ExtMcpServicer_to_server(ExtMcpServicer(), server)
    server.add_insecure_port(listen)
    log.info(
        "extmcp listening on %s denied_tools=%s allowed_owners=%s",
        listen,
        sorted(DENIED_TOOLS),
        sorted(allowed_owners()) or "(any)",
    )
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    main()
