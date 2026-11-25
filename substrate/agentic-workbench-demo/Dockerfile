FROM golang:1.25.14 AS build
WORKDIR /src
COPY go.mod main.go ./
COPY web ./web
RUN CGO_ENABLED=0 go build -trimpath -o /workbench .

FROM scratch
COPY --from=build /workbench /workbench
ENV LISTEN_ADDR=:80 WORKSPACE_DIR=/workspace
EXPOSE 80
ENTRYPOINT ["/workbench"]
