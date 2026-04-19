import os

from strands.models.openai import OpenAIModel
from bedrock_agentcore.identity.auth import requires_api_key

IDENTITY_PROVIDER_NAME = "testagwAnthropic"
IDENTITY_ENV_VAR = "AGENTCORE_CREDENTIAL_TESTAGWANTHROPIC"
GATEWAY_URL = "http://20.245.132.78:8082/anthropic"


@requires_api_key(provider_name=IDENTITY_PROVIDER_NAME)
def _agentcore_identity_api_key_provider(api_key: str) -> str:
    """Fetch API key from AgentCore Identity."""
    return api_key


def _get_api_key() -> str:
    """
    Uses AgentCore Identity for API key management in deployed environments.
    For local development, run via 'agentcore dev' which loads agentcore/.env.
    """
    if os.getenv("LOCAL_DEV") == "1":
        api_key = os.getenv(IDENTITY_ENV_VAR)
        if not api_key:
            raise RuntimeError(
                f"{IDENTITY_ENV_VAR} not found. Add {IDENTITY_ENV_VAR}=your-key to .env.local"
            )
        return api_key
    return _agentcore_identity_api_key_provider()


def load_model() -> OpenAIModel:
    """Get an OpenAI-compatible model client routed through agentgateway."""
    return OpenAIModel(
        client_args={
            "api_key": _get_api_key(),
            "base_url": GATEWAY_URL,
            "default_headers": {
                "anthropic-version": "2023-06-01",
            },
        },
        model_id="claude-sonnet-4-5-20250929",
        params={"max_tokens": 5000},
    )
