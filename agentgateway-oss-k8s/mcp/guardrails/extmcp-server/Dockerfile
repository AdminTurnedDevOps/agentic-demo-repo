FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ext_mcp.proto server.py ./
RUN python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. ext_mcp.proto \
    && useradd --system --uid 65532 --gid nogroup extmcp \
    && chown -R extmcp:nogroup /app

USER 65532:65534
EXPOSE 9001 8080
CMD ["python", "server.py"]
