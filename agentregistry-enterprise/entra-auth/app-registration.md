export OIDC_CLIENT_PASSWORD='<password>'

arctl user login \
  --oidc-flow password-credentials \
  --oidc-issuer-url "$OIDC_ISSUER" \
  --oidc-client-id "$OIDC_CLIENT_ID" \
  --oidc-username "$USERNAME"