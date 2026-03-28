"""CrewAI agent with live streaming to agentevals via standard OTLP export.

No agentevals SDK dependency — just standard OpenTelemetry exporters
pointing at the agentevals OTLP receiver on port 4318.

Prerequisites:
    1. Install dependencies:
       $ pip install -r requirements.txt

    2. Start agentevals dev server:
       $ agentevals serve --dev

    3. Set Anthropic API key:
       $ export ANTHROPIC_API_KEY="your-key-here"

Usage:
    $ python main.py

View live results at http://localhost:5173
"""

import os

from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# NOTE: Do NOT import crewai at module level. Importing crewai sets a global
# TracerProvider, which prevents us from registering our own with OTLP
# exporters. We import it inside main() after OTel setup is complete.

OTEL_ENDPOINT = "http://localhost:4318"


def setup_otel(endpoint: str = OTEL_ENDPOINT):
    """Configure OpenTelemetry with OTLP export to agentevals.

    Must be called BEFORE importing crewai, which sets its own
    TracerProvider at import time.
    """
    os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "true"

    os.environ.setdefault(
        "OTEL_RESOURCE_ATTRIBUTES",
        "agentevals.eval_set_id=crewai_agent_eval,agentevals.session_name=crewai-live-session",
    )

    resource = Resource.create()

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"), schedule_delay_millis=1000)
    )
    trace.set_tracer_provider(tracer_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs"), schedule_delay_millis=1000)
    )
    set_logger_provider(logger_provider)

    AnthropicInstrumentor().instrument()

    return tracer_provider, logger_provider


def main():
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set. Set it with:")
        print("  export ANTHROPIC_API_KEY='your-key-here'")
        return

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", OTEL_ENDPOINT)
    print(f"OTLP endpoint: {endpoint}")

    tracer_provider, logger_provider = setup_otel(endpoint)

    # Import crewai AFTER OTel setup so our TracerProvider is the global one
    from agent import create_crew

    crew = create_crew()
    result = crew.kickoff()
    print()
    print(result)

    tracer_provider.force_flush()
    logger_provider.force_flush()
    print()
    print("All traces and logs flushed to OTLP receiver.")


if __name__ == "__main__":
    main()
