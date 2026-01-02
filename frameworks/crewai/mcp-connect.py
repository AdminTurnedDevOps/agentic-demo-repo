from crewai import Agent, Task, Crew, Process, LLM
from crewai.mcp import MCPServerStdio
from crewai.mcp.filters import create_static_tool_filter
import os

def main():
    # Set dummy OpenAI API key for Ollama compatibility
    # CrewAI's LLM class internally uses OpenAI-compatible clients that validate the API key presence
    os.environ['OPENAI_API_KEY'] = 'ollama'

    modelType = LLM(model="ollama/deepseek-r1:8b", temperature=0.1, base_url="http://localhost:11434")


    search = Agent(
        role="Kubernetes Expert",
        goal="Tell me the Pods running in the kube-system namespace",
        backstory="An expert in k8s",
        llm=modelType,
        mcps=[
            MCPServerStdio(
                command="npx",
                args=["-y", "kubernetes-mcp-server@latest"],
                tool_filter=create_static_tool_filter(
                    allowed_tool_names=["pods_list", "pods_get", "namespaces_list"]
                ),
                cache_tools_list=True,
            ),
       ]
    )

    job = Task(
        description="Kubernetes Expert telling us about Pods",
        expected_output="Pod list",
        agent=search
    )

    crew = Crew(
        agents=[search],
        tasks=[job],
        verbose=True,
        process=Process.sequential,
    )
    
    crew.kickoff()

    
if __name__ == '__main__':
    main()