"""DealerIQ mock CRM + inventory MCP server.

Serves MCP Streamable HTTP on /mcp so agentgateway (waypoint) can route
tool calls. Mutations stay in memory; `make seed` + pod restart restores JSON.

Do not enable postponed annotations: FastMCP 1.12.4 calls issubclass() on
raw parameter annotations and crashes if they are strings.
"""

import copy
import json
import logging
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

logging.basicConfig(level=logging.INFO, stream=__import__("sys").stderr)
log = logging.getLogger("dealer-leads-mcp")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))

mcp = FastMCP(
    "dealer-leads",
    host=os.environ.get("HOST", "0.0.0.0"),
    port=int(os.environ.get("PORT", "3000")),
    streamable_http_path="/mcp",
)


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


def _load_json(name: str) -> Any:
    path = DATA_DIR / name
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


LEADS: list[dict[str, Any]] = copy.deepcopy(_load_json("leads.json"))
INVENTORY: list[dict[str, Any]] = copy.deepcopy(_load_json("inventory.json"))
HISTORY: dict[str, Any] = copy.deepcopy(_load_json("history.json"))
OFFERS: list[dict[str, Any]] = []


def _lead(lead_id: str) -> dict[str, Any]:
    for row in LEADS:
        if str(row["id"]) == str(lead_id):
            return row
    raise ValueError(f"lead {lead_id} not found")


@mcp.tool()
def get_lead_details(lead_id: str) -> dict[str, Any]:
    """Pull an inbound CRM lead by id (web form, phone, or trade-in inquiry)."""
    return _lead(lead_id)


@mcp.tool()
def score_lead(lead_id: str) -> dict[str, Any]:
    """Qualify a lead: intent, budget fit, and timeline."""
    lead = _lead(lead_id)
    budget = int(lead.get("budget_usd") or 0)
    timeline = (lead.get("timeline") or "").lower()
    intent = "high" if "week" in timeline or "month" in timeline else "medium"
    if lead.get("status") == "lost":
        intent = "low"
    matching = [
        v
        for v in INVENTORY
        if v.get("on_lot") and int(v["price_usd"]) <= budget + 2000
    ]
    return {
        "lead_id": lead["id"],
        "name": lead["name"],
        "intent": intent,
        "budget_usd": budget,
        "timeline": lead.get("timeline"),
        "budget_fit": "strong" if matching else "weak",
        "on_lot_matches": len(matching),
        "recommended_next_step": (
            "match inventory and draft outreach"
            if intent != "low"
            else "nurture; do not discount"
        ),
    }


@mcp.tool()
def search_inventory(
    vehicle_type: str = "",
    max_price_usd: int = 0,
    lead_id: str = "",
) -> list[dict[str, Any]]:
    """Match on-lot vehicles. Optionally constrain by type, max price, or a lead's budget."""
    budget = max_price_usd
    if lead_id:
        budget = int(_lead(lead_id).get("budget_usd") or 0)
    wanted = vehicle_type.strip().lower()
    results: list[dict[str, Any]] = []
    for v in INVENTORY:
        if not v.get("on_lot"):
            continue
        if wanted and wanted not in (v.get("type") or "").lower() and wanted not in (v.get("model") or "").lower():
            continue
        if budget and int(v["price_usd"]) > budget:
            continue
        results.append(v)
    return results


@mcp.tool()
def get_vehicle_history(stock: str = "", history_id: str = "") -> dict[str, Any]:
    """Attach vehicle history (owners, accidents, title) to a listing pitch."""
    if history_id and history_id in HISTORY:
        return HISTORY[history_id]
    for v in INVENTORY:
        if v.get("stock") == stock:
            hid = v.get("history_id")
            if hid and hid in HISTORY:
                return HISTORY[hid]
    raise ValueError(f"history not found for stock={stock} history_id={history_id}")


@mcp.tool()
def draft_followup(lead_id: str, stock: str = "") -> dict[str, Any]:
    """Compose (do not send) outreach for a lead, optionally naming a stock vehicle."""
    lead = _lead(lead_id)
    vehicle = None
    if stock:
        for v in INVENTORY:
            if v.get("stock") == stock:
                vehicle = v
                break
    body = (
        f"Hi {lead['name'].split()[0]}, thanks for reaching out about a "
        f"{lead.get('interest', 'vehicle')}. "
    )
    if vehicle:
        body += (
            f"We have a {vehicle['year']} {vehicle['make']} {vehicle['model']} "
            f"({vehicle['stock']}) on the lot at ${vehicle['price_usd']:,}. "
        )
    body += "When is a good time this week to walk through options?"
    return {
        "lead_id": lead["id"],
        "to": lead.get("email"),
        "subject": "Your vehicle search at DealerIQ Motors",
        "body": body,
        "status": "draft",
    }


@mcp.tool()
def send_customer_offer(lead_id: str, stock: str, price_usd: int, discount_usd: int = 0) -> dict[str, Any]:
    """Send a discounted customer offer. Privileged: requires manager approval."""
    lead = _lead(lead_id)
    vehicle = None
    for v in INVENTORY:
        if v.get("stock") == stock:
            vehicle = v
            break
    if vehicle is None:
        raise ValueError(f"stock {stock} not found")
    offer = {
        "offer_id": f"OFF-{len(OFFERS) + 1:04d}",
        "lead_id": lead["id"],
        "customer": lead["name"],
        "stock": stock,
        "vehicle": f"{vehicle['year']} {vehicle['make']} {vehicle['model']}",
        "list_price_usd": vehicle["price_usd"],
        "offer_price_usd": price_usd,
        "discount_usd": discount_usd,
        "status": "sent",
    }
    OFFERS.append(offer)
    lead["status"] = "offer_sent"
    log.info("offer sent %s", offer["offer_id"])
    return offer


@mcp.tool()
def update_lead_status(lead_id: str, status: str) -> dict[str, Any]:
    """Mutate CRM lead status. Privileged. Allowed: new, contacted, qualified, offer_sent, won, lost."""
    allowed = {"new", "contacted", "qualified", "offer_sent", "won", "lost"}
    if status not in allowed:
        raise ValueError(f"status must be one of {sorted(allowed)}")
    lead = _lead(lead_id)
    previous = lead.get("status")
    lead["status"] = status
    return {"lead_id": lead["id"], "previous_status": previous, "status": status}


@mcp.tool()
def export_leads() -> list[dict[str, Any]]:
    """Bulk export of CRM leads including PII. Privileged. Denied for every demo persona."""
    return copy.deepcopy(LEADS)


if __name__ == "__main__":
    log.info("starting Streamable HTTP on %s:%s/mcp", mcp.settings.host, mcp.settings.port)
    mcp.run(transport="streamable-http")
