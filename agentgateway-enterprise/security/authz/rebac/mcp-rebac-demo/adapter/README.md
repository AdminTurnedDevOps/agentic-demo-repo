# Thin Authorization Adapter

This service is intentionally small and does two things:

1. `/extauth`: receives Agent Gateway external-auth checks and calls OpenFGA `Check` for `tools/call`.
2. `/mcp`: MCP proxy endpoint that calls OpenFGA `ListObjects` for `tools/list` filtering and `Check` for `tools/call`.

The adapter is not the product story; it is only the bridge from gateway request context to OpenFGA API calls.
