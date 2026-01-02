from crewai import Agent, Task, Crew, Process, LLM
from crewai_tools import SerperDevTool
from crewai.memory import LongTermMemory
from crewai.memory.storage.ltm_sqlite_storage import LTMSQLiteStorage
import os

def main():
    # Set dummy OpenAI API key for Ollama compatibility
    # CrewAI's LLM class internally uses OpenAI-compatible clients that validate the API key presence
    os.environ['OPENAI_API_KEY'] = 'ollama'

    modelType = LLM(model="ollama/deepseek-r1:8b", temperature=0.1, base_url="http://localhost:11434")


    search = Agent(
        role="Platform Engineering Expert",
        goal="Answer an question around Platform Engineering",
        backstory="An expert in A2A",
        # if you don't specify a Model, it will default to gpt-4
        llm=modelType,
    )

    job = Task(
        description="Let us know all things Platform Engineering",
        expected_output="Whats the best way to run Kubernetes",
        agent=search
    )
    
    storage = "./memory"

    crew = Crew(
        agents=[search],
        tasks=[job],
        verbose=True,
        process=Process.sequential,
        memory=True,
        long_term_memory=LongTermMemory(
            storage=LTMSQLiteStorage(
                db_path=f"{storage}/memory.db"
            )
        )
    )
    
    crew.kickoff()

    
if __name__ == '__main__':
    main()