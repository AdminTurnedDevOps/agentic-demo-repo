from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    # IMPORTANT: stream logs to stderr so STDIO MCP messages on stdout stay clean.
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
