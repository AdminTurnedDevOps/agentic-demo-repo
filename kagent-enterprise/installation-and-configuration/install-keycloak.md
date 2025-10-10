## 1. Deploy Keycloak
```bash
kubectl apply -f keycloak.yaml
kubectl get svc keycloak
```

Wait for LoadBalancer IP and access Keycloak at: http://KEYCLOAK_IP:8080
- Admin Console: http://KEYCLOAK_IP:8080/admin
- Login: admin / password

## 2. Configure OIDC Clients in Keycloak

### Create kagent-frontend Client
1. Go to Clients → Create client
2. Client ID: `kagent-frontend`
3. Client authentication: OFF
4. Standard flow: ON
5. Valid redirect URIs: `http://KAGENT_UI_IP/*`
6. Web origins: `http://KAGENT_UI_IP`

### Create kagent-backend Client  
1. Go to Clients → Create client
2. Client ID: `kagent-backend`
3. Client authentication: ON
4. Standard flow: ON
5. Service accounts roles: ON
6. Get client secret from Credentials tab