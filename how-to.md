1. Deploy keycloak (`keycloak.yaml`)
2. Create the frontend/backend client in keycloak (put in a foo redirect URL). Config for what is needed for keycloak is in `install-kagent.md`.
3. Deploy kagent enterprise (the backend/frontend just needs keycloaks URL and the secret created)
4. Go into keycloak and update the frontend client with kagent enterprises k8s services LB IP