"""Standard OTel bootstrap — import this BEFORE importing the agent or LangChain.

Exports OTLP traces and logs to the endpoint in OTEL_EXPORTER_OTLP_ENDPOINT.
Defaults to http://localhost:4318 (local agentevals serve).

Used by:
- Demo 1: agentevals batch CLI (writes traces to local agentevals, then dumps to file)
- Demo 2: in-cluster agent pushing to agentevals Service
- Demo 4: agent runs that produce traces for offline scoring
"""

import os

os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
os.environ.setdefault("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
os.environ.setdefault("OTEL_SERVICE_NAME", "k8s-troubleshooter")
os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "true"

from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def init_otel() -> tuple[TracerProvider, LoggerProvider]:
    resource = Resource.create({"service.name": os.environ["OTEL_SERVICE_NAME"]})

    tp = TracerProvider(resource=resource)
    tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tp)

    lp = LoggerProvider(resource=resource)
    lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(lp)

    from opentelemetry.instrumentation.openai import OpenAIInstrumentor
    OpenAIInstrumentor().instrument()

    return tp, lp


def shutdown(tp: TracerProvider, lp: LoggerProvider) -> None:
    tp.force_flush()
    lp.force_flush()
    tp.shutdown()
    lp.shutdown()
