# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

FROM --platform=linux/amd64 nvidia/cuda@sha256:a99a1860ba8e2916e5c3e73b72ec4c4301653a84586e05bfc9a2aa2d58027e97 AS build

WORKDIR /src
COPY cuda_probe.cu status_server.c ./
RUN nvcc -O2 -o /cuda-probe cuda_probe.cu \
    && cc -O2 -Wall -Wextra -Werror -o /status-server status_server.c

FROM --platform=linux/amd64 nvidia/cuda@sha256:4a801ef9232d2b05e69df4eb8aa054dbbe2824e5499e1e6e857320bb01ac41a9

COPY --from=build /cuda-probe /usr/local/bin/cuda-probe
COPY --from=build /status-server /usr/local/bin/status-server
COPY start.sh /usr/local/bin/start.sh
RUN chmod 0755 /usr/local/bin/start.sh

EXPOSE 80
ENTRYPOINT ["/usr/local/bin/start.sh"]
