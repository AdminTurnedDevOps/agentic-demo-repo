import random
import os

from google.adk import Agent
from google.adk.models.lite_llm import LiteLlm
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


def list_available_tools() -> dict:
    """List the local tools and GitHub MCP tool categories available to this agent."""
    return {
        "local_tools": [
            {
                "name": "roll_die",
                "description": "Roll a die with a specified number of sides.",
            },
            {
                "name": "check_prime",
                "description": "Check whether a list of numbers are prime.",
            },
            {
                "name": "list_available_tools",
                "description": "List local and MCP-backed tool capabilities.",
            },
        ],
        "github_mcp_tools": {
            "repository": [
                "search_repositories",
                "create_repository",
                "fork_repository",
                "get_file_contents",
                "create_or_update_file",
                "delete_file",
                "push_files",
            ],
            "branches_commits_releases": [
                "list_branches",
                "create_branch",
                "list_commits",
                "get_commit",
                "list_tags",
                "get_tag",
                "list_releases",
                "get_latest_release",
                "get_release_by_tag",
            ],
            "issues": [
                "list_issues",
                "search_issues",
                "issue_read",
                "add_issue_comment",
                "add_reply_to_pull_request_comment",
                "list_issue_fields",
                "list_issue_types",
                "sub_issue_write",
            ],
            "pull_requests": [
                "list_pull_requests",
                "search_pull_requests",
                "pull_request_read",
                "create_pull_request",
                "update_pull_request",
                "update_pull_request_branch",
                "merge_pull_request",
                "pull_request_review_write",
                "add_comment_to_pending_review",
                "request_copilot_review",
            ],
            "copilot": [
                "assign_copilot_to_issue",
                "create_pull_request_with_copilot",
                "get_copilot_job_status",
            ],
            "search_and_identity": [
                "search_code",
                "search_commits",
                "search_users",
                "get_me",
                "get_label",
                "get_team_members",
                "get_teams",
                "list_repository_collaborators",
                "run_secret_scanning",
            ],
            "disabled_by_default": [
                "issue_write",
            ],
        },
    }


def create_model():
    """Return the configured model.

    Anthropic must go through LiteLLM so ADK calls Anthropic directly with
    ANTHROPIC_API_KEY instead of treating Claude model names as Vertex models.
    """
    provider = os.getenv("MODEL_PROVIDER", "anthropic").lower()
    if provider == "anthropic":
        model_name = os.getenv("MODEL_NAME", "claude-sonnet-4-6")
        if not model_name.startswith("anthropic/"):
            model_name = f"anthropic/{model_name}"
        return LiteLlm(model=model_name)

    return os.getenv("MODEL_NAME", "gemini-3.5-flash")


mcp_tools = get_mcp_tools()
root_agent = Agent(
    model=create_model(),
    name="k8shelper_agent",
    description="k8shelper agent.",
    instruction=build_instruction("""
You are k8shelper, a Kubernetes demo agent with local dice/math tools and GitHub Copilot MCP tools.
When the user asks what tools you have access to, call list_available_tools and summarize the local tools and GitHub MCP tool categories.
You can use GitHub MCP tools for repositories, files, branches, commits, releases, issues, pull requests, code search, users, teams, collaborators, secret scanning, and GitHub Copilot coding-agent tasks.
The issue_write GitHub MCP tool is disabled by default because its schema is not compatible with the current model's function/tool-calling schema conversion.

You can also roll dice and answer questions about the outcome of the dice rolls.
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
        list_available_tools,
    ] + (mcp_tools if mcp_tools else []),
)
