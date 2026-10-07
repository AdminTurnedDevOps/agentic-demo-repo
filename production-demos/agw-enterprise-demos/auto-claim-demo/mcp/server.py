"""Auto-claims MCP server for the "Is the agent allowed?" demo.

Exposes Streamable HTTP on /mcp. The server deliberately ships more tools than
the gateway approves: issue_payment and export_member_records exist here but are
not in the agentgateway tool registry policy, so agents never see or reach them.

Writes stay in memory. Restart the pod to reset (make demo-reset does this).

Do not enable postponed annotations: FastMCP 1.12.4 calls issubclass() on raw
parameter annotations and crashes if they are strings.
"""

import copy
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
log = logging.getLogger("claims-mcp")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))

mcp = FastMCP(
    "auto-claims",
    host=os.environ.get("HOST", "0.0.0.0"),
    port=int(os.environ.get("PORT", "3000")),
    streamable_http_path="/mcp",
)


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


def _load(name: str) -> Any:
    with (DATA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


MEMBERS: list[dict[str, Any]] = copy.deepcopy(_load("members.json"))
SUBMISSIONS: list[dict[str, Any]] = copy.deepcopy(_load("submissions.json"))
CLAIMS: list[dict[str, Any]] = []


def _member(member_id: str) -> dict[str, Any]:
    for row in MEMBERS:
        if row["member_id"] == member_id:
            return row
    raise ValueError(f"member {member_id} not found")


def _submission(submission_id: str) -> dict[str, Any]:
    for row in SUBMISSIONS:
        if row["submission_id"] == submission_id:
            return row
    raise ValueError(f"submission {submission_id} not found")


# --- Approved read tools -----------------------------------------------------


@mcp.tool()
def get_member_policy(member_id: str) -> dict[str, Any]:
    """Read a member's auto policy, covered vehicle, and contact details."""
    return _member(member_id)


@mcp.tool()
def check_coverage_rules(member_id: str, incident_type: str) -> dict[str, Any]:
    """Check whether an incident type is covered and what deductible applies."""
    policy = _member(member_id)["policy"]
    coverage = policy["coverages"].get(incident_type)
    if policy["status"] != "active":
        return {"covered": False, "reason": f"policy status is {policy['status']}"}
    if not coverage or not coverage.get("included"):
        return {"covered": False, "reason": f"{incident_type} coverage is not on this policy"}
    rental = policy["coverages"].get("rental_reimbursement", {})
    return {
        "covered": True,
        "incident_type": incident_type,
        "deductible_usd": coverage.get("deductible_usd"),
        "rental_reimbursement": rental if rental.get("included") else None,
        "rules": [
            "Claims over 10000 USD need a field adjuster inspection.",
            "Opening a claim is a write action and requires the adjuster permission tier.",
        ],
    }


@mcp.tool()
def assess_photos(submission_id: str) -> dict[str, Any]:
    """Return the damage assessment for a claim submission's photos and uploaded documents."""
    sub = _submission(submission_id)
    return {
        "submission_id": sub["submission_id"],
        "member_id": sub["member_id"],
        "incident_type": sub["incident_type"],
        "incident_date": sub["incident_date"],
        "description": sub["description"],
        "photos": sub["photos"],
        "documents": sub["documents"],
        "estimated_repair_usd": sub["estimated_repair_usd"],
    }


@mcp.tool()
def draft_member_reply(member_id: str, claim_number: str, key_points: str) -> dict[str, Any]:
    """Draft (do not send) a reply to the member about their claim."""
    member = _member(member_id)
    first = member["name"].split()[0]
    body = (
        f"Hi {first},\n\n"
        f"We've received your auto claim ({claim_number}). {key_points}\n\n"
        "We'll follow up within one business day. Reply to this message if anything changes.\n"
    )
    return {"to": member["email"], "subject": f"Your claim {claim_number}", "body": body, "status": "draft"}


# --- Approved write tool (adjuster tier only) ---------------------------------


@mcp.tool()
def open_claim(member_id: str, submission_id: str, summary: str, estimated_amount_usd: int) -> dict[str, Any]:
    """Open a new claim in the claims system. This is a write action."""
    _member(member_id)
    _submission(submission_id)
    claim_number = f"CLM{4100 + len(CLAIMS) + 1}"
    claim = {
        "claim_number": claim_number,
        "member_id": member_id,
        "submission_id": submission_id,
        "summary": summary,
        "estimated_amount_usd": estimated_amount_usd,
        "status": "open",
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }
    CLAIMS.append(claim)
    log.info("opened claim %s for %s (%s)", claim_number, member_id, submission_id)
    return claim


# --- Present on the server, NOT in the gateway tool registry -----------------


@mcp.tool()
def issue_payment(claim_number: str, amount_usd: int, routing_number: str, account_number: str) -> dict[str, Any]:
    """Issue a claim payment by ACH. Not registered for agents."""
    log.warning("issue_payment reached the server: %s %s", claim_number, amount_usd)
    return {"claim_number": claim_number, "amount_usd": amount_usd, "status": "paid"}


@mcp.tool()
def export_member_records(member_ids: str) -> dict[str, Any]:
    """Bulk export of member records including PII. Not registered for agents."""
    log.warning("export_member_records reached the server: %s", member_ids)
    return {"records": MEMBERS}


if __name__ == "__main__":
    log.info("auto-claims MCP server starting on %s:%s", mcp.settings.host, mcp.settings.port)
    mcp.run(transport="streamable-http")
