#!/bin/bash

# Test script for MCP OAuth demo with Auth0
# Tests calling MCP tools through agentgateway with JWT authentication

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Default values
GATEWAY_URL="http://localhost:3000"
TOKEN=""
TOOL=""
MESSAGE="Hello from MCP!"
FILENAME="test.txt"

# Usage
usage() {
    echo "Usage: $0 --token <JWT_TOKEN> --tool <TOOL_NAME> [--gateway-url <URL>]"
    echo ""
    echo "Available tools:"
    echo "  echo                - Echo a message (any authenticated user)"
    echo "  get_user_info       - Get user information from JWT (any authenticated user)"
    echo "  list_files          - List files (requires files:read scope)"
    echo "  delete_file         - Delete a file (requires files:delete scope AND admin role)"
    echo "  system_status       - Get system status (requires admin role)"
    echo ""
    echo "Options:"
    echo "  --token <TOKEN>     JWT access token (required)"
    echo "  --tool <TOOL>       Tool to call (required)"
    echo "  --gateway-url <URL> Gateway URL (default: http://localhost:3000)"
    echo "  --message <MSG>     Message for echo tool (default: 'Hello from MCP!')"
    echo "  --filename <FILE>   Filename for delete_file tool (default: 'test.txt')"
    echo ""
    echo "Example:"
    echo "  $0 --token \$TOKEN --tool echo"
    echo "  $0 --token \$TOKEN --tool list_files"
    exit 1
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --token)
            TOKEN="$2"
            shift 2
            ;;
        --tool)
            TOOL="$2"
            shift 2
            ;;
        --gateway-url)
            GATEWAY_URL="$2"
            shift 2
            ;;
        --message)
            MESSAGE="$2"
            shift 2
            ;;
        --filename)
            FILENAME="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            usage
            ;;
    esac
done

# Validate required arguments
if [ -z "$TOKEN" ] || [ -z "$TOOL" ]; then
    echo -e "${RED}Error: --token and --tool are required${NC}"
    usage
fi

# Build the MCP request based on the tool
build_mcp_request() {
    case $TOOL in
        echo)
            cat <<EOF
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "echo",
    "arguments": {
      "message": "$MESSAGE"
    }
  }
}
EOF
            ;;
        get_user_info)
            cat <<EOF
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "get_user_info",
    "arguments": {}
  }
}
EOF
            ;;
        list_files)
            cat <<EOF
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "list_files",
    "arguments": {
      "path": "/"
    }
  }
}
EOF
            ;;
        delete_file)
            cat <<EOF
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "delete_file",
    "arguments": {
      "filename": "$FILENAME"
    }
  }
}
EOF
            ;;
        system_status)
            cat <<EOF
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "system_status",
    "arguments": {}
  }
}
EOF
            ;;
        *)
            echo -e "${RED}Unknown tool: $TOOL${NC}"
            exit 1
            ;;
    esac
}

# Make the request
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Testing MCP Tool: $TOOL${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

REQUEST_BODY=$(build_mcp_request)

echo -e "${YELLOW}Gateway URL:${NC} $GATEWAY_URL"
echo -e "${YELLOW}Tool:${NC} $TOOL"
echo -e "${YELLOW}Request:${NC}"
echo "$REQUEST_BODY" | jq . 2>/dev/null || echo "$REQUEST_BODY"
echo ""

echo -e "${YELLOW}Sending request...${NC}"
echo ""

RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X POST \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d "$REQUEST_BODY" \
    "$GATEWAY_URL/mcp")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

echo -e "${YELLOW}HTTP Status:${NC} $HTTP_CODE"
echo -e "${YELLOW}Response:${NC}"

if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}"
    echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
    echo -e "${NC}"
    echo -e "${GREEN}✓ Success!${NC}"
elif [ "$HTTP_CODE" = "401" ]; then
    echo -e "${RED}"
    echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
    echo -e "${NC}"
    echo -e "${RED}✗ Authentication failed - Invalid or missing token${NC}"
elif [ "$HTTP_CODE" = "403" ]; then
    echo -e "${RED}"
    echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
    echo -e "${NC}"
    echo -e "${RED}✗ Authorization failed - Token lacks required scopes or roles${NC}"
    echo -e "${YELLOW}Required for this tool:${NC}"
    case $TOOL in
        list_files)
            echo "  - Scope: files:read"
            ;;
        delete_file)
            echo "  - Scope: files:delete"
            echo "  - Role: admin (via custom claim)"
            ;;
        system_status)
            echo "  - Role: admin (via custom claim)"
            ;;
    esac
else
    echo -e "${RED}"
    echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
    echo -e "${NC}"
    echo -e "${RED}✗ Request failed${NC}"
fi

echo ""
