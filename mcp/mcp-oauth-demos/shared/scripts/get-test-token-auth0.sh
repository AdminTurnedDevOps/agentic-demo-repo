#!/bin/bash

# Get an access token from Auth0 using device code flow
# This is the easiest flow for CLI demos and workshops

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Get Auth0 Access Token${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check for jq
if ! command -v jq &> /dev/null; then
    echo -e "${RED}Error: jq is required but not installed.${NC}"
    echo "Install it with: brew install jq (macOS) or apt-get install jq (Linux)"
    exit 1
fi

# Get configuration
read -p "Enter your Auth0 Domain (e.g., your-tenant.us.auth0.com): " AUTH0_DOMAIN
read -p "Enter your Client ID: " CLIENT_ID
read -p "Enter your API Identifier (audience, e.g., https://mcp-oauth-demo): " AUDIENCE

# Request the scopes you want
echo ""
echo "Enter the scopes you want (space-separated):"
echo "Examples:"
echo "  - files:read"
echo "  - files:read files:delete"
echo ""
read -p "Scopes: " SCOPES

# Default to openid if no scopes provided
if [ -z "$SCOPES" ]; then
    SCOPES="openid"
fi

echo ""
echo -e "${YELLOW}Initiating device code flow...${NC}"

# Request device code
DEVICE_CODE_RESPONSE=$(curl -s -X POST \
    "https://$AUTH0_DOMAIN/oauth/device/code" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "client_id=$CLIENT_ID&scope=$SCOPES&audience=$AUDIENCE")

# Extract values
USER_CODE=$(echo "$DEVICE_CODE_RESPONSE" | jq -r '.user_code')
DEVICE_CODE=$(echo "$DEVICE_CODE_RESPONSE" | jq -r '.device_code')
VERIFICATION_URL=$(echo "$DEVICE_CODE_RESPONSE" | jq -r '.verification_uri_complete // .verification_uri')

if [ "$USER_CODE" = "null" ] || [ -z "$USER_CODE" ]; then
    echo -e "${RED}Error getting device code:${NC}"
    echo "$DEVICE_CODE_RESPONSE" | jq .
    exit 1
fi

# Display instructions
echo ""
echo -e "${GREEN}Device code obtained successfully!${NC}"
echo ""
echo -e "${YELLOW}Instructions:${NC}"
echo "1. Open this URL in your browser: ${BLUE}$VERIFICATION_URL${NC}"
echo "2. If prompted, enter this code: ${GREEN}$USER_CODE${NC}"
echo "3. Sign in with your account"
echo "4. Consent to the requested scopes"
echo ""
echo "Waiting for authentication..."

# Poll for the token
INTERVAL=$(echo "$DEVICE_CODE_RESPONSE" | jq -r '.interval // 5')
MAX_ATTEMPTS=60
ATTEMPT=0

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    sleep $INTERVAL
    ATTEMPT=$((ATTEMPT + 1))

    TOKEN_RESPONSE=$(curl -s -X POST \
        "https://$AUTH0_DOMAIN/oauth/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "grant_type=urn:ietf:params:oauth:grant-type:device_code&client_id=$CLIENT_ID&device_code=$DEVICE_CODE")

    ERROR=$(echo "$TOKEN_RESPONSE" | jq -r '.error // "none"')

    if [ "$ERROR" = "none" ]; then
        # Success!
        ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token')

        echo ""
        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}✓ Authentication successful!${NC}"
        echo -e "${GREEN}========================================${NC}"
        echo ""
        echo -e "${YELLOW}Access Token:${NC}"
        echo "$ACCESS_TOKEN"
        echo ""
        echo -e "${YELLOW}Token Details:${NC}"

        # Decode and display token claims (header + payload)
        HEADER=$(echo "$ACCESS_TOKEN" | cut -d. -f1)
        PAYLOAD=$(echo "$ACCESS_TOKEN" | cut -d. -f2)

        # Add padding if needed for base64 decoding
        PAYLOAD_PADDED=$(printf '%s' "$PAYLOAD" | awk '{while (length($0) % 4 != 0) $0 = $0 "="; print}')

        echo ""
        echo "Decoded payload:"
        echo "$PAYLOAD_PADDED" | base64 -d 2>/dev/null | jq . || echo "Could not decode token"

        echo ""
        echo -e "${YELLOW}Export token for use in tests:${NC}"
        echo "export AUTH0_TOKEN=\"$ACCESS_TOKEN\""
        echo ""
        echo -e "${YELLOW}Test with the MCP demo:${NC}"
        echo "cd ../../auth0/test-client"
        echo "./test-mcp.sh --token \$AUTH0_TOKEN --tool echo"

        exit 0

    elif [ "$ERROR" = "authorization_pending" ]; then
        # Still waiting for user to authenticate
        echo -n "."
    elif [ "$ERROR" = "slow_down" ]; then
        # Increase polling interval
        INTERVAL=$((INTERVAL + 5))
        echo -n "."
    else
        # Error occurred
        echo ""
        echo -e "${RED}Error: $ERROR${NC}"
        echo "$TOKEN_RESPONSE" | jq .
        exit 1
    fi
done

echo ""
echo -e "${RED}Timeout waiting for authentication${NC}"
exit 1
