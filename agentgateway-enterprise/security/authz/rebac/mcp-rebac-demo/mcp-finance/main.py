import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

mcp = FastMCP("finance-mcp")


@mcp.tool()
def read_budget(project: str) -> str:
    return f"Budget for {project}: on track"


@mcp.tool()
def create_forecast_ticket(quarter: str) -> str:
    return f"Created finance ticket for {quarter}"


def _serialize_tool_result(result_items) -> list[dict]:
    serialized = []
    for item in result_items:
        if hasattr(item, "type") and item.type == "text":
            serialized.append({"type": "text", "text": item.text})
        elif isinstance(item, dict):
            serialized.append(item)
        else:
            serialized.append({"type": "text", "text": str(item)})
    return serialized


async def handle_mcp(request: Request):
    payload = await request.json()
    method = payload.get("method")
    msg_id = payload.get("id")

    if method == "initialize":
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "finance-mcp", "version": "0.1.0"},
                },
            }
        )

    if method == "notifications/initialized":
        return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "result": True})

    if method == "tools/list":
        tools = await mcp.list_tools()
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": t.inputSchema,
                        }
                        for t in tools
                    ]
                },
            }
        )

    if method == "tools/call":
        params = payload.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        result_items = await mcp.call_tool(name, args)
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": _serialize_tool_result(result_items),
                    "isError": False,
                },
            }
        )

    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": "Method not found"},
        },
        status_code=404,
    )


app = Starlette(
    routes=[
        Route("/", lambda _: JSONResponse({"status": "ok", "service": "mcp-finance"}), methods=["GET"]),
        Route("/mcp", handle_mcp, methods=["POST"]),
    ]
)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
