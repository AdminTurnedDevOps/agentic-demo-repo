#!/bin/bash

# Setup script for Auth0 OAuth demo
# This script guides you through configuring Auth0 for the MCP OAuth demo

set -e

echo "========================================="
echo "MCP OAuth Demo - Auth0 Setup"
echo "========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}This script will help you configure Auth0 for the MCP OAuth demo.${NC}"
echo ""

# Step 1: Instructions for creating the API
echo "========================================="
echo "Step 1: Create API in Auth0"
echo "========================================="
echo ""
echo "1. Go to the Auth0 Dashboard: https://manage.auth0.com"
echo "2. Navigate to: Applications > APIs > Create API"
echo "3. Configure the API:"
echo "   - Name: MCP OAuth Demo API"
echo "   - Identifier: https://mcp-oauth-demo (or your choice - this is the 'audience')"
echo "   - Signing Algorithm: RS256"
echo "4. Click 'Create'"
echo ""
echo "5. In the API settings, go to: Permissions (Scopes)"
echo "6. Add these scopes:"
echo "   - files:read - Read files from the system"
echo "   - files:delete - Delete files from the system"
echo ""
read -p "Press Enter when you've created the API and scopes..."

# Step 2: Get Auth0 Domain and API Identifier
echo ""
echo "========================================="
echo "Step 2: Provide Configuration Values"
echo "========================================="
echo ""

read -p "Enter your Auth0 Domain (e.g., your-tenant.us.auth0.com): " AUTH0_DOMAIN
read -p "Enter your API Identifier (e.g., https://mcp-oauth-demo): " API_IDENTIFIER

echo ""
echo -e "${GREEN}Configuration values received:${NC}"
echo "  Auth0 Domain: $AUTH0_DOMAIN"
echo "  API Identifier: $API_IDENTIFIER"
echo ""

# Step 3: Instructions for creating the application
echo "========================================="
echo "Step 3: Create Application in Auth0"
echo "========================================="
echo ""
echo "You need to create an application for testing:"
echo ""
echo "1. In Auth0 Dashboard, go to: Applications > Applications > Create Application"
echo "2. Configure the application:"
echo "   - Name: MCP OAuth Test Client"
echo "   - Application Type: Choose based on your test client:"
echo "     * Single Page Application (for browser-based testing)"
echo "     * Machine to Machine (for backend/CLI testing)"
echo "     * Regular Web Application (for server-side apps)"
echo "3. Click 'Create'"
echo ""
echo "4. In the application settings:"
echo "   - Note the Client ID (you'll need this for testing)"
echo "   - If you chose 'Machine to Machine', authorize it for your API"
echo "   - Configure Allowed Callback URLs if using browser-based auth"
echo ""
read -p "Press Enter when you've created the application..."

echo ""
read -p "Enter your Application Client ID: " CLIENT_ID

# Step 4: Instructions for configuring custom claims (roles)
echo ""
echo "========================================="
echo "Step 4: Configure Custom Claims (Roles)"
echo "========================================="
echo ""
echo "Auth0 requires custom claims to be namespaced. We'll add a 'roles' claim."
echo ""
echo "1. In Auth0 Dashboard, go to: Actions > Flows > Login"
echo "2. Click the '+' icon to add a custom action"
echo "3. Choose 'Build from scratch'"
echo "4. Name it: 'Add Roles to Token'"
echo "5. Replace the code with:"
echo ""
echo "-----------------------------------------------------------"
cat << 'EOF'
exports.onExecutePostLogin = async (event, api) => {
  const namespace = 'https://mcp-demo';

  // Add user roles to the access token
  if (event.authorization) {
    // You can add roles from user metadata, app metadata, or hardcode for testing
    // Example: Get from user metadata
    const roles = event.user.app_metadata?.roles || ['user'];

    // Add the roles claim to the access token
    api.accessToken.setCustomClaim(`${namespace}/roles`, roles);
  }
};
EOF
echo "-----------------------------------------------------------"
echo ""
echo "6. Click 'Deploy'"
echo "7. Go back to: Actions > Flows > Login"
echo "8. Drag your 'Add Roles to Token' action into the flow"
echo "9. Click 'Apply'"
echo ""
echo "To assign roles to users for testing:"
echo "1. Go to: User Management > Users"
echo "2. Select a user"
echo "3. Go to the 'Metadata' tab"
echo "4. In 'app_metadata', add:"
echo '   {"roles": ["admin"]}  // for admin users'
echo '   {"roles": ["user"]}   // for regular users'
echo ""
read -p "Press Enter when you've configured the custom claims..."

# Step 5: Update Kubernetes manifests
echo ""
echo "========================================="
echo "Step 5: Update Kubernetes Manifests"
echo "========================================="
echo ""

K8S_DIR="$(dirname "$0")/k8s"
POLICY_FILE="$K8S_DIR/gloo-traffic-policy.yaml"

if [ -f "$POLICY_FILE" ]; then
    echo "Updating $POLICY_FILE with your configuration..."

    # Create a backup
    cp "$POLICY_FILE" "$POLICY_FILE.backup"

    # Replace placeholders with actual values
    sed -i.tmp "s|{AUTH0_DOMAIN}|$AUTH0_DOMAIN|g" "$POLICY_FILE"
    sed -i.tmp "s|{API_IDENTIFIER}|$API_IDENTIFIER|g" "$POLICY_FILE"
    rm -f "$POLICY_FILE.tmp"

    echo -e "${GREEN}✓ Updated $POLICY_FILE${NC}"
else
    echo -e "${RED}Error: $POLICY_FILE not found${NC}"
    exit 1
fi

# Step 6: Optional - Create secrets
echo ""
echo "========================================="
echo "Step 6: Create Kubernetes Secrets (Optional)"
echo "========================================="
echo ""
echo "If your test clients need a client secret:"
echo "1. In your application settings, find the 'Client Secret'"
echo "2. Copy the secret value"
echo ""
read -p "Do you want to create a Kubernetes secret with these values? (y/n): " CREATE_SECRET

if [[ "$CREATE_SECRET" =~ ^[Yy]$ ]]; then
    read -s -p "Enter your client secret (input hidden): " CLIENT_SECRET
    echo ""

    # Create secrets.yaml from template
    SECRETS_FILE="$K8S_DIR/secrets.yaml"
    cp "$K8S_DIR/secrets.yaml.template" "$SECRETS_FILE"

    sed -i.tmp "s/YOUR_AUTH0_DOMAIN/$AUTH0_DOMAIN/g" "$SECRETS_FILE"
    sed -i.tmp "s|YOUR_API_IDENTIFIER|$API_IDENTIFIER|g" "$SECRETS_FILE"
    sed -i.tmp "s/YOUR_CLIENT_ID/$CLIENT_ID/g" "$SECRETS_FILE"
    sed -i.tmp "s/YOUR_CLIENT_SECRET/$CLIENT_SECRET/g" "$SECRETS_FILE"
    rm -f "$SECRETS_FILE.tmp"

    echo -e "${GREEN}✓ Created $SECRETS_FILE${NC}"
    echo -e "${YELLOW}⚠ WARNING: This file contains sensitive data. Do not commit it to version control.${NC}"
fi

# Step 7: Summary and next steps
echo ""
echo "========================================="
echo "Setup Complete!"
echo "========================================="
echo ""
echo -e "${GREEN}Your Auth0 configuration is ready!${NC}"
echo ""
echo "Next steps:"
echo ""
echo "1. Build the MCP server Docker image:"
echo "   cd ../shared/mcp-server"
echo "   docker build -t mcp-oauth-demo:latest ."
echo ""
echo "2. If using a local Kubernetes cluster (minikube/kind), load the image:"
echo "   # For minikube:"
echo "   minikube image load mcp-oauth-demo:latest"
echo "   # For kind:"
echo "   kind load docker-image mcp-oauth-demo:latest"
echo ""
echo "3. Deploy to Kubernetes:"
echo "   kubectl apply -k k8s/"
echo ""
echo "4. Verify the deployment:"
echo "   kubectl get pods -n mcp-demo-auth0"
echo "   kubectl get gateway,mcptarget,glootrafficpolicy -n mcp-demo-auth0"
echo ""
echo "5. Test the setup:"
echo "   kubectl port-forward svc/mcp-gateway 3000:3000 -n mcp-demo-auth0"
echo "   # Then use the test client scripts to test with tokens"
echo ""
echo "For detailed instructions, see the README.md file."
echo ""
