from __future__ import annotations

import pytest

from mcp_server_starter.services import (
    add_numbers_service,
    config_resource_service,
    customer_resource_service,
    lookup_customer_service,
    ping_service,
)


def test_ping_service() -> None:
    assert ping_service() == "pong"


def test_add_numbers_service() -> None:
    assert add_numbers_service(2, 3) == 5


def test_lookup_customer_service_found() -> None:
    result = lookup_customer_service("cust_1001")
    assert result["name"] == "Alice Nguyen"


def test_lookup_customer_service_missing() -> None:
    with pytest.raises(KeyError):
        lookup_customer_service("does_not_exist")


def test_static_config_resource() -> None:
    cfg = config_resource_service()
    assert cfg["service"] == "mcp-server-starter"


def test_dynamic_customer_resource() -> None:
    customer = customer_resource_service("cust_1002")
    assert customer["tier"] == "silver"
