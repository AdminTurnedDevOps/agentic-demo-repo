from crewai import Agent, Task, Crew, Process, LLM
from crewai_tools import SerperDevTool
import os

def main():
    os.environ.get('SERPER_API_KEY')
    # Set dummy OpenAI API key for Ollama compatibility
    # CrewAI's LLM class internally uses OpenAI-compatible clients that validate the API key presence
    os.environ['OPENAI_API_KEY'] = 'ollama'

    modelType = LLM(model="ollama/deepseek-r1:8b", temperature=0.1, base_url="http://localhost:11434")

    serper = SerperDevTool(
        search_url="https://a2a-protocol.org/latest/"
    )


    search = Agent(
        role="A2A Expert",
        goal="Let us all know the EXACT definition of A2A",
        backstory="An expert in A2A",
        tools=[serper],
        # if you don't specify a Model, it will default to gpt-4
        llm=modelType,
    )

    job = Task(
        description="Let us all know the EXACT definition of A2A",
        expected_output="The best possible definition on the Agent2Agent(A2A) protocol",
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