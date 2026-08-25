#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

enum { port = 80, request_size = 2048, result_size = 8192 };

static volatile sig_atomic_t stopping = 0;

static void handle_signal(int signal_number) {
  (void)signal_number;
  stopping = 1;
}

static int send_all(int socket_fd, const char *data, size_t length) {
  while (length > 0) {
    ssize_t written = send(socket_fd, data, length, 0);
    if (written < 0) {
      if (errno == EINTR) {
        continue;
      }
      return -1;
    }
    if (written == 0) {
      return -1;
    }
    data += written;
    length -= (size_t)written;
  }
  return 0;
}

static int read_result(const char *path, char *buffer, size_t capacity) {
  FILE *file = fopen(path, "r");
  if (file == NULL) {
    return -1;
  }

  size_t length = fread(buffer, 1, capacity - 1, file);
  if (ferror(file)) {
    fclose(file);
    return -1;
  }
  buffer[length] = '\0';
  fclose(file);
  return 0;
}

static void serve_request(int client_fd, const char *result_path) {
  char request[request_size];
  ssize_t request_length = recv(client_fd, request, sizeof(request) - 1, 0);
  if (request_length <= 0) {
    return;
  }
  request[request_length] = '\0';

  const int ready_request = strncmp(request, "GET /readyz ", 12) == 0;
  const int root_request = strncmp(request, "GET / ", 6) == 0;
  const char *status = "200 OK";
  const char *content_type = "text/plain; charset=utf-8";
  char body[result_size];

  if (ready_request) {
    char result[result_size / 2];
    if (read_result(result_path, result, sizeof(result)) != 0) {
      status = "503 Service Unavailable";
      snprintf(body, sizeof(body), "GPU result is unavailable\n");
    } else {
      snprintf(body, sizeof(body), "ok\n");
    }
  } else if (root_request) {
    char result[result_size / 2];
    if (read_result(result_path, result, sizeof(result)) != 0) {
      status = "500 Internal Server Error";
      snprintf(body, sizeof(body), "GPU result is unavailable\n");
    } else {
      snprintf(body, sizeof(body),
               "actor_status=ready\nserver_pid=%ld\n%s", (long)getpid(),
               result);
    }
  } else {
    status = "404 Not Found";
    snprintf(body, sizeof(body), "not found\n");
  }

  char headers[512];
  int header_length = snprintf(
      headers, sizeof(headers),
      "HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %zu\r\n"
      "Connection: close\r\n\r\n",
      status, content_type, strlen(body));
  if (header_length < 0 || (size_t)header_length >= sizeof(headers)) {
    return;
  }

  if (send_all(client_fd, headers, (size_t)header_length) == 0) {
    (void)send_all(client_fd, body, strlen(body));
  }
}

int main(int argc, char **argv) {
  if (argc != 2) {
    fprintf(stderr, "usage: %s RESULT_FILE\n", argv[0]);
    return EXIT_FAILURE;
  }

  struct sigaction action = {.sa_handler = handle_signal};
  sigemptyset(&action.sa_mask);
  if (sigaction(SIGINT, &action, NULL) != 0 ||
      sigaction(SIGTERM, &action, NULL) != 0) {
    perror("sigaction");
    return EXIT_FAILURE;
  }
  if (signal(SIGPIPE, SIG_IGN) == SIG_ERR) {
    perror("signal");
    return EXIT_FAILURE;
  }

  int server_fd = socket(AF_INET, SOCK_STREAM, 0);
  if (server_fd < 0) {
    perror("socket");
    return EXIT_FAILURE;
  }

  int reuse_address = 1;
  if (setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &reuse_address,
                 sizeof(reuse_address)) != 0) {
    perror("setsockopt");
    close(server_fd);
    return EXIT_FAILURE;
  }

  struct sockaddr_in address = {
      .sin_family = AF_INET,
      .sin_port = htons(port),
      .sin_addr = {.s_addr = htonl(INADDR_ANY)},
  };
  if (bind(server_fd, (struct sockaddr *)&address, sizeof(address)) != 0) {
    perror("bind");
    close(server_fd);
    return EXIT_FAILURE;
  }
  if (listen(server_fd, 16) != 0) {
    perror("listen");
    close(server_fd);
    return EXIT_FAILURE;
  }

  printf("STATUS_SERVER_READY port=%d result_file=%s\n", port, argv[1]);
  fflush(stdout);

  while (!stopping) {
    int client_fd = accept(server_fd, NULL, NULL);
    if (client_fd < 0) {
      if (errno == EINTR) {
        continue;
      }
      perror("accept");
      close(server_fd);
      return EXIT_FAILURE;
    }
    struct timeval io_timeout = {.tv_sec = 5, .tv_usec = 0};
    if (setsockopt(client_fd, SOL_SOCKET, SO_RCVTIMEO, &io_timeout,
                   sizeof(io_timeout)) != 0 ||
        setsockopt(client_fd, SOL_SOCKET, SO_SNDTIMEO, &io_timeout,
                   sizeof(io_timeout)) != 0) {
      perror("setsockopt client timeout");
      close(client_fd);
      continue;
    }
    serve_request(client_fd, argv[1]);
    close(client_fd);
  }

  close(server_fd);
  return EXIT_SUCCESS;
}
