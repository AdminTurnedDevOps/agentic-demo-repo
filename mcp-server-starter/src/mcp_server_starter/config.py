from __future__ import annotations

from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from typing import Literal

Transport = Literal["stdio", "http", "sse"]


@dataclass(frozen=True)
class ServerConfig:
    transport: Transport = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    path: str = "/mcp"
    log_level: str = "INFO"


def parse_args() -> ServerConfig:
    parser = ArgumentParser(description="FastMCP starter server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse"],
        default="stdio",
        help="Server transport mode (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP/SSE host")
    parser.add_argument("--port", type=int, default=8000, help="HTTP/SSE port")
    parser.add_argument("--path", default="/mcp", help="HTTP path for MCP endpoint")
    parser.add_argument("--log-level", default="INFO", help="Python logging level")
    args: Namespace = parser.parse_args()

    return ServerConfig(
        transport=args.transport,
        host=args.host,
        port=args.port,
        path=args.path,
        log_level=args.log_level.upper(),
    )
