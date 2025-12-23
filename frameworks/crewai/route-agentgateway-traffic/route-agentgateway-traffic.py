from crewai import Agent, Task, Crew, Process, LLM

import os

def main():

    gateway = os.environ.get('INGRESS_GW_ADDRESS')

    if not gateway:
        raise ValueError("INGRESS_GW_ADDRESS environment variable is not set")

    base_url = f"http://{gateway}:8080/anthropic"
    print(f"Using base_url: {base_url}")

    # agentgateway returns a OpenAI-compatible format, so use provider="openai"
    # This happens at the `replaceFullPath: /v1/chat/completions` in the `HTTPRoute` object
    agentgateway_proxy = LLM(
        provider="openai",
        base_url=base_url,
        model="claude-3-5-haiku-latest",
        api_key="testingtesting"  # agentgateway handles auth, but the OpenAI provider requires a key
    )

    search = Agent(
        role="agentgateway traffic router",
        goal="Tell us what agentgateway is",
        backstory="An expert in agentgateway",
        llm=agentgateway_proxy,
    )

    job = Task(
        description="Let us know EXACTLY what agentgateway is",
        expected_output="The best possible definition on agentgateway",
        agent=search
    )

    crew = Crew(
        agents=[search],
        tasks=[job],
        verbose=True,
        process=Process.sequential
    )

    crew.kickoff()

    
if __name__ == '__main__':
    main()