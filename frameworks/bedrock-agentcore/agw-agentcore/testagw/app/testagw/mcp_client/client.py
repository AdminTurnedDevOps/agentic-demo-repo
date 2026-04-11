"""Compatibility stub for MCP client wiring.

This project uses agentgateway through the model client in model/load.py,
so no MCP client is configured here.
"""

def get_streamable_http_mcp_client():
    """Return no MCP client for the LLM-endpoint integration path."""
    return None
