### LLM Metrics

`agentgateway_gen_ai_client_token_usage_sum` - Total Tokens

`agentgateway_gen_ai_client_token_usage_count` - Number of requests

`agentgateway_gen_ai_client_token_usage_bucket` - Tracks the distribution of token usage across different ranges

### Request & Connection Metrics:
`agentgateway_downstream_connections_total` - Counter of downstream connections (labeled by bind, gateway, listener, protocol)

### MCP Metrics:
agentgateway_mcp_requests_total - Counter of MCP tool calls

### xDS Metrics:
`agentgateway_xds_message_total` - Counter of xDS messages received (by URL type)

`agentgateway_xds_message_bytes_total` - Counter of xDS bytes received

### Build Info:
`agentgateway_build_info` - Build/version information

### Docs
https://agentgateway.dev/docs/llm/observability/