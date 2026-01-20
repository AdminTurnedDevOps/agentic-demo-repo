#!/usr/bin/env python3
"""
AI Technical Lead Slack Bot

A Slack bot that connects to the kagent AI Technical Lead agent via A2A protocol.
Users can interact with the agent through slash commands or mentions.

Usage:
    /techlead <question or command>
    @TechLead <question or command>

Examples:
    /techlead What alerts are currently firing?
    /techlead Investigate high CPU usage on the payment service
    /techlead Create a ticket for the database connection issues
    @TechLead What's the cluster status?
"""

import os
import logging
import json
import httpx
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Environment variables
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
KAGENT_A2A_URL = os.environ.get(
    "KAGENT_A2A_URL",
    "http://kagent-controller.kagent:8083/api/a2a/kagent/ai-tech-lead/"
)

# Validate required environment variables
if not SLACK_BOT_TOKEN:
    raise ValueError("SLACK_BOT_TOKEN environment variable is required")
if not SLACK_APP_TOKEN:
    raise ValueError("SLACK_APP_TOKEN environment variable is required")

# Initialize the Slack app
app = App(token=SLACK_BOT_TOKEN)


class A2AClient:
    """Client for communicating with kagent via A2A protocol."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=120.0)  # 2 minute timeout for agent responses

    def invoke(self, message: str, skill_id: str = None) -> dict:
        """
        Invoke the kagent agent with a message.

        Args:
            message: The user's message/question
            skill_id: Optional skill ID to invoke specifically

        Returns:
            dict with 'response' key containing agent's response
        """
        payload = {
            "message": message
        }
        if skill_id:
            payload["skill_id"] = skill_id

        try:
            response = self.client.post(
                f"{self.base_url}invoke",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from kagent: {e.response.status_code} - {e.response.text}")
            return {"error": f"Failed to reach AI Tech Lead: {e.response.status_code}"}
        except httpx.RequestError as e:
            logger.error(f"Request error to kagent: {e}")
            return {"error": f"Connection error to AI Tech Lead: {str(e)}"}

    def get_skills(self) -> list:
        """Get available skills from the agent."""
        try:
            response = self.client.get(f"{self.base_url}skills")
            response.raise_for_status()
            return response.json().get("skills", [])
        except Exception as e:
            logger.error(f"Failed to get skills: {e}")
            return []


# Initialize A2A client
a2a_client = A2AClient(KAGENT_A2A_URL)


def format_response_for_slack(response: dict) -> list:
    """
    Format the agent's response for Slack display.

    Returns a list of Slack blocks for rich formatting.
    """
    if "error" in response:
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":warning: *Error*\n{response['error']}"
                }
            }
        ]

    agent_response = response.get("response", "No response from agent")

    # Split long responses into multiple blocks if needed
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": agent_response[:3000]  # Slack block text limit
            }
        }
    ]

    # Add continuation blocks for long responses
    if len(agent_response) > 3000:
        remaining = agent_response[3000:]
        while remaining:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": remaining[:3000]
                }
            })
            remaining = remaining[3000:]

    return blocks


@app.command("/techlead")
def handle_techlead_command(ack, respond, command):
    """Handle the /techlead slash command."""
    ack()  # Acknowledge the command immediately

    user = command["user_name"]
    text = command.get("text", "").strip()

    if not text:
        respond(
            text="Please provide a question or command. Examples:\n"
                 "• `/techlead What alerts are firing?`\n"
                 "• `/techlead Investigate high error rate on api-gateway`\n"
                 "• `/techlead Create a ticket for the memory issues`"
        )
        return

    logger.info(f"User {user} invoked /techlead: {text}")

    # Send a "thinking" message
    respond(text=f":robot_face: AI Tech Lead is analyzing your request...")

    # Invoke the agent
    result = a2a_client.invoke(text)

    # Format and send the response
    blocks = format_response_for_slack(result)
    respond(blocks=blocks, replace_original=True)


@app.event("app_mention")
def handle_mention(event, say):
    """Handle @TechLead mentions in channels."""
    user = event.get("user")
    text = event.get("text", "")

    # Remove the bot mention from the text
    # Format is typically "<@BOTID> message"
    import re
    clean_text = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()

    if not clean_text:
        say(
            text="Hi! I'm the AI Technical Lead. How can I help you?\n\n"
                 "You can ask me things like:\n"
                 "• What's the current cluster status?\n"
                 "• Are there any alerts firing?\n"
                 "• Investigate the latency spike on checkout-service\n"
                 "• Create a ticket for the database connection issues",
            thread_ts=event.get("ts")
        )
        return

    logger.info(f"User {user} mentioned bot: {clean_text}")

    # Send a "thinking" message in thread
    say(
        text=":robot_face: Analyzing...",
        thread_ts=event.get("ts")
    )

    # Invoke the agent
    result = a2a_client.invoke(clean_text)

    # Format and send the response
    blocks = format_response_for_slack(result)
    say(blocks=blocks, thread_ts=event.get("ts"))


@app.event("message")
def handle_dm(event, say):
    """Handle direct messages to the bot."""
    # Ignore messages from bots (including ourselves)
    if event.get("bot_id"):
        return

    # Only handle DMs (channel type 'im')
    if event.get("channel_type") != "im":
        return

    user = event.get("user")
    text = event.get("text", "").strip()

    if not text:
        return

    logger.info(f"User {user} sent DM: {text}")

    # Send a "thinking" message
    say(text=":robot_face: Analyzing...")

    # Invoke the agent
    result = a2a_client.invoke(text)

    # Format and send the response
    blocks = format_response_for_slack(result)
    say(blocks=blocks)


@app.command("/techlead-skills")
def handle_skills_command(ack, respond):
    """List available skills from the AI Tech Lead."""
    ack()

    skills = a2a_client.get_skills()

    if not skills:
        respond(text="Unable to retrieve skills from AI Tech Lead.")
        return

    skill_text = "*Available AI Tech Lead Skills:*\n\n"
    for skill in skills:
        skill_text += f"• *{skill.get('name', 'Unknown')}* (`{skill.get('id', '')}`)\n"
        skill_text += f"  {skill.get('description', 'No description')}\n\n"

    respond(text=skill_text)


def main():
    """Main entry point."""
    logger.info("Starting AI Technical Lead Slack Bot...")
    logger.info(f"kagent A2A URL: {KAGENT_A2A_URL}")

    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()


if __name__ == "__main__":
    main()
