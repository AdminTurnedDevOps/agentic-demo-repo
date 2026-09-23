# AgentCore Runtime requires a Linux ARM64 image serving /invocations and /ping
# on port 8080.
FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PORT=8080

COPY pyproject.toml uv.lock README.md ./
COPY src/ src/

RUN uv sync --frozen --no-cache --no-dev

RUN useradd --create-home --uid 1000 agentcore
USER agentcore

EXPOSE 8080

CMD ["uv", "run", "--no-sync", "uvicorn", "runtime_agent.app:app", "--host", "0.0.0.0", "--port", "8080"]
