#!/usr/bin/env python3
"""Audit view over claims-gateway JSON access logs (read from stdin).

  --submission SUB-2042   every call in the agent runs that touched SUB-2042
                          (joined on trace ID: A2A entry, model calls, tools)
  --member <sub>          one member's calls
  --status 401            one HTTP status
  --denials               only rejected calls (4xx/5xx)
  --summary               counts per member: allowed / no identity / denied / limited
  --args                  show tool arguments instead of the decision column
  --all                   include MCP plumbing (initialize, tools/list, ...)
  --last N                last N rows (default 40)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict

PLUMBING = {"initialize", "notifications/initialized", "ping", "tools/list"}


def load(stdin, personas: dict[str, str]) -> list[dict]:
    rows = []
    for line in stdin:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        route = str(rec.get("route", ""))
        if rec.get("scope") != "request" or not route.startswith("auto-claims/"):
            continue
        status = rec.get("audit.status", rec.get("http.status"))
        if status == 405:  # MCP clients probing GET /mcp for SSE; not a decision
            continue
        method = rec.get("audit.mcp_method") or rec.get("mcp.method.name") or ""
        member = rec.get("audit.member", "none")
        agent = rec.get("audit.agent", "none")
        tool = rec.get("audit.tool") or rec.get("gen_ai.tool.name") or method
        if not tool:
            tool = {"auto-claims/claims-a2a": "A2A -> claims-agent",
                    "auto-claims/claims-llm": "model call",
                    "auto-claims/claims-mcp": "tools"}.get(route, route)
        reason = rec.get("reason") or ""
        if not reason:
            reason = "allowed" if status in (200, 202) else (rec.get("error") or "")
        rows.append({
            "time": rec.get("time", "")[11:19],
            "persona": personas.get(member, "anonymous" if member == "none" else member[:8]),
            "member": member,
            "agent": agent.rsplit(":", 1)[-1],
            "tool": tool,
            "method": method,
            "model": (rec.get("audit.model_served") or rec.get("audit.model_requested") or "").replace("us.anthropic.", ""),
            "submission": rec.get("audit.submission", ""),
            "args": rec.get("audit.tool_args", "") or "",
            "status": status,
            "tokens": rec.get("audit.tokens", 0),
            "reason": reason,
            "trace": rec.get("trace.id", ""),
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reader", default="")
    ap.add_argument("--writer", default="")
    ap.add_argument("--submission")
    ap.add_argument("--member")
    ap.add_argument("--status", type=int)
    ap.add_argument("--denials", action="store_true")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--args", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--last", type=int, default=40)
    a = ap.parse_args()
    personas = {k: v for k, v in ((a.reader, "reader"), (a.writer, "writer")) if k}
    member = {"reader": a.reader, "writer": a.writer}.get(a.member, a.member) if a.member else None

    rows = load(sys.stdin, personas)

    if a.summary:
        counts: dict[str, Counter] = defaultdict(Counter)
        for r in rows:
            if r["method"] in PLUMBING:
                continue
            bucket = {200: "allowed", 202: "allowed", 401: "no identity", 403: "denied/blocked",
                      400: "denied/blocked", 429: "limited"}.get(r["status"], f"http {r['status']}")
            counts[r["persona"]][bucket] += 1
        cols = ["allowed", "no identity", "denied/blocked", "limited"]
        print(f"{'member':<10}" + "".join(f"{c:>16}" for c in cols))
        for persona, c in sorted(counts.items()):
            print(f"{persona:<10}" + "".join(f"{c.get(col, 0):>16}" for col in cols))
        return 0

    if a.submission:
        traces = {r["trace"] for r in rows if r["submission"] == a.submission and r["trace"]}
        rows = [r for r in rows if r["submission"] == a.submission or (r["trace"] and r["trace"] in traces)]
    if member:
        rows = [r for r in rows if r["member"] == member]
    if a.status is not None:
        rows = [r for r in rows if r["status"] == a.status]
    if a.denials:
        rows = [r for r in rows if isinstance(r["status"], int) and r["status"] >= 400]
    if not a.all:
        rows = [r for r in rows if r["method"] not in PLUMBING]
    # Collapse consecutive identical rows (e.g. kagent's tool discovery retrying every minute).
    collapsed: list[dict] = []
    for r in rows:
        key = (r["persona"], r["agent"], r["tool"], r["status"], r["reason"], r["submission"])
        if collapsed and collapsed[-1]["_key"] == key and r["status"] != 200:
            collapsed[-1]["_n"] += 1
            continue
        collapsed.append({**r, "_key": key, "_n": 1})
    rows = collapsed[-a.last:]

    last_col = "arguments" if a.args else "decision"
    fmt = "{:<9} {:<9} {:<24} {:<22} {:<18} {:<9} {:<6} {:<6} {}"
    print(fmt.format("time", "member", "agent", "tool / call", "model", "subm.", "status", "tokens", last_col))
    for r in rows:
        print(fmt.format(r["time"], r["persona"], r["agent"][:24], r["tool"][:22], r["model"][:18],
                         r["submission"], str(r["status"]), str(r["tokens"]),
                         (r["args"][:60] if a.args else r["reason"]) + (f"  (x{r['_n']})" if r["_n"] > 1 else "")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
