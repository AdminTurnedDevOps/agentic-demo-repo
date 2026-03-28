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

import json
import os
from pathlib import Path
from typing import Any

from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor,
    LogExportResult,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExportResult,
)

# NOTE: Do NOT import crewai at module level. Importing crewai sets a global
# TracerProvider, which prevents us from registering our own with OTLP
# exporters. We import it inside main() after OTel setup is complete.

OTEL_ENDPOINT = "http://localhost:4318"
BROWSER_TRACE_PATH = "crewai-trace.json"
_GENAI_EVENT_KEYS = {"gen_ai.input.messages", "gen_ai.output.messages"}


class CapturingSpanExporter:
    """Collect spans in-memory so we can write a browser-uploadable trace file."""

    def __init__(self):
        self.spans = []

    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        return None

    def force_flush(self, timeout_millis: int = 30_000):
        return True


class CapturingLogExporter:
    """Collect OTel log records in-memory for GenAI message enrichment."""

    def __init__(self):
        self.logs = []

    def export(self, batch):
        self.logs.extend(batch)
        return LogExportResult.SUCCESS

    def shutdown(self):
        return None

    def force_flush(self, timeout_millis: int = 30_000):
        return True


def _normalize_value(value: Any) -> Any:
    """Convert SDK attribute values into JSON/tag-friendly primitives."""
    if isinstance(value, tuple):
        value = list(value)
    if isinstance(value, list):
        return [_normalize_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _normalize_value(v) for k, v in value.items()}
    return value


def _value_to_otlp(value: Any) -> dict[str, Any]:
    """Encode a Python value as an OTLP-style AnyValue dict."""
    value = _normalize_value(value)
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"intValue": value}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, dict):
        return {
            "kvlistValue": {
                "values": [{"key": str(k), "value": _value_to_otlp(v)} for k, v in value.items()]
            }
        }
    if isinstance(value, list):
        return {"arrayValue": {"values": [_value_to_otlp(v) for v in value]}}
    return {"stringValue": str(value)}


def _otlp_to_plain(value_obj: dict[str, Any]) -> Any:
    """Decode an OTLP-style AnyValue dict back into plain Python values."""
    if "stringValue" in value_obj:
        return value_obj["stringValue"]
    if "intValue" in value_obj:
        return int(value_obj["intValue"])
    if "doubleValue" in value_obj:
        return float(value_obj["doubleValue"])
    if "boolValue" in value_obj:
        return value_obj["boolValue"]
    if "kvlistValue" in value_obj:
        values = value_obj["kvlistValue"].get("values", [])
        return {item.get("key", ""): _otlp_to_plain(item.get("value", {})) for item in values}
    if "arrayValue" in value_obj:
        return [_otlp_to_plain(v) for v in value_obj["arrayValue"].get("values", [])]
    return value_obj


def _flatten_otlp_attributes(attrs: list[dict[str, Any]]) -> dict[str, Any]:
    flat = {}
    for attr in attrs:
        key = attr.get("key", "")
        value = _otlp_to_plain(attr.get("value", {}))
        if key:
            flat[key] = value
    return flat


def _extract_messages_from_logs(logs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reconstruct GenAI messages from log records, mirroring agentevals behavior."""
    input_messages = []
    output_messages = []
    seen_user = set()
    seen_assistant = set()

    for log in logs:
        event_name = log.get("event_name", "")
        body = log.get("body", {})
        if not isinstance(body, dict):
            continue

        if event_name == "gen_ai.user.message":
            user_content = body.get("content", "")
            if user_content and user_content not in seen_user:
                input_messages.append({"role": "user", "content": user_content})
                seen_user.add(user_content)
        elif event_name in ("gen_ai.assistant.message", "gen_ai.choice"):
            if event_name == "gen_ai.choice":
                nested = body.get("message", {}) if isinstance(body.get("message"), dict) else {}
                assistant_content = body.get("content") or nested.get("content") or ""
                tool_calls = nested.get("tool_calls", [])
            else:
                assistant_content = body.get("content") or ""
                tool_calls = body.get("tool_calls", [])

            dedupe_key = f"{assistant_content}:{json.dumps(tool_calls, sort_keys=True) if tool_calls else ''}"
            if (assistant_content or tool_calls) and dedupe_key not in seen_assistant:
                message = {"role": "assistant", "content": assistant_content}
                if tool_calls:
                    message["tool_calls"] = tool_calls
                output_messages.append(message)
                seen_assistant.add(dedupe_key)

    return input_messages, output_messages


def _capture_log_body(body: Any) -> Any:
    if isinstance(body, str):
        try:
            return json.loads(body)
        except (TypeError, json.JSONDecodeError):
            return body
    if isinstance(body, (dict, list, int, float, bool)) or body is None:
        return body
    return str(body)


def _log_record_to_event(log_data: Any) -> dict[str, Any] | None:
    """Convert an in-memory OTel log record into agentevals-style event data."""
    record = getattr(log_data, "log_record", log_data)
    event_name = getattr(record, "event_name", None)
    attributes = dict(getattr(record, "attributes", {}) or {})

    if not event_name:
        event_name = attributes.get("event.name", "")
    if not event_name or not str(event_name).startswith("gen_ai."):
        return None

    event = {
        "event_name": str(event_name),
        "timestamp": getattr(record, "timestamp", None) or getattr(record, "observed_timestamp", None),
        "body": _capture_log_body(getattr(record, "body", None)),
        "attributes": {str(k): _normalize_value(v) for k, v in attributes.items()},
    }

    span_id = getattr(record, "span_id", 0)
    if span_id:
        event["span_id"] = f"{int(span_id):016x}"

    return event


def _inject_messages(span: dict[str, Any], input_messages: list[dict[str, Any]], output_messages: list[dict[str, Any]], session_name: str) -> dict[str, Any]:
    span_copy = dict(span)
    attrs = list(span_copy.get("attributes", []))
    existing = {item.get("key") for item in attrs}

    if input_messages and "gen_ai.input.messages" not in existing:
        attrs.append({"key": "gen_ai.input.messages", "value": {"stringValue": json.dumps(input_messages)}})
    if output_messages and "gen_ai.output.messages" not in existing:
        attrs.append({"key": "gen_ai.output.messages", "value": {"stringValue": json.dumps(output_messages)}})
    if "gen_ai.agent.name" not in existing:
        attrs.append({"key": "gen_ai.agent.name", "value": {"stringValue": session_name}})

    span_copy["attributes"] = attrs
    return span_copy


def _collect_indexed_messages(attrs: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    """Build GenAI message arrays from indexed attr families like prompt/completion."""
    grouped: dict[int, dict[str, Any]] = {}
    prefix_with_dot = f"{prefix}."
    for key, value in attrs.items():
        if not key.startswith(prefix_with_dot):
            continue
        remainder = key[len(prefix_with_dot) :]
        idx_str, sep, field = remainder.partition(".")
        if not sep or not idx_str.isdigit():
            continue
        grouped.setdefault(int(idx_str), {})[field] = value

    messages = []
    for _, fields in sorted(grouped.items()):
        role = str(fields.get("role", "")).strip()
        content = fields.get("content")
        if not role:
            continue
        message = {"role": role}
        if content is not None and str(content) != "":
            message["content"] = str(content)
        messages.append(message)
    return messages


def _synthesize_messages_from_attrs(span: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fallback for Anthropic spans that expose prompt/completion attrs instead of message arrays."""
    attrs = _flatten_otlp_attributes(span.get("attributes", []))
    input_messages = _collect_indexed_messages(attrs, "gen_ai.prompt")
    output_messages = _collect_indexed_messages(attrs, "gen_ai.completion")
    return input_messages, output_messages


def _enrich_spans_with_logs(spans: list[dict[str, Any]], captured_logs: list[Any], session_name: str) -> list[dict[str, Any]]:
    """Merge GenAI log message content back into spans for Jaeger export."""
    log_events = [event for event in (_log_record_to_event(item) for item in captured_logs) if event]
    if not log_events:
        enriched = []
        for span in spans:
            input_messages, output_messages = _synthesize_messages_from_attrs(span)
            enriched.append(_inject_messages(span, input_messages, output_messages, session_name))
        return enriched

    logs_by_span = {}
    for event in log_events:
        span_id = event.get("span_id")
        if not span_id:
            continue
        logs_by_span.setdefault(span_id, []).append(event)

    enriched = []
    for span in spans:
        span_logs = logs_by_span.get(span.get("spanId", ""), [])
        input_messages, output_messages = _extract_messages_from_logs(span_logs)
        if not input_messages and not output_messages:
            input_messages, output_messages = _synthesize_messages_from_attrs(span)
        enriched.append(_inject_messages(span, input_messages, output_messages, session_name))
    return enriched


def _readable_span_to_otlp(span: Any) -> dict[str, Any]:
    """Convert a ReadableSpan into the OTLP-like shape used by agentevals."""
    attributes = {str(k): _normalize_value(v) for k, v in dict(span.attributes or {}).items()}

    scope = getattr(span, "instrumentation_scope", None)
    if scope and getattr(scope, "name", "") and "otel.scope.name" not in attributes:
        attributes["otel.scope.name"] = scope.name
    if scope and getattr(scope, "version", "") and "otel.scope.version" not in attributes:
        attributes["otel.scope.version"] = scope.version

    resource = getattr(span, "resource", None)
    if resource:
        for key, value in dict(resource.attributes or {}).items():
            attributes.setdefault(str(key), _normalize_value(value))

    events = []
    for event in span.events or []:
        event_attrs = {str(k): _normalize_value(v) for k, v in dict(event.attributes or {}).items()}
        for key in _GENAI_EVENT_KEYS:
            if key in event_attrs and key not in attributes:
                attributes[key] = event_attrs[key]
        events.append(
            {
                "name": event.name,
                "timeUnixNano": str(event.timestamp),
                "attributes": [{"key": key, "value": _value_to_otlp(value)} for key, value in event_attrs.items()],
            }
        )

    parent_span_id = ""
    parent = getattr(span, "parent", None)
    if parent and getattr(parent, "span_id", 0):
        parent_span_id = f"{int(parent.span_id):016x}"

    return {
        "traceId": f"{int(span.context.trace_id):032x}",
        "spanId": f"{int(span.context.span_id):016x}",
        "parentSpanId": parent_span_id,
        "name": span.name,
        "startTimeUnixNano": str(span.start_time),
        "endTimeUnixNano": str(span.end_time),
        "attributes": [{"key": key, "value": _value_to_otlp(value)} for key, value in attributes.items()],
        "events": events,
    }


def _tag_type_and_value(value: Any) -> tuple[str, Any]:
    value = _normalize_value(value)
    if isinstance(value, bool):
        return "bool", value
    if isinstance(value, int) and not isinstance(value, bool):
        return "int64", value
    if isinstance(value, float):
        return "float64", value
    if isinstance(value, (list, dict)):
        return "string", json.dumps(value)
    return "string", str(value)


def _otlp_span_to_jaeger(span: dict[str, Any]) -> dict[str, Any]:
    attrs = _flatten_otlp_attributes(span.get("attributes", []))
    tags = []
    for key, value in attrs.items():
        tag_type, tag_value = _tag_type_and_value(value)
        tags.append({"key": key, "type": tag_type, "value": tag_value})

    logs = []
    for event in span.get("events", []):
        fields = [{"key": "event.name", "type": "string", "value": event.get("name", "")}]
        for attr in event.get("attributes", []):
            value = _otlp_to_plain(attr.get("value", {}))
            field_type, field_value = _tag_type_and_value(value)
            fields.append({"key": attr.get("key", ""), "type": field_type, "value": field_value})
        logs.append({"timestamp": int(event.get("timeUnixNano", "0")) // 1000, "fields": fields})

    references = []
    parent_span_id = span.get("parentSpanId")
    if parent_span_id:
        references.append(
            {
                "refType": "CHILD_OF",
                "traceID": span["traceId"],
                "spanID": parent_span_id,
            }
        )

    start_ns = int(span.get("startTimeUnixNano", "0"))
    end_ns = int(span.get("endTimeUnixNano", "0"))

    return {
        "traceID": span["traceId"],
        "spanID": span["spanId"],
        "operationName": span.get("name", ""),
        "references": references,
        "startTime": start_ns // 1000,
        "duration": max(0, end_ns - start_ns) // 1000,
        "tags": tags,
        "logs": logs,
        "processID": "p1",
        "warnings": None,
    }


def _is_evaluable_genai_span(span: dict[str, Any]) -> bool:
    attrs = _flatten_otlp_attributes(span.get("attributes", []))
    return bool(
        attrs.get("gen_ai.request.model")
        or attrs.get("gen_ai.input.messages")
        or attrs.get("gen_ai.output.messages")
        or attrs.get("gen_ai.prompt.0.content")
        or attrs.get("gen_ai.completion.0.content")
    )


def write_browser_trace(span_exporter: CapturingSpanExporter, log_exporter: CapturingLogExporter, output_path: str = BROWSER_TRACE_PATH, session_name: str = "crewai-live-session"):
    """Write a Jaeger-style JSON trace file that agentevals UI can upload."""
    if not span_exporter.spans:
        return None

    otlp_spans = [_readable_span_to_otlp(span) for span in span_exporter.spans]
    enriched_spans = _enrich_spans_with_logs(otlp_spans, log_exporter.logs, session_name)

    export_spans = [span for span in enriched_spans if _is_evaluable_genai_span(span)]
    if not export_spans:
        export_spans = enriched_spans

    unified_trace_id = next((span["traceId"] for span in export_spans if span.get("traceId")), "0" * 32)
    export_span_ids = {span.get("spanId", "") for span in export_spans}
    normalized_spans = []
    for span in export_spans:
        span_copy = dict(span)
        span_copy["traceId"] = unified_trace_id
        parent_span_id = span_copy.get("parentSpanId", "")
        if parent_span_id and parent_span_id not in export_span_ids:
            span_copy["parentSpanId"] = ""
        normalized_spans.append(span_copy)

    jaeger_spans = [_otlp_span_to_jaeger(span) for span in normalized_spans]
    service_name = "crewai-live-session"
    if jaeger_spans and jaeger_spans[0]["tags"]:
        for tag in jaeger_spans[0]["tags"]:
            if tag["key"] == "service.name":
                service_name = tag["value"]
                break

    trace_docs = [
        {
            "traceID": unified_trace_id,
            "spans": jaeger_spans,
            "processes": {
                "p1": {
                    "serviceName": service_name,
                    "tags": [],
                }
            },
            "warnings": None,
        }
    ]

    output = {
        "data": trace_docs,
        "total": len(trace_docs),
        "limit": 0,
        "offset": 0,
        "errors": None,
    }

    path = Path(output_path)
    path.write_text(json.dumps(output, indent=2))
    return path


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

    span_capture_exporter = CapturingSpanExporter()
    log_capture_exporter = CapturingLogExporter()

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"), schedule_delay_millis=1000)
    )
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_capture_exporter))
    trace.set_tracer_provider(tracer_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs"), schedule_delay_millis=1000)
    )
    logger_provider.add_log_record_processor(SimpleLogRecordProcessor(log_capture_exporter))
    set_logger_provider(logger_provider)

    AnthropicInstrumentor().instrument()

    return tracer_provider, logger_provider, span_capture_exporter, log_capture_exporter


def main():
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set. Set it with:")
        print("  export ANTHROPIC_API_KEY='your-key-here'")
        return

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", OTEL_ENDPOINT)
    print(f"OTLP endpoint: {endpoint}")

    tracer_provider, logger_provider, span_capture_exporter, log_capture_exporter = setup_otel(endpoint)

    # Import crewai AFTER OTel setup so our TracerProvider is the global one
    from agent import create_crew

    crew = create_crew()
    result = crew.kickoff()
    print()
    print(result)

    tracer_provider.force_flush()
    logger_provider.force_flush()

    browser_trace = write_browser_trace(span_capture_exporter, log_capture_exporter)
    print()
    print("All traces and logs flushed to OTLP receiver.")
    if browser_trace:
        print(f"Browser upload trace written to: {browser_trace}")


if __name__ == "__main__":
    main()
