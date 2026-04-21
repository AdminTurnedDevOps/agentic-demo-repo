import os
from strands.models.anthropic import AnthropicModel
from dotenv import load_dotenv
from bedrock_agentcore.identity.auth import requires_api_key

@requires_api_key(provider_name=os.getenv("BEDROCK_AGENTCORE_MODEL_PROVIDER_API_KEY_NAME", ""))
def agentcore_identity_api_key_provider(api_key: str) -> str:
    return api_key

def _get_api_key() -> str:
    """Provide API key"""
    if os.getenv("LOCAL_DEV") == "1":
        load_dotenv(".env.local")
        return os.getenv("ANTHROPIC_API_KEY")
    else:
        return agentcore_identity_api_key_provider()

def load_model() -> AnthropicModel:
    """
    Get authenticated Anthropic model client.
    """
    return AnthropicModel(
        client_args={"api_key": _get_api_key()},
        model_id="claude-sonnet-4-5-20250929",
        max_tokens=5000
    )