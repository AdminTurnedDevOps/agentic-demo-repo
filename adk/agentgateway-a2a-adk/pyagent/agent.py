from google.adk.agents.llm_agent import Agent
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

# `root_agent` variable is mandatory. Otherwise, you may see:
# ValueError: No root_agent found for 'pyagent'
root_agent = LlmAgent(
    model=LiteLlm('anthropic/claude-3-7-sonnet-latest'),
    name='k8sassistant',
    description='You are a Kubernetes expert',
    instruction='Answer questions about all things Kubernetes and Istio Service Mesh to the best of your ability. Use the Kubernetes tools to check pods, namespaces, events, and other cluster resources.',
    tools=[
        MCPToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command='npx',
                    args=["-y", "@modelcontextprotocol/server-kubernetes"]
                )
            ),
            tool_filter=[
                'events_list',
                'namespaces_list',
                'pods_list',
                'pods_get',
                'pods_log',
                'resources_list',
                'resources_get'
            ]
        )
    ]
)
