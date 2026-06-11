```
source ~/.zshrc
```

```
export TENANT_ID="5e7d8166-7876-4755-a1a4-b476d4a344f6"
export ARE_CLI_CLIENT_ID="d8eea557-75fd-44ae-aa05-fe99041a6801"
export ARE_BACKEND_CLIENT_ID="2bcea899-dfc5-4b73-a805-43737d958921"
```

arctl user login \
  --oidc-issuer-url "https://login.microsoftonline.com/$TENANT_ID/v2.0" \
  --oidc-client-id "$ARE_CLI_CLIENT_ID" \
  --oidc-scope "openid,profile,offline_access,api://$ARE_BACKEND_CLIENT_ID/agentregistry"

```
arctl user login \
  --oidc-issuer-url "https://login.microsoftonline.com/$TENANT_ID/v2.0" \
  --oidc-client-id "$ARE_CLI_CLIENT_ID"
```

That will start the CLI/device login flow and you’ll sign in with your email in Entra.