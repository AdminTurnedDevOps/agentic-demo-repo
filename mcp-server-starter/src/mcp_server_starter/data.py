from __future__ import annotations

from typing import TypedDict


class CustomerRecord(TypedDict):
    customer_id: str
    name: str
    tier: str
    email: str
    active: bool


CUSTOMERS: dict[str, CustomerRecord] = {
    "cust_1001": {
        "customer_id": "cust_1001",
        "name": "Alice Nguyen",
        "tier": "gold",
        "email": "alice@example.com",
        "active": True,
    },
    "cust_1002": {
        "customer_id": "cust_1002",
        "name": "Jordan Patel",
        "tier": "silver",
        "email": "jordan@example.com",
        "active": True,
    },
    "cust_1003": {
        "customer_id": "cust_1003",
        "name": "Riley Chen",
        "tier": "trial",
        "email": "riley@example.com",
        "active": False,
    },
}
