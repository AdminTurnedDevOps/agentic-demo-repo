import os

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

os.getenv("ANTHROPIC_API_KEY")

agent = create_agent(
    model="claude-sonnet-4-5",
    system_prompt="You are a Platform Engineer"
)

out = agent.invoke(
    {"messages": [{"role": "user", "content": "What is a Platform Engineer?"}]}
)

print(out)