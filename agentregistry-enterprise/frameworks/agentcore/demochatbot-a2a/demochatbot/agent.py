import logging
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.genai import types

try:
    from typing import override
except ImportError:
    from typing_extensions import override


logger = logging.getLogger(__name__)


class DemoChatbotAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="demochatbot",
            description="A deterministic demo chatbot for AgentRegistry Enterprise AgentCore deployments.",
        )

    @override
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        session = ctx.session
        text = (
            "demochatbot is running on AWS AgentCore through AgentRegistry Enterprise. "
            f"Session: {session.id}."
        )

        logger.info("Generating demochatbot response for session %s", session.id)

        yield Event(
            id=Event.new_id(),
            invocation_id=ctx.invocation_id,
            author=ctx.agent.name,
            branch=ctx.branch,
            content=types.ModelContent(parts=[types.Part.from_text(text=text)]),
        )


root_agent = DemoChatbotAgent()
