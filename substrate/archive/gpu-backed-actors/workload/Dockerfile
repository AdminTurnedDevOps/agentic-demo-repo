# Build on the host arch (ARM Mac) so go test is not emulated.
# The runtime image is linux/amd64 for GKE GPU nodes.
FROM --platform=$BUILDPLATFORM golang:1.24-bookworm AS build
ARG TARGETOS=linux
ARG TARGETARCH=amd64
WORKDIR /src
COPY go.mod main.go main_test.go ./
RUN go test ./...
RUN CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} go build -o /gpu-agent .

# debian, not distroless: nvidia-smi from the driver mount is dynamically linked
# against glibc in this image's rootfs.
FROM debian:bookworm-slim
COPY --from=build /gpu-agent /usr/local/bin/gpu-agent
EXPOSE 80
ENTRYPOINT ["/usr/local/bin/gpu-agent"]
