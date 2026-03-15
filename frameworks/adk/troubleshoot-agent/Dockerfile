### STAGE 1: base image
ARG DOCKER_REGISTRY=ghcr.io
ARG VERSION=0.7.7
FROM $DOCKER_REGISTRY/kagent-dev/kagent/kagent-adk:$VERSION

WORKDIR /app

COPY troubleshootagent/ troubleshootagent/
COPY pyproject.toml pyproject.toml
COPY uv.lock uv.lock
COPY how-it-works.md how-it-works.md

RUN uv sync --locked --refresh

CMD ["troubleshootagent"]
