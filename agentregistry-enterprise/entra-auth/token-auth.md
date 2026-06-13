1. Set the appropriate env vars for auth and to point to your agentregistry enterprise instance

```
export PATH="$HOME/.arctl/bin:$PATH"
export ARCTL_API_BASE_URL="http://34.138.72.241:12121"
export TENANT_ID="5e7d8166-7876-4755-a1a4-b476d4a344f6"
export ARE_CLI_CLIENT_ID="d8eea557-75fd-44ae-aa05-fe99041a6801"
export ARE_BACKEND_CLIENT_ID="2bcea899-dfc5-4b73-a805-43737d958921"
```

2. Obtain a token for entra for auth
```
DEVICE_RESPONSE=$(curl -s -X POST \
  "https://login.microsoftonline.com/$TENANT_ID/oauth2/v2.0/devicecode" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=$ARE_CLI_CLIENT_ID&scope=openid+api://$ARE_BACKEND_CLIENT_ID/agentregistry")
echo "$DEVICE_RESPONSE" | python3 -m json.tool
Open the URL/code it prints, then run:
DEVICE_CODE=$(echo "$DEVICE_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['device_code'])")
while true; do
  TOKEN_RESPONSE=$(curl -s -X POST \
    "https://login.microsoftonline.com/$TENANT_ID/oauth2/v2.0/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=urn:ietf:params:oauth:grant-type:device_code&client_id=$ARE_CLI_CLIENT_ID&device_code=$DEVICE_CODE")
  ERROR=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error','none'))")
  if [ "$ERROR" = "none" ]; then
    export ARCTL_API_TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
    echo "Token obtained successfully"
    break
  elif [ "$ERROR" = "authorization_pending" ]; then
    sleep 5
  else
    echo "$TOKEN_RESPONSE" | python3 -m json.tool
    break
  fi
done
```

3. Test `arctl` commands
```
arctl get runtimes
arctl get deployments
```



