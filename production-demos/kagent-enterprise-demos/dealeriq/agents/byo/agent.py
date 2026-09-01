"""DealerIQ BYO LangGraph agent.

kagent SDK (KAgentCheckpointer, KAgentApp, interrupt relay) is wired at init.
Graph logic is standard LangGraph. Privileged send_customer_offer uses interrupt().
MCP calls go through dealer-leads-mcp so AccessPolicy at the waypoint still applies.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Any

import httpx
from kagent.core import KAgentConfig
from kagent.langgraph import KAgentCheckpointer
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from typing_extensions import TypedDict

from mcp_tools import call_mcp_tool

logger = logging.getLogger(__name__)

TOOLS_REQUIRING_APPROVAL = {"send_customer_offer"}

kagent_checkpointer = KAgentCheckpointer(
    client=httpx.AsyncClient(base_url=KAgentConfig().url),
    app_name=KAgentConfig().app_name,
)


@tool
async def get_lead_details(lead_id: str) -> str:
    """Pull an inbound CRM lead by id."""
    return await call_mcp_tool("get_lead_details", {"lead_id": lead_id})


@tool
async def score_lead(lead_id: str) -> str:
    """Qualify a lead: intent, budget fit, and timeline."""
    return await call_mcp_tool("score_lead", {"lead_id": lead_id})


@tool
async def search_inventory(vehicle_type: str = "", max_price_usd: int = 0, lead_id: str = "") -> str:
    """Match on-lot vehicles to a type, max price, or lead budget."""
    args: dict[str, Any] = {}
    if vehicle_type:
        args["vehicle_type"] = vehicle_type
    if max_price_usd:
        args["max_price_usd"] = max_price_usd
    if lead_id:
        args["lead_id"] = lead_id
    return await call_mcp_tool("search_inventory", args)


@tool
async def get_vehicle_history(stock: str = "", history_id: str = "") -> str:
    """Attach vehicle history to a listing pitch."""
    args: dict[str, Any] = {}
    if stock:
        args["stock"] = stock
    if history_id:
        args["history_id"] = history_id
    return await call_mcp_tool("get_vehicle_history", args)


@tool
async def draft_followup(lead_id: str, stock: str = "") -> str:
    """Compose (do not send) outreach for a lead."""
    args: dict[str, Any] = {"lead_id": lead_id}
    if stock:
        args["stock"] = stock
    return await call_mcp_tool("draft_followup", args)


@tool
async def send_customer_offer(lead_id: str, stock: str, price_usd: int, discount_usd: int = 0) -> str:
    """Send a discounted customer offer. Requires manager approval."""
    return await call_mcp_tool(
        "send_customer_offer",
        {
            "lead_id": lead_id,
            "stock": stock,
            "price_usd": price_usd,
            "discount_usd": discount_usd,
        },
    )


@tool
async def update_lead_status(lead_id: str, status: str) -> str:
    """Mutate CRM lead status (new, contacted, qualified, offer_sent, won, lost)."""
    return await call_mcp_tool("update_lead_status", {"lead_id": lead_id, "status": status})


@tool
async def export_leads() -> str:
    """Bulk export of CRM leads including PII."""
    return await call_mcp_tool("export_leads", {})


ALL_TOOLS = [
    get_lead_details,
    score_lead,
    search_inventory,
    get_vehicle_history,
    draft_followup,
    send_customer_offer,
    update_lead_status,
    export_leads,
]
TOOL_MAP = {t.name: t for t in ALL_TOOLS}

SYSTEM = SystemMessage(
    content=(
        "You are DealerIQ, the dealership AI assistant for inbound leads. "
        "Work leads: details → score → inventory match → history → draft follow-up. "
        "Lead 4127 (Jordan Hale) is the default demo lead: used midsize pickup, $38,000, this month. "
        "Call send_customer_offer only when asked to send a discounted offer. "
        "Call update_lead_status only when asked to change CRM status. "
        "Never call export_leads unless the user explicitly asks for a bulk export. "
        "Be concise. Name stock numbers. Do not invent vehicles."
    )
)


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def _llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.environ.get("MODEL_NAME", "claude-sonnet-4-6"),
        base_url=os.environ.get("OPENAI_BASE_URL"),
        api_key=os.environ.get("OPENAI_API_KEY", "not-used"),
    ).bind_tools(ALL_TOOLS)


async def call_model(state: AgentState) -> dict[str, Any]:
    messages = [SYSTEM, *state["messages"]]
    response = await _llm().ainvoke(messages)
    return {"messages": [response]}


async def run_tools(state: AgentState) -> dict[str, Any]:
    last_message = state["messages"][-1]
    assert isinstance(last_message, AIMessage) and last_message.tool_calls
    results: list[ToolMessage] = []
    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_call_id = tool_call["id"]
        if tool_name in TOOLS_REQUIRING_APPROVAL:
            decision = interrupt(
                {
                    "action_requests": [
                        {
                            "name": tool_name,
                            "args": tool_args,
                            "id": tool_call_id,
                        }
                    ]
                }
            )
            decision_type = decision.get("decision_type", "reject") if isinstance(decision, dict) else "reject"
            if decision_type != "approve":
                reason = ""
                if isinstance(decision, dict):
                    reasons = decision.get("rejection_reasons", {})
                    reason = reasons.get("*", "") if isinstance(reasons, dict) else ""
                msg = "Tool call was rejected by user."
                if reason:
                    msg += f" Reason: {reason}"
                results.append(ToolMessage(content=msg, tool_call_id=tool_call_id, name=tool_name))
                continue
        tool_fn = TOOL_MAP[tool_name]
        result = await tool_fn.ainvoke(tool_args)
        results.append(ToolMessage(content=str(result), tool_call_id=tool_call_id, name=tool_name))
    return {"messages": results}


def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return END


builder = StateGraph(AgentState)
builder.add_node("agent", call_model)
builder.add_node("tools", run_tools)
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
builder.add_edge("tools", "agent")
graph = builder.compile(checkpointer=kagent_checkpointer)
