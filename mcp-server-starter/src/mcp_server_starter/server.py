from __future__ import annotations

import logging

from fastmcp import FastMCP
from fastmcp.exceptions import ResourceError, ToolError

from mcp_server_starter.config import parse_args
from mcp_server_starter.logging_config import configure_logging
from mcp_server_starter.services import (
    add_numbers_service,
    config_resource_service,
    customer_resource_service,
    lookup_customer_service,
    ping_service,
)

logger = logging.getLogger(__name__)

mcp = FastMCP("mcp-server-starter", mask_error_details=True)


@mcp.tool
def ping() -> str:
    """Simple liveness check."""
    return ping_service()


@mcp.tool
def add_numbers(a: int, b: int) -> int:
    """Add two integers."""
    return add_numbers_service(a, b)


@mcp.tool
def lookup_customer(customer_id: str) -> dict:
    """Look up a customer by customer_id."""
    try:
        customer = lookup_customer_service(customer_id)
    except KeyError as exc:
        logger.warning("Customer not found: %s", customer_id)
        raise ToolError(f"Customer '{customer_id}' was not found.") from exc
    return dict(customer)


@mcp.resource("resource://config")
def config_resource() -> dict:
    """Static server config resource."""
    return config_resource_service()


@mcp.resource("customers://{customer_id}")
def customer_resource(customer_id: str) -> dict:
    """Dynamic customer resource template."""
    try:
        customer = customer_resource_service(customer_id)
    except KeyError as exc:
        logger.warning("Customer resource not found: %s", customer_id)
        raise ResourceError(f"Customer resource '{customer_id}' was not found.") from exc
    return dict(customer)


def main() -> None:
    cfg = parse_args()
    configure_logging(level=cfg.log_level)

    logger.info("Starting server with transport=%s", cfg.transport)

    if cfg.transport == "stdio":
        mcp.run(transport="stdio", show_banner=False)
        return

    if cfg.transport == "http":
        mcp.run(
            transport="http",
            host=cfg.host,
            port=cfg.port,
            path=cfg.path,
            show_banner=False,
        )
        return

    mcp.run(
        transport="sse",
        host=cfg.host,
        port=cfg.port,
        show_banner=False,
    )


if __name__ == "__main__":
    main()
