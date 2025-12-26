#!/bin/bash

# Setup script for Microsoft Entra ID OAuth demo
# This script guides you through configuring Entra ID for the MCP OAuth demo

set -e

echo "========================================="
echo "MCP OAuth Demo - Entra ID Setup"
echo "========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}This script will help you configure Microsoft Entra ID for the MCP OAuth demo.${NC}"
echo ""

# Step 1: Instructions for creating the app registration
echo "========================================="
echo "Step 1: Create App Registration in Azure"
echo "========================================="
echo ""
echo "1. Go to the Azure Portal: https://portal.azure.com"
echo "2. Navigate to: Microsoft Entra ID > App registrations > New registration"
echo "3. Configure the application:"
echo "   - Name: mcp-oauth-demo (or your choice)"
echo "   - Supported account types: Single tenant (or as needed)"
echo "   - Redirect URI: (leave blank for now, or add your client's redirect URI)"
echo "4. Click 'Register'"
echo ""
echo -e "${GREEN}After registration, you'll need:${NC}"
echo "   - Application (client) ID"
echo "   - Directory (tenant) ID"
echo ""
read -p "Press Enter when you've created the app registration..."

# Step 2: Get Tenant ID and Client ID
echo ""
echo "========================================="
echo "Step 2: Provide Configuration Values"
echo "========================================="
echo ""

read -p "Enter your Tenant ID: " TENANT_ID
read -p "Enter your Client ID: " CLIENT_ID

echo ""
echo -e "${GREEN}Configuration values received:${NC}"
echo "  Tenant ID: $TENANT_ID"
echo "  Client ID: $CLIENT_ID"
echo ""

# Step 3: Instructions for configuring API permissions/scopes
echo "========================================="
echo "Step 3: Configure API Permissions & Scopes"
echo "========================================="
echo ""
echo "You need to expose custom scopes for the MCP demo:"
echo ""
echo "1. In your app registration, go to: Expose an API"
echo "2. Click 'Add a scope' and create these scopes:"
echo ""
echo "   Scope 1:"
echo "     - Scope name: files.read"
echo "     - Who can consent: Admins and users"
echo "     - Admin consent display name: Read files"
echo "     - Admin consent description: Allows reading files"
echo "     - State: Enabled"
echo ""
echo "   Scope 2:"
echo "     - Scope name: files.delete"
echo "     - Who can consent: Admins only"
echo "     - Admin consent display name: Delete files"
echo "     - Admin consent description: Allows deleting files"
echo "     - State: Enabled"
echo ""
echo "3. Note: The full scope URI will be: api://$CLIENT_ID/files.read"
echo ""
read -p "Press Enter when you've configured the scopes..."

# Step 4: Instructions for configuring App Roles
echo ""
echo "========================================="
echo "Step 4: Configure App Roles"
echo "========================================="
echo ""
echo "You need to create app roles for authorization:"
echo ""
echo "1. In your app registration, go to: App roles"
echo "2. Click 'Create app role' and create these roles:"
echo ""
echo "   Role 1:"
echo "     - Display name: Admin"
echo "     - Allowed member types: Users/Groups"
echo "     - Value: admin"
echo "     - Description: Administrator role with full access"
echo "     - Enable this app role: Yes"
echo ""
echo "   Role 2:"
echo "     - Display name: User"
echo "     - Allowed member types: Users/Groups"
echo "     - Value: user"
echo "     - Description: Standard user role"
echo "     - Enable this app role: Yes"
echo ""
echo "3. After creating roles, assign them to users:"
echo "   - Go to: Enterprise applications > Your app > Users and groups"
echo "   - Click 'Add user/group'"
echo "   - Select users and assign them roles"
echo ""
read -p "Press Enter when you've configured the roles..."

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
    sed -i.tmp "s/{TENANT_ID}/$TENANT_ID/g" "$POLICY_FILE"
    sed -i.tmp "s/{CLIENT_ID}/$CLIENT_ID/g" "$POLICY_FILE"
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
echo "If your test clients need a client secret, create one in Azure:"
echo ""
echo "1. In your app registration, go to: Certificates & secrets"
echo "2. Click 'New client secret'"
echo "3. Add a description and select an expiration"
echo "4. Click 'Add' and COPY THE SECRET VALUE (you won't see it again)"
echo ""
read -p "Do you want to create a Kubernetes secret with these values? (y/n): " CREATE_SECRET

if [[ "$CREATE_SECRET" =~ ^[Yy]$ ]]; then
    read -s -p "Enter your client secret (input hidden): " CLIENT_SECRET
    echo ""

    # Create secrets.yaml from template
    SECRETS_FILE="$K8S_DIR/secrets.yaml"
    cp "$K8S_DIR/secrets.yaml.template" "$SECRETS_FILE"

    sed -i.tmp "s/YOUR_TENANT_ID/$TENANT_ID/g" "$SECRETS_FILE"
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
echo -e "${GREEN}Your Entra ID configuration is ready!${NC}"
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
echo "   kubectl get pods -n mcp-demo-entra"
echo "   kubectl get gateway,mcptarget,glootrafficpolicy -n mcp-demo-entra"
echo ""
echo "5. Test the setup:"
echo "   kubectl port-forward svc/mcp-gateway 3000:3000 -n mcp-demo-entra"
echo "   # Then use the test client scripts to test with tokens"
echo ""
echo "For detailed instructions, see the README.md file."
echo ""
