from google.adk.agents.llm_agent import Agent
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

# `root_agent` variable is mandatory. Otherwise, you may see:
# ValueError: No root_agent found for 'pyagent'
root_agent = LlmAgent(
    model=LiteLlm('anthropic/claude-3-7-sonnet-latest'),
    name='k8sassistant',
    description='You are a Kubernetes expert',
    instruction='Answer questions about all things Kubernetes and Istio Service Mesh to the best of your ability',
)
