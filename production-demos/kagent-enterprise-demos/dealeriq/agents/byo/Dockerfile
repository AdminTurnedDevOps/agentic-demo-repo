FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
# kagent-core 0.9.12 declares opentelemetry-instrumentation-fastapi>=0.52.0,
# which does not exist as a stable PyPI release. Install the kagent wheels
# without that extra, then the runtime deps we actually import.
RUN pip install --no-cache-dir \
      kagent-langgraph==0.9.12 \
      kagent-core==0.9.12 \
      --no-deps \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && pip install --no-cache-dir --pre \
      'opentelemetry-instrumentation-fastapi==0.59b0' \
      'opentelemetry-instrumentation-httpx==0.59b0' \
      'opentelemetry-instrumentation-openai==0.52.5' \
      'opentelemetry-instrumentation-anthropic==0.52.5' \
      'opentelemetry-instrumentation-google-generativeai==0.52.5'

COPY agent.py mcp_tools.py cli.py agent-card.json /app/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV PORT=8080
ENV HOST=0.0.0.0

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/health || exit 1

CMD ["python", "/app/cli.py"]
