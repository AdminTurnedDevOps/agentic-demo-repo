import os
from strands import Agent, tool
from strands_tools.code_interpreter import AgentCoreCodeInterpreter
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp_client.client import get_streamable_http_mcp_client
from model.load import load_model

app = BedrockAgentCoreApp()
log = app.logger

REGION = os.getenv("AWS_REGION")

# Import AgentCore Gateway as Streamable HTTP MCP Client
mcp_client = get_streamable_http_mcp_client()

# Define a simple function tool
@tool
def add_numbers(a: int, b: int) -> int:
    """Return the sum of two numbers"""
    return a+b

@app.entrypoint
async def invoke(payload, context):
    session_id = getattr(context, 'session_id', 'default')
    user_id = payload.get("user_id") or 'default-user'
    
    # Create code interpreter
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

            # Implement additional handling for other events
            # if "toolUse" in event:
            #   # Process toolUse

            # Handle end of stream
            # if "result" in event:
            #    yield(format_response(event["result"]))

def format_response(result) -> str:
    """Extract code from metrics and format with LLM response."""
    parts = []

    # Extract executed code from metrics
    try:
        tool_metrics = result.metrics.tool_metrics.get('code_interpreter')
        if tool_metrics and hasattr(tool_metrics, 'tool'):
            action = tool_metrics.tool['input']['code_interpreter_input']['action']
            if 'code' in action:
                parts.append(f"## Executed Code:\n```{action.get('language', 'python')}\n{action['code']}\n```\n---\n")
    except (AttributeError, KeyError):
        pass  # No code to extract

    # Add LLM response
    parts.append(f"## 📊 Result:\n{str(result)}")
    return "\n".join(parts)

if __name__ == "__main__":
    app.run()