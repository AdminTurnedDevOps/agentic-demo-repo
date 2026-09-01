"""A2A server entrypoint for dealer-assistant-byo."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import uvicorn
from agent import graph
from fastapi import Request
from kagent.core import KAgentConfig
from kagent.langgraph import KAgentApp
from mcp_tools import set_authorization_header

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("dealer-assistant-byo")


def main() -> None:
    card_path = Path(__file__).with_name("agent-card.json")
    with card_path.open(encoding="utf-8") as fh:
        agent_card = json.load(fh)
    config = KAgentConfig()
    app = KAgentApp(graph=graph, agent_card=agent_card, config=config, tracing=False).build()

    @app.middleware("http")
    async def capture_identity(request: Request, call_next):
        set_authorization_header(request.headers.get("authorization"))
        try:
            return await call_next(request)
        finally:
            set_authorization_header(None)

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    logger.info("starting on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
