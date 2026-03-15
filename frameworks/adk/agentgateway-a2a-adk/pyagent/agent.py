from google.adk.agents.llm_agent import Agent
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters
import os
import logging

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing K8s Assistant agent...")

# `root_agent` variable is mandatory. Otherwise, you may see:
# ValueError: No root_agent found for 'pyagent'
try:
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
                        args=["-y", "kubernetes-mcp-server"],
                        env=os.environ.copy()  # Pass environment variables
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
    logger.info("Agent initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize agent: {e}", exc_info=True)
    raise
