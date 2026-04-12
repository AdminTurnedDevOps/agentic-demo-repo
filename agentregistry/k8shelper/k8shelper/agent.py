import random
import os

from google.adk import Agent
from google.adk.tools.tool_context import ToolContext

from .mcp_tools import get_mcp_tools
from .prompts_loader import build_instruction

# Initialize OpenTelemetry
# Set service name from environment variable for OpenTelemetry
os.environ.setdefault('OTEL_SERVICE_NAME', 'k8shelper')

from google.adk.telemetry.setup import maybe_set_otel_providers
maybe_set_otel_providers()


def roll_die(sides: int, tool_context: ToolContext) -> int:
    """Roll a die and record the outcome for later reference."""
    result = random.randint(1, sides)
    if "rolls" not in tool_context.state:
        tool_context.state["rolls"] = []

    tool_context.state["rolls"] = tool_context.state["rolls"] + [result]
    return result


async def check_prime(nums: list[int]) -> str:
    """Check whether the provided numbers are prime."""
    primes = set()
    for number in nums:
        number = int(number)
        if number <= 1:
            continue
        is_prime = True
        for i in range(2, int(number**0.5) + 1):
            if number % i == 0:
                is_prime = False
                break
        if is_prime:
            primes.add(number)
    return "No prime numbers found." if not primes else f"{', '.join(str(num) for num in primes)} are prime numbers."


def create_model():
    """Use a Gemini model."""
    return "gemini-2.0-flash"


mcp_tools = get_mcp_tools()
root_agent = Agent(
    model=create_model(),
    name="k8shelper_agent",
    description="k8shelper agent.",
    instruction=build_instruction("""
You roll dice and answer questions about the outcome of the dice rolls.
You can roll dice of different sizes.
You can use multiple tools in parallel by calling functions in parallel (in one request and in one round).
It is ok to discuss previous dice roles, and comment on the dice rolls.
When you are asked to roll a die, you must call the roll_die tool with the number of sides. Be sure to pass in an integer. Do not pass in a string.
You should never roll a die on your own.
When checking prime numbers, call the check_prime tool with a list of integers. Be sure to pass in a list of integers. You should never pass in a string.
You should not check prime numbers before calling the tool.
When you are asked to roll a die and check prime numbers, you should always make the following two function calls:
1. You should first call the roll_die tool to get a roll. Wait for the function response before calling the check_prime tool.
2. After you get the function response from roll_die tool, you should call the check_prime tool with the roll_die result.
2.1 If user asks you to check primes based on previous rolls, make sure you include the previous rolls in the list.
3. When you respond, you must include the roll_die result from step 1.
You should always perform the previous 3 steps when asking for a roll and checking prime numbers.
You should not rely on the previous history on prime results.


    """),
    tools=[
        roll_die,
        check_prime,
    ] + (mcp_tools if mcp_tools else []),
)

