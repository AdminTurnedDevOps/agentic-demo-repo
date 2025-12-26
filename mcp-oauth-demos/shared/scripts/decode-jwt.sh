#!/bin/bash

# Decode and display JWT token claims
# Useful for debugging and understanding token contents

set -e

# Colors
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

if [ -z "$1" ]; then
    echo "Usage: $0 <JWT_TOKEN>"
    echo ""
    echo "Example:"
    echo "  $0 eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
    exit 1
fi

TOKEN="$1"

# Check for jq
if ! command -v jq &> /dev/null; then
    echo "Warning: jq not found. Output will not be formatted."
    JQ_AVAILABLE=false
else
    JQ_AVAILABLE=true
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}JWT Token Decoder${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Split the token into parts
IFS='.' read -ra PARTS <<< "$TOKEN"

if [ ${#PARTS[@]} -ne 3 ]; then
    echo "Error: Invalid JWT token format"
    exit 1
fi

HEADER="${PARTS[0]}"
PAYLOAD="${PARTS[1]}"
SIGNATURE="${PARTS[2]}"

# Function to decode base64url
decode_base64url() {
    local input="$1"
    # Add padding if needed
    local padded=$(printf '%s' "$input" | awk '{while (length($0) % 4 != 0) $0 = $0 "="; print}')
    # Decode
    echo "$padded" | base64 -d 2>/dev/null
}

# Decode header
echo -e "${YELLOW}Header:${NC}"
HEADER_JSON=$(decode_base64url "$HEADER")
if [ "$JQ_AVAILABLE" = true ]; then
    echo "$HEADER_JSON" | jq .
else
    echo "$HEADER_JSON"
fi
echo ""

# Decode payload
echo -e "${YELLOW}Payload (Claims):${NC}"
PAYLOAD_JSON=$(decode_base64url "$PAYLOAD")
if [ "$JQ_AVAILABLE" = true ]; then
    echo "$PAYLOAD_JSON" | jq .
else
    echo "$PAYLOAD_JSON"
fi
echo ""

# Display signature (cannot be decoded without the secret/private key)
echo -e "${YELLOW}Signature:${NC}"
echo "$SIGNATURE"
echo -e "${BLUE}(Signature verification requires the signing key)${NC}"
echo ""

# Extract and display important claims
if [ "$JQ_AVAILABLE" = true ]; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}Key Claims Summary${NC}"
    echo -e "${GREEN}========================================${NC}"

    ISS=$(echo "$PAYLOAD_JSON" | jq -r '.iss // "N/A"')
    SUB=$(echo "$PAYLOAD_JSON" | jq -r '.sub // "N/A"')
    AUD=$(echo "$PAYLOAD_JSON" | jq -r '.aud // "N/A"')
    EXP=$(echo "$PAYLOAD_JSON" | jq -r '.exp // "N/A"')
    IAT=$(echo "$PAYLOAD_JSON" | jq -r '.iat // "N/A"')
    SCOPES=$(echo "$PAYLOAD_JSON" | jq -r '.scope // .scp // "N/A"')
    ROLES=$(echo "$PAYLOAD_JSON" | jq -r '.roles // "N/A"')

    echo "Issuer (iss):    $ISS"
    echo "Subject (sub):   $SUB"
    echo "Audience (aud):  $AUD"
    echo "Scopes:          $SCOPES"
    echo "Roles:           $ROLES"
    echo ""

    if [ "$EXP" != "N/A" ]; then
        EXP_DATE=$(date -r "$EXP" 2>/dev/null || date -d "@$EXP" 2>/dev/null || echo "Unknown")
        echo "Expires at (exp): $EXP ($EXP_DATE)"

        # Check if token is expired
        CURRENT_TIME=$(date +%s)
        if [ "$EXP" -lt "$CURRENT_TIME" ]; then
            echo -e "${YELLOW}⚠ Token is EXPIRED${NC}"
        else
            REMAINING=$((EXP - CURRENT_TIME))
            echo -e "${GREEN}✓ Token is valid (expires in ${REMAINING}s)${NC}"
        fi
    fi

    if [ "$IAT" != "N/A" ]; then
        IAT_DATE=$(date -r "$IAT" 2>/dev/null || date -d "@$IAT" 2>/dev/null || echo "Unknown")
        echo "Issued at (iat):  $IAT ($IAT_DATE)"
    fi
fi

echo ""
