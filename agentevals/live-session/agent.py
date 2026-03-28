"""CrewAI agent for agentevals live session streaming."""

from crewai import Agent, Crew, Process, Task, LLM


def create_crew(model: str = "anthropic/claude-sonnet-4-20250514") -> Crew:
    """Build a CrewAI Crew with sequential tasks streamed to agentevals."""
    llm = LLM(model=model, temperature=0.0)

    analyst = Agent(
        role="Tech Analyst",
        goal="Provide concise, insightful analysis on technology topics.",
        backstory=(
            "You are a senior technology analyst who gives clear, "
            "direct answers backed by reasoning."
        ),
        llm=llm,
        verbose=True,
    )

    explain_task = Task(
        description="Explain what OpenTelemetry is and why it matters for AI agents in 2-3 sentences.",
        expected_output="A concise explanation of OpenTelemetry's relevance to AI agents.",
        agent=analyst,
    )

    compare_task = Task(
        description=(
            "Compare trace-based evaluation vs re-execution-based evaluation "
            "for AI agents. Give pros and cons of each in a few bullet points."
        ),
        expected_output="A short comparison of trace-based vs re-execution evaluation approaches.",
        agent=analyst,
    )

    recommend_task = Task(
        description=(
            "Based on your previous analysis, recommend when a team should "
            "adopt trace-based agent evaluation. Keep it to 2-3 sentences."
        ),
        expected_output="A brief recommendation on when to adopt trace-based evaluation.",
        agent=analyst,
    )

    crew = Crew(
        agents=[analyst],
        tasks=[explain_task, compare_task, recommend_task],
        process=Process.sequential,
        verbose=True,
    )

    return crew
