# Microsoft Entra ID Setup Instructions

## Step 1: Create App Registration

1. Go to the [Azure Portal](https://portal.azure.com)
2. Navigate to: **Microsoft Entra ID > App registrations > New registration**
3. Configure:
   - **Name:** mcp-oauth-demo
   - **Supported account types:** Single tenant (or as needed)
   - **Redirect URI:** Leave blank for now
4. Click **Register**
5. Note your **Application (client) ID** and **Directory (tenant) ID**

## Step 2: Configure API Scopes

1. In your app registration, go to: **Expose an API**
2. Click **Add a scope** and create:

**Scope 1:**
- Scope name: `files.read`
- Who can consent: Admins and users
- Admin consent display name: Read files
- Admin consent description: Allows reading files
- State: Enabled

**Scope 2:**
- Scope name: `files.delete`
- Who can consent: Admins only
- Admin consent display name: Delete files
- Admin consent description: Allows deleting files
- State: Enabled

## Step 3: Configure App Roles

1. In your app registration, go to: **App roles**
2. Click **Create app role** and create:

**Role 1:**
- Display name: Admin
- Allowed member types: Users/Groups
- Value: `admin`
- Description: Administrator role with full access
- Enable this app role: Yes

**Role 2:**
- Display name: User
- Allowed member types: Users/Groups
- Value: `user`
- Description: Standard user role
- Enable this app role: Yes

## Step 4: Assign Roles to Users

1. Go to: **Enterprise applications > Your app > Users and groups**
2. Click **Add user/group**
3. Select users and assign them roles

## Step 5: Update Kubernetes Manifests

Edit `k8s/gloo-traffic-policy.yaml` and replace:
- `{TENANT_ID}` with your Directory (tenant) ID
- `{CLIENT_ID}` with your Application (client) ID
