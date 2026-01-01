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
   - **Application Type:** Native (required for device code flow)
3. Click **Create**
4. In the **Settings** tab:
   - Scroll down to **Advanced Settings** and expand it
   - Click on the **Grant Types** tab
   - Enable the **Device Code** checkbox
   - Click **Save Changes** at the bottom
5. Note your **Client ID** from the Settings tab (you'll need this for testing)

## Step 3: Configure Custom Claims (Roles)

Auth0 requires custom claims to be namespaced.

1. Go to: **Actions > Library** (or **Actions > Custom**)
2. Click **Build Custom** (or **Create Action** button)
3. Choose **Create Custom Action**
4. Select the trigger: **Login / Post Login**
5. Name it: `Add Roles to Token`
6. Replace the code with:

```javascript
exports.onExecutePostLogin = async (event, api) => {
  const namespace = 'https://mcp-demo';

  if (event.authorization) {
    const roles = event.user.app_metadata?.roles || ['user'];
    api.accessToken.setCustomClaim(`${namespace}/roles`, roles);
  }
};
```

7. Click **Deploy**
8. Go to: **Actions > Triggers**
9. Click on the **Post-Login** trigger
10. Drag your custom action from the right sidebar into the flow (between Start and Complete)
11. Click **Apply**

### Assign Roles to Users

1. Go to: **User Management > Users**
2. Select a user
3. Go to the **Metadata** tab
4. In `app_metadata`, add:
   - For admin: `{"roles": ["admin"]}`
   - For regular user: `{"roles": ["user"]}`