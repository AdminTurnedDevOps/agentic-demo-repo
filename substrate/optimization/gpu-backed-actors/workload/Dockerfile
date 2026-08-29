FROM --platform=linux/amd64 golang:1.24-bookworm AS build

WORKDIR /src
COPY go.mod main.go main_test.go ./
RUN go test ./...
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /gpu-agent .

# debian, not distroless: nvidia-smi from the driver mount is dynamically linked
# against glibc in this image's rootfs.
FROM --platform=linux/amd64 debian:bookworm-slim

COPY --from=build /gpu-agent /usr/local/bin/gpu-agent
EXPOSE 80
ENTRYPOINT ["/usr/local/bin/gpu-agent"]
