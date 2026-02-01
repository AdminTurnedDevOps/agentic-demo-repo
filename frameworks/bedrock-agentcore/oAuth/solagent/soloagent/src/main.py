import os
from strands import Agent, tool
from strands_tools.code_interpreter import AgentCoreCodeInterpreter
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig, RetrievalConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.identity import requires_access_token
from mcp_client.client import get_streamable_http_mcp_client
from model.load import load_model

import jwt


app = BedrockAgentCoreApp()
log = app.logger

OAUTH_CALLBACK_URL = os.getenv("OAUTH_CALLBACK_URL")
REGION = os.getenv("AWS_REGION")

# Import Agentore Gateway as Streamable HTTP MCP Client
mcp_client = get_streamable_http_mcp_client()

# Define a simple function tool
@tool
def add_numbers(a: int, b: int) -> int:
    """Return the sum of two numbers"""
    return a+b

async def handle_auth_url(url):
    return {"type": "authorization_required", "authorization_url": url}

@app.entrypoint
@requires_access_token(
    provider_name="keycloak-provider",
    scopes=["openid", "profile", "email"],
    auth_flow="USER_FEDERATION",
    on_auth_url=handle_auth_url,
    force_authentication=False,
    callback_url=OAUTH_CALLBACK_URL,
)

async def invoke(payload, context, *, access_token: str):
    user_info = jwt.decode(access_token, options={"verify_signature": False})
    user_id = user_info.get("sub", "unknown-user")

    session_id = getattr(context, 'session_id', 'default')

    code_interpreter = AgentCoreCodeInterpreter(
        region=REGION,
        session_name=session_id,
        auto_create=True,
        persist_sessions=True
    )

    with mcp_client as client:
        # Get MCP Tools
        tools = client.list_tools_sync()

        # Create agent
        agent = Agent(
            model=load_model(),
            system_prompt="""
                You are a helpful assistant with code execution capabilities. Use tools when appropriate.
            """,
            tools=[code_interpreter.code_interpreter, add_numbers] + tools
        )

        # Execute and format response
        stream = agent.stream_async(payload.get("prompt"))

        async for event in stream:
            # Handle Text parts of the response
            if "data" in event and isinstance(event["data"], str):
                yield event["data"]

def format_response(result) -> str:
    """Extract code from metrics and format with LLM response."""
    parts = []

    try:
        tool_metrics = result.metrics.tool_metrics.get('code_interpreter')
        if tool_metrics and hasattr(tool_metrics, 'tool'):
            action = tool_metrics.tool['input']['code_interpreter_input']['action']
            if 'code' in action:
                parts.append(f"## Executed Code:\n```{action.get('language', 'python')}\n{action['code']}\n```\n---\n")
    except (AttributeError, KeyError):
        pass 

    parts.append(f"## 📊 Result:\n{str(result)}")
    return "\n".join(parts)

if __name__ == "__main__":
    app.run()