# Auth0 Setup Instructions

## Step 1: Create API in Auth0

1. Go to the [Auth0 Dashboard](https://manage.auth0.com)
2. Navigate to: **Applications > APIs > Create API**
3. Configure the API:
   - **Name:** MCP OAuth Demo API
   - **Identifier:** `https://mcp-oauth-demo` (this is the "audience")
   - **Signing Algorithm:** RS256
4. Click **Create**
5. Go to the **Permissions** tab and add these scopes:
   - `files:read` - Read files from the system
   - `files:delete` - Delete files from the system

## Step 2: Create Application

1. Go to: **Applications > Applications > Create Application**
2. Configure:
   - **Name:** MCP OAuth Test Client
   - **Application Type:** Machine to Machine (for CLI testing)
3. Click **Create**
4. If Machine to Machine, authorize it for your API and select the scopes
5. Note your **Client ID** and **Client Secret**

## Step 3: Configure Custom Claims (Roles)

Auth0 requires custom claims to be namespaced.

1. Go to: **Actions > Flows > Login**
2. Click **+** and choose **Build from scratch**
3. Name it: `Add Roles to Token`
4. Replace the code with:

```javascript
exports.onExecutePostLogin = async (event, api) => {
  const namespace = 'https://mcp-demo';

  if (event.authorization) {
    const roles = event.user.app_metadata?.roles || ['user'];
    api.accessToken.setCustomClaim(`${namespace}/roles`, roles);
  }
};
```

5. Click **Deploy**
6. Go back to **Actions > Flows > Login**
7. Drag your action into the flow between Start and Complete
8. Click **Apply**

### Assign Roles to Users

1. Go to: **User Management > Users**
2. Select a user
3. Go to the **Metadata** tab
4. In `app_metadata`, add:
   - For admin: `{"roles": ["admin"]}`
   - For regular user: `{"roles": ["user"]}`

## Step 4: Update Kubernetes Manifests

Edit `k8s/gloo-traffic-policy.yaml` and replace:
- `{AUTH0_DOMAIN}` with your Auth0 domain (e.g., `your-tenant.us.auth0.com`)
- `{API_IDENTIFIER}` with your API identifier (e.g., `https://mcp-oauth-demo`)
