# ADK + Microsoft Entra ID OIDC Authentication

This example shows how to authenticate an ADK agent with Microsoft Entra ID
(formerly Azure AD) using OpenID Connect, then call the Microsoft Graph API
to retrieve the signed-in user's profile.

## Architecture

```
User ─► ADK Agent ─► get_my_profile tool
                         │
                         ├─ 1. No token? → request_credential() → Entra login redirect
                         ├─ 2. Post-redirect? → get_auth_response() → extract access_token
                         └─ 3. Has token → GET https://graph.microsoft.com/v1.0/me
```

## Prerequisites

- Python 3.10+
- A Microsoft Entra ID (Azure AD) tenant
- `google-adk` and `requests` installed

## Step 1: Register an App in Entra ID

1. Go to the [Azure Portal → App registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
2. Click **New registration**
3. Configure:
   - **Name**: `adk-oidc-demo` (or whatever you like)
   - **Supported account types**: Choose based on your needs (single tenant is fine for testing)
   - **Redirect URI**: Select **Web** and enter `http://localhost:8000/dev-ui/`
     (this is the default ADK dev UI redirect URI — note the trailing slash)
4. Click **Register**

## Step 2: Create a Client Secret

1. In your new app registration, go to **Certificates & secrets**
2. Click **New client secret**
3. Add a description and choose an expiry
4. Copy the **Value** immediately (it won't be shown again)

## Step 3: Configure API Permissions

1. Go to **API permissions**
2. Click **Add a permission → Microsoft Graph → Delegated permissions**
3. Add these permissions:
   - `openid`
   - `profile`
   - `User.Read`
4. Click **Grant admin consent** if you have admin privileges (optional but avoids per-user consent prompts)

## Step 4: Note Your IDs

From the app registration **Overview** page, copy:
- **Application (client) ID** → `AZURE_CLIENT_ID`
- **Directory (tenant) ID** → `AZURE_TENANT_ID`
- The client secret from Step 2 → `AZURE_CLIENT_SECRET`

## Step 5: Set Environment Variables

```bash
cd frameworks/adk/oidc/entra_oidc_agent

# Copy the template and fill in your values
cp .env.example .env
```

Edit `.env`:
```
AZURE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_SECRET=your-client-secret-value
GOOGLE_API_KEY=your-google-api-key
```

## Step 6: Run the Agent

From the `frameworks/adk/oidc` directory:

```bash
# Install dependencies if not already installed
pip install google-adk requests

# Launch the ADK dev UI
adk web
```

The dev UI will start at `http://localhost:8000`. Select `entra_oidc_agent`
from the agent dropdown.

## Step 7: Test It

1. In the dev UI chat, type: **"What is my profile?"**
2. The agent will invoke `get_my_profile`
3. Since there's no token yet, ADK will redirect you to the Entra ID login page
4. Sign in with your Microsoft account
5. After consent, you'll be redirected back to the dev UI
6. The agent will call Microsoft Graph `/me` and display your profile info

## How It Works

The auth flow uses ADK's built-in credential exchange mechanism:

| Step | What happens | ADK API |
|------|-------------|---------|
| 1 | Tool checks for cached token in session state | `tool_context.state.get()` |
| 2 | If no token, checks if ADK just completed an OIDC exchange | `tool_context.get_auth_response()` |
| 3 | If still no token, triggers the login redirect | `tool_context.request_credential()` |
| 4 | After auth, uses the access token to call Graph API | Standard HTTP call |

Key configuration:
- **`auth_scheme`** (OAuth2): Points to the Entra `/authorize` and `/token` endpoints with `openid`, `profile`, and `User.Read` scopes
- **`auth_credential`** (OPEN_ID_CONNECT): Carries the client ID and secret from the Entra app registration
- **`TOKEN_CACHE_KEY`**: Caches the access token in ADK session state so subsequent tool calls don't re-authenticate

## Known Limitation

There is an open ADK issue ([google/adk-python#779](https://github.com/google/adk-python/issues/779))
where the dev UI frontend does not fully handle the OAuth callback for
**non-Google** identity providers. The FastAPI server receives the redirect
with `code` and `state` query parameters at `/dev-ui/`, but the frontend
JavaScript may not automatically parse and complete the token exchange for
third-party providers like Entra ID. Google Workspace OAuth (Gmail, Calendar,
etc.) works correctly.

If you hit this, you can work around it by:
1. Running the agent programmatically with `runner.run_async()` and handling
   the redirect/callback yourself (see the ADK auth docs for the full
   client-side flow).
2. Watching the ADK repo for a fix to issue #779.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `AADSTS50011: The redirect URI does not match` | Ensure `http://localhost:8000/dev-ui/` (with trailing slash) is registered in Entra under **Redirect URIs** |
| `AADSTS700016: Application not found` | Double-check `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` |
| `AADSTS7000218: Invalid client secret` | Regenerate the secret in Entra and update `.env` |
| Graph API returns `401` | Token may have expired; restart the session to re-authenticate |
| `openid` scope error | Ensure the delegated permissions are granted in the Entra portal |
