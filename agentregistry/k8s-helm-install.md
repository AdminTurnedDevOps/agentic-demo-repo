JWT_KEY=$(openssl rand -hex 32)

helm upgrade --install agentregistry oci://ghcr.io/agentregistry-dev/agentregistry/charts/agentregistry --namespace agentregistry \
--create-namespace \
--set config.jwtPrivateKey="${JWT_KEY}" \
--set config.enableAnonymousAuth="true" \
--set service.type=LoadBalancer \
--set database.postgres.vectorEnabled=true \
--set database.postgres.bundled.image.repository=pgvector \
--set database.postgres.bundled.image.name=pgvector \
--set database.postgres.bundled.image.tag=pg16 \
--set image.tag=v0.3.3 \
--wait --timeout 300s

helm upgrade --install --reuse-values agentregistry oci://ghcr.io/agentregistry-dev/agentregistry/charts/agentregistry --namespace agentregistry \
--set config.disableBuiltinSeed="false"