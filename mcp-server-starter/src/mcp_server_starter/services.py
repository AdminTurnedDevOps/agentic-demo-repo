from __future__ import annotations

from mcp_server_starter.data import CUSTOMERS, CustomerRecord


def ping_service() -> str:
    return "pong"


def add_numbers_service(a: int, b: int) -> int:
    return a + b


def lookup_customer_service(customer_id: str) -> CustomerRecord:
    return CUSTOMERS[customer_id]


def config_resource_service() -> dict[str, object]:
    return {
        "service": "mcp-server-starter",
        "version": "0.1.0",
        "default_transport": "stdio",
    }


def customer_resource_service(customer_id: str) -> CustomerRecord:
    return CUSTOMERS[customer_id]
