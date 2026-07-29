# Code Mode Token Cost Test

This test compares the tool-context overhead of the two currently deployed MCP
gateways:

| Gateway | MCP endpoint | Tool source |
| --- | --- | --- |
| `codemode-gateway` | `/mcp/geocoding` | Code Mode facade for the Open-Meteo Geocoding API |
| `mcp-gateway` | `/mcp` | Standard GitHub Copilot MCP server |

The test does not require an Agent. It retrieves each MCP `tools/list` response,
converts the tools to the format accepted by the existing Anthropic route, and
sends the same prompt and tool inventory to Claude Sonnet 4.6. The response's
`usage.prompt_tokens` value is the primary measurement.

MCP Inspector can display the tool definitions, but it does not invoke an LLM
and therefore cannot report model token usage.

> This measures the two deployed configurations as they exist. The upstreams
> and tool inventories differ, so it is not a controlled test where MCP tool
> mode is the only variable.

## Prerequisites

- The active Kubernetes context points to the cluster containing both Gateways.
- `kubectl` can access the `agentgateway-system` namespace.
- Node.js 18 or newer is installed.
- The `anthropic` backend and `anthropic-secret` are configured.
- A GitHub PAT with access to the GitHub Copilot MCP server is available.

## 1. Update GitHub Authentication

Enter the PAT interactively so it is not written to this file or shell history.
The upstream expects the complete `Authorization` header in the Secret.

```bash
read -rsp "GitHub PAT: " GITHUB_PAT
printf '\n'

kubectl create secret generic github-pat \
  --namespace agentgateway-system \
  --from-literal=Authorization="Bearer ${GITHUB_PAT}" \
  --dry-run=client \
  -o yaml | kubectl apply -f -

unset GITHUB_PAT
```

## 2. Run The Comparison

The script discovers the current Gateway addresses, initializes separate MCP
sessions, fetches both tool inventories, and makes two otherwise identical LLM
requests. It does not call any MCP tools.

```bash
RESULTS="$(
node --input-type=module <<'NODE'
import { execFileSync } from "node:child_process";

const namespace = "agentgateway-system";
const inputUsdPerMillion = 3;
const outputUsdPerMillion = 15;

function gatewayAddress(name) {
  return execFileSync(
    "kubectl",
    [
      "get",
      "gateway",
      name,
      "--namespace",
      namespace,
      "--output",
      "jsonpath={.status.addresses[0].value}",
    ],
    { encoding: "utf8" },
  ).trim();
}

function parseMcpResponse(body) {
  const events = body
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim());

  return JSON.parse(events.length > 0 ? events.at(-1) : body);
}

async function request(url, options, operation) {
  const response = await fetch(url, options);
  const body = await response.text();

  if (!response.ok) {
    throw new Error(`${operation} returned ${response.status}: ${body}`);
  }

  return { response, body };
}

async function listTools(url) {
  const headers = {
    accept: "application/json, text/event-stream",
    "content-type": "application/json",
  };

  const initialized = await request(
    url,
    {
      method: "POST",
      headers,
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: {
          protocolVersion: "2024-11-05",
          capabilities: {},
          clientInfo: { name: "token-cost-test", version: "1" },
        },
      }),
    },
    `${url} initialize`,
  );

  const sessionId = initialized.response.headers.get("mcp-session-id");
  if (sessionId) {
    headers["mcp-session-id"] = sessionId;
  }

  await request(
    url,
    {
      method: "POST",
      headers,
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "notifications/initialized",
      }),
    },
    `${url} initialized notification`,
  );

  const listed = await request(
    url,
    {
      method: "POST",
      headers,
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 2,
        method: "tools/list",
        params: {},
      }),
    },
    `${url} tools/list`,
  );

  return parseMcpResponse(listed.body).result.tools;
}

function modelTools(mcpTools) {
  return mcpTools.map((tool) => ({
    type: "function",
    function: {
      name: tool.name,
      description: tool.description ?? "",
      parameters: tool.inputSchema ?? { type: "object" },
    },
  }));
}

function estimatedCost(usage) {
  return (
    (usage.prompt_tokens * inputUsdPerMillion +
      usage.completion_tokens * outputUsdPerMillion) /
    1_000_000
  );
}

async function measure(label, mcpTools, llmUrl) {
  const tools = modelTools(mcpTools);
  const result = await request(
    llmUrl,
    {
      method: "POST",
      headers: {
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: "claude-sonnet-4-6",
        max_tokens: 16,
        messages: [
          {
            role: "user",
            content: "Do not call any tools. Reply with exactly OK.",
          },
        ],
        tools,
      }),
    },
    `${label} model request`,
  );

  const response = JSON.parse(result.body);
  return {
    label,
    toolCount: mcpTools.length,
    mcpToolBytes: Buffer.byteLength(JSON.stringify(mcpTools)),
    modelToolBytes: Buffer.byteLength(JSON.stringify(tools)),
    usage: response.usage,
    estimatedCostUsd: estimatedCost(response.usage),
    finishReason: response.choices?.[0]?.finish_reason,
  };
}

const codeAddress = gatewayAddress("codemode-gateway");
const standardAddress = gatewayAddress("mcp-gateway");
const codeMcpUrl = `http://${codeAddress}/mcp/geocoding`;
const standardMcpUrl = `http://${standardAddress}:3000/mcp`;
const llmUrl = `http://${standardAddress}:3000/anthropic`;

const codeTools = await listTools(codeMcpUrl);
const standardTools = await listTools(standardMcpUrl);
const code = await measure("code-mode-geocoding", codeTools, llmUrl);
const standard = await measure("standard-github", standardTools, llmUrl);

const promptTokenDifference =
  standard.usage.prompt_tokens - code.usage.prompt_tokens;
const promptTokenReductionPercent =
  (1 - code.usage.prompt_tokens / standard.usage.prompt_tokens) * 100;
const estimatedCostDifferenceUsd =
  standard.estimatedCostUsd - code.estimatedCostUsd;

console.table([
  {
    configuration: "Code Mode Geocoding",
    tools: code.toolCount,
    mcpBytes: code.mcpToolBytes,
    modelBytes: code.modelToolBytes,
    promptTokens: code.usage.prompt_tokens,
    completionTokens: code.usage.completion_tokens,
    estimatedCostUsd: code.estimatedCostUsd.toFixed(6),
  },
  {
    configuration: "Standard GitHub",
    tools: standard.toolCount,
    mcpBytes: standard.mcpToolBytes,
    modelBytes: standard.modelToolBytes,
    promptTokens: standard.usage.prompt_tokens,
    completionTokens: standard.usage.completion_tokens,
    estimatedCostUsd: standard.estimatedCostUsd.toFixed(6),
  },
]);

console.log(`Prompt tokens avoided: ${promptTokenDifference}`);
console.log(
  `Prompt-token reduction: ${promptTokenReductionPercent.toFixed(2)}%`,
);
console.log(
  `Estimated savings per request: $${estimatedCostDifferenceUsd.toFixed(6)}`,
);
NODE
)"

printf '%s\n' "$RESULTS"
```
