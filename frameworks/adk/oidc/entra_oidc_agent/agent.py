"""
ADK Agent with Microsoft Entra ID OIDC Authentication.

Demonstrates using Entra ID as an OIDC provider with Google ADK's
authentication system. The agent authenticates via Entra and calls
Microsoft Graph API to retrieve user profile information.
"""

import os

import requests
from fastapi.openapi.models import (
    OAuth2,
    OAuthFlowAuthorizationCode,
    OAuthFlows,
)
from google.adk.agents import LlmAgent
from google.adk.auth import AuthConfig, AuthCredential, AuthCredentialTypes, OAuth2Auth
from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

# ---------------------------------------------------------------------------
# Entra ID configuration
# ---------------------------------------------------------------------------
TENANT_ID = os.getenv("AZURE_TENANT_ID", "your-tenant-id")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "your-client-id")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "your-client-secret")

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_CACHE_KEY = "entra_oidc_tokens"

# ---------------------------------------------------------------------------
# Auth scheme — points ADK at the Entra ID OAuth2/OIDC endpoints
# ---------------------------------------------------------------------------
auth_scheme = OAuth2(
    flows=OAuthFlows(
        authorizationCode=OAuthFlowAuthorizationCode(
            authorizationUrl=(
                f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/authorize"
            ),
            tokenUrl=(
                f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
            ),
            scopes={
                "openid": "OpenID Connect sign-in",
                "profile": "View basic profile",
                "User.Read": "Read signed-in user profile",
            },
        )
    )
)

# ---------------------------------------------------------------------------
# Auth credential — client credentials from the Entra app registration
# ---------------------------------------------------------------------------
auth_credential = AuthCredential(
    auth_type=AuthCredentialTypes.OPEN_ID_CONNECT,
    oauth2=OAuth2Auth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    ),
)

auth_config = AuthConfig(
    auth_scheme=auth_scheme,
    raw_auth_credential=auth_credential,
)


# ---------------------------------------------------------------------------
# Tool: get_my_profile
# ---------------------------------------------------------------------------
def get_my_profile(tool_context: ToolContext) -> dict:
    """Retrieve the authenticated user's profile from Microsoft Graph API."""

    # 1. Check for a cached token from a previous call in this session.
    access_token = (tool_context.state.get(TOKEN_CACHE_KEY) or {}).get("access_token")

    # 2. Check whether ADK just completed the OIDC exchange (post-redirect).
    if not access_token:
        exchanged = tool_context.get_auth_response(auth_config)
        if exchanged and exchanged.oauth2:
            access_token = exchanged.oauth2.access_token
            tool_context.state[TOKEN_CACHE_KEY] = {"access_token": access_token}

    # 3. No token yet — kick off the OIDC login flow.
    if not access_token:
        tool_context.request_credential(auth_config)
        return {"status": "pending", "message": "Awaiting Entra ID sign-in."}

    # 4. Call Microsoft Graph /me with the access token.
    try:
        resp = requests.get(
            f"{GRAPH_API_BASE}/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        profile = resp.json()
        return {
            "status": "success",
            "displayName": profile.get("displayName"),
            "mail": profile.get("mail"),
            "jobTitle": profile.get("jobTitle"),
            "officeLocation": profile.get("officeLocation"),
            "userPrincipalName": profile.get("userPrincipalName"),
        }
    except requests.RequestException as e:
        return {"status": "error", "message": f"Graph API call failed: {e}"}


get_profile_tool = FunctionTool(func=get_my_profile)

# ---------------------------------------------------------------------------
# Root agent
# ---------------------------------------------------------------------------
root_agent = LlmAgent(
    model="gemini-2.0-flash",
    name="entra_oidc_agent",
    description=(
        "An agent that authenticates with Microsoft Entra ID via OIDC "
        "and queries Microsoft Graph API."
    ),
    instruction=(
        "You are a helpful assistant that retrieves user profile information "
        "from Microsoft Entra ID using the Microsoft Graph API.\n\n"
        "When the user asks about their profile, identity, or account info, "
        "use the get_my_profile tool. If authentication is required, let the "
        "user know they will be redirected to sign in.\n\n"
        "Present profile information in a clear, readable format."
    ),
    tools=[get_profile_tool],
)
