/**
 * k6 Load Test — Agent1 (test-math) vs Agent2 (bedrock-direct-test)
 *
 * Agent1 (test-math):          LLM via agentgateway (US-East) → Bedrock (CA-Central)
 *                               MCP via agentgateway (US-West) → MCP Server
 *
 * Agent2 (bedrock-direct-test): Bedrock (CA-Central) directly — no agentgateway, no MCP
 *
 * Gateway overhead ≈ agent1_loop_latency_ms − agent2_loop_latency_ms
 * (both exclude LLM inference; Agent1 also excludes MCP execution time)
 *
 * Run:
 *   k6 run test.js
 *
 * Required environment variables:
 *   AWS_ACCESS_KEY_ID     — AWS access key for direct Bedrock calls (Agent2)
 *   AWS_SECRET_ACCESS_KEY — AWS secret key for direct Bedrock calls (Agent2)
 *
 * Optional environment variables:
 *   AWS_SESSION_TOKEN     — AWS session token (if using temporary credentials)
 *   AWS_REGION            — Bedrock region (default: ca-central-1)
 *   BEDROCK_MODEL_ID      — Bedrock model/inference profile ID (default: global.anthropic.claude-sonnet-4-6)
 *   AGENT1_LLM_URL        — Agent1 LLM gateway endpoint (default: http://agentgateway-us-east:8082/anthropic)
 *   AGENT1_MCP_URL        — Agent1 MCP gateway endpoint (default: http://agentgateway-us-west:8080/mcp)
 */

import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Counter } from "k6/metrics";
import { uuidv4 } from "https://jslib.k6.io/k6-utils/1.4.0/index.js";
import crypto from "k6/crypto";

// ─── AWS / ENDPOINT CONFIGURATION ───────────────────────────────────────────

const AWS_ACCESS_KEY    = __ENV.AWS_ACCESS_KEY_ID     || "";
const AWS_SECRET_KEY    = __ENV.AWS_SECRET_ACCESS_KEY || "";
const AWS_SESSION_TOKEN = __ENV.AWS_SESSION_TOKEN     || "";
const AWS_REGION        = __ENV.AWS_REGION            || "ca-central-1";
const BEDROCK_MODEL_ID  = __ENV.BEDROCK_MODEL_ID      || "global.anthropic.claude-sonnet-4-6";

if (!AWS_ACCESS_KEY || !AWS_SECRET_KEY) {
  console.warn("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required for Agent2 direct Bedrock calls");
}

// Bedrock Runtime InvokeModel endpoint (SigV4-authenticated)
const BEDROCK_HOST = `bedrock-runtime.${AWS_REGION}.amazonaws.com`;
const BEDROCK_PATH = `/model/${BEDROCK_MODEL_ID}/invoke`;
const BEDROCK_URL  = `https://${BEDROCK_HOST}${BEDROCK_PATH}`;

const ENDPOINTS = {
  // Agent1 (test-math): HTTP via agentgateway ALB
  //   LLM gateway rewrites /anthropic → /v1/chat/completions internally (see eks-east1-gatewaysetup.md)
  //   MCP gateway proxies to math-server in us-west-1 (see eks-east1-agent1setup.md)
  llm_via_agentgateway: __ENV.AGENT1_LLM_URL || "http://agentgateway-us-east:8082/anthropic",
  mcp_via_agentgateway: __ENV.AGENT1_MCP_URL  || "http://agentgateway-us-west:8080/mcp",

  // Agent2 (bedrock-direct-test): HTTPS direct to Bedrock Runtime with SigV4
  llm_direct_bedrock: BEDROCK_URL,
};

// ─── AWS SIGV4 REQUEST SIGNING ──────────────────────────────────────────────
//
// Agent2 calls Bedrock directly (no agentgateway). The Bedrock Runtime
// InvokeModel API requires SigV4 authentication, which is what boto3/litellm
// would do inside kagent's Bedrock provider. We replicate it here using k6's
// crypto module so the test is self-contained.

function hmacBinary(key, data) {
  const h = crypto.createHMAC("sha256", key);
  h.update(data);
  return h.digest("binary"); // ArrayBuffer — needed to chain HMACs
}

function sha256Hex(data) {
  return crypto.sha256(data, "hex");
}

function getSignatureKey(secretKey, dateStamp, region, service) {
  const kDate    = hmacBinary("AWS4" + secretKey, dateStamp);
  const kRegion  = hmacBinary(kDate, region);
  const kService = hmacBinary(kRegion, service);
  return hmacBinary(kService, "aws4_request");
}

/**
 * Produce SigV4-signed headers for a POST to the Bedrock Runtime endpoint.
 * @param {string} body — the serialized JSON request body
 * @returns {Object} headers map ready for http.post()
 */
function signedBedrockHeaders(body) {
  const now       = new Date();
  const amzDate   = now.toISOString().replace(/[-:]/g, "").split(".")[0] + "Z"; // 20260319T120000Z
  const dateStamp = amzDate.substring(0, 8); // 20260319

  const payloadHash = sha256Hex(body);

  // Canonical headers must be sorted lexicographically
  let signedHeaderNames = "content-type;host;x-amz-date";
  let canonicalHeaders  =
    `content-type:application/json\n` +
    `host:${BEDROCK_HOST}\n` +
    `x-amz-date:${amzDate}\n`;

  // Temporary credentials (STS) require the security token in the signature
  if (AWS_SESSION_TOKEN) {
    signedHeaderNames = "content-type;host;x-amz-date;x-amz-security-token";
    canonicalHeaders  =
      `content-type:application/json\n` +
      `host:${BEDROCK_HOST}\n` +
      `x-amz-date:${amzDate}\n` +
      `x-amz-security-token:${AWS_SESSION_TOKEN}\n`;
  }

  const canonicalRequest = [
    "POST",
    BEDROCK_PATH,
    "",               // no query string
    canonicalHeaders, // ends with \n — produces required blank line before signed headers
    signedHeaderNames,
    payloadHash,
  ].join("\n");

  const credentialScope = `${dateStamp}/${AWS_REGION}/bedrock/aws4_request`;
  const stringToSign = [
    "AWS4-HMAC-SHA256",
    amzDate,
    credentialScope,
    sha256Hex(canonicalRequest),
  ].join("\n");

  const signingKey = getSignatureKey(AWS_SECRET_KEY, dateStamp, AWS_REGION, "bedrock");
  const sigHmac    = crypto.createHMAC("sha256", signingKey);
  sigHmac.update(stringToSign);
  const signature = sigHmac.digest("hex");

  const authorization =
    `AWS4-HMAC-SHA256 Credential=${AWS_ACCESS_KEY}/${credentialScope}, ` +
    `SignedHeaders=${signedHeaderNames}, Signature=${signature}`;

  const headers = {
    "Content-Type":  "application/json",
    "X-Amz-Date":   amzDate,
    "Authorization": authorization,
  };
  if (AWS_SESSION_TOKEN) {
    headers["X-Amz-Security-Token"] = AWS_SESSION_TOKEN;
  }
  return headers;
}

// ─── CUSTOM METRICS ─────────────────────────────────────────────────────────

// Per-agent loop latency (excl. LLM inference AND MCP time) — diff for gateway overhead
const loopLatencyAgent1 = new Trend("agent1_loop_latency_ms", true);
const loopLatencyAgent2 = new Trend("agent2_loop_latency_ms", true);

// LLM wall time exported separately for auditability (per-hop timing)
const llmWallAgent1 = new Trend("agent1_llm_wall_ms", true);
const llmWallAgent2 = new Trend("agent2_llm_wall_ms", true);

// MCP latency for Agent1 — needed to separate MCP time from gateway overhead
const mcpLatencyAgent1 = new Trend("agent1_mcp_latency_ms", true);

const loopIterationCount = new Counter("loop_iterations_total");
const totalCallsAgent1   = new Counter("agent1_total_mcp_llm_calls");
const totalCallsAgent2   = new Counter("agent2_llm_calls");

// ─── CONCURRENCY LEVELS (run both agents at each level) ─────────────────────
//
// NOTE: Each level runs both agents concurrently, so total VUs = 2× the per-agent value.
//   Light:    50 + 50 = 100 total VUs
//   Moderate: 100 + 100 = 200 total VUs
//   Stress:   up to 1000 + 1000 = 2000 total VUs
// If the benchmark table intends total (not per-agent) counts, halve each VU value.

export const options = {
  scenarios: {
    // ── Light (50 VUs per agent, 3 min) ──
    agent1_light: {
      executor: "constant-vus",
      vus:      50,
      duration: "3m",
      exec:     "agent1Session",
      tags:     { agent: "test-math", level: "light" },
    },
    agent2_light: {
      executor: "constant-vus",
      vus:      50,
      duration: "3m",
      exec:     "agent2Session",
      tags:     { agent: "bedrock-direct-test", level: "light" },
    },

    // ── Moderate (100 VUs per agent, 5 min) ──
    agent1_moderate: {
      executor:  "constant-vus",
      vus:       100,
      duration:  "5m",
      startTime: "3m30s",
      exec:      "agent1Session",
      tags:      { agent: "test-math", level: "moderate" },
    },
    agent2_moderate: {
      executor:  "constant-vus",
      vus:       100,
      duration:  "5m",
      startTime: "3m30s",
      exec:      "agent2Session",
      tags:      { agent: "bedrock-direct-test", level: "moderate" },
    },

    // ── Stress (ramp 100 → 1000 VUs per agent) ──
    agent1_stress: {
      executor: "ramping-vus",
      startVUs: 100,
      stages: [
        { target: 1000, duration: "3m" },  // ramp up
        { target: 1000, duration: "5m" },  // hold
        { target: 0,    duration: "2m" },  // ramp down
      ],
      startTime: "9m",
      exec:      "agent1Session",
      tags:      { agent: "test-math", level: "stress" },
    },
    agent2_stress: {
      executor: "ramping-vus",
      startVUs: 100,
      stages: [
        { target: 1000, duration: "3m" },
        { target: 1000, duration: "5m" },
        { target: 0,    duration: "2m" },
      ],
      startTime: "9m",
      exec:      "agent2Session",
      tags:      { agent: "bedrock-direct-test", level: "stress" },
    },
  },

  thresholds: {
    agent1_loop_latency_ms: ["p(95) < 2000"],
    agent2_loop_latency_ms: ["p(95) < 2000"],
    http_req_failed:        ["rate < 0.01"],
  },
};

// ─── HELPERS ────────────────────────────────────────────────────────────────

// Pre-generate a pool of payloads at init time to avoid per-call string
// allocation, which causes excessive GC pressure and can crash local machines
// at high VU counts. The pool covers the 32–256 KB range from the benchmark spec.
const PAYLOAD_POOL_SIZE = 20;
const PAYLOAD_MIN_KB = parseInt(__ENV.PAYLOAD_MIN_KB || "32");
const PAYLOAD_MAX_KB = parseInt(__ENV.PAYLOAD_MAX_KB || "256");
const PAYLOAD_POOL = [];
for (let i = 0; i < PAYLOAD_POOL_SIZE; i++) {
  const kb = Math.floor(Math.random() * (PAYLOAD_MAX_KB - PAYLOAD_MIN_KB + 1)) + PAYLOAD_MIN_KB;
  PAYLOAD_POOL.push("x".repeat(kb * 1024));
}

function randomPayload() {
  return PAYLOAD_POOL[Math.floor(Math.random() * PAYLOAD_POOL.length)];
}

// Available MCP tools from the math-server (see eks-east1-agent1setup.md)
const MCP_TOOLS = ["add", "multiply"];

function mcpToolCall(sessionId, toolIdx) {
  const toolName = MCP_TOOLS[Math.floor(Math.random() * MCP_TOOLS.length)];
  const t0 = Date.now();
  const res = http.post(
    ENDPOINTS.mcp_via_agentgateway,
    JSON.stringify({
      jsonrpc: "2.0",
      method:  "tools/call",
      id:      `${sessionId}-tool-${toolIdx}`,
      params:  {
        name:      toolName,
        arguments: { a: Math.floor(Math.random() * 1000), b: Math.floor(Math.random() * 1000) },
      },
    }),
    {
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store", "X-Session-Id": sessionId },
      tags:    { call_type: "mcp", agent: "test-math" },
    }
  );
  check(res, { "mcp 200": (r) => r.status === 200 });
  totalCallsAgent1.add(1);
  return Date.now() - t0; // MCP wall time for overhead isolation
}

/**
 * Agent1 LLM call — OpenAI chat-completions format via agentgateway.
 * The gateway's HTTPRoute rewrites /anthropic → /v1/chat/completions and
 * forwards to the Bedrock AgentgatewayBackend in ca-central-1.
 */
function llmCallViaGateway(sessionId, messages) {
  const paddedMessages = messages.map((m, i) =>
    i === messages.length - 1 && m.role === "user"
      ? { ...m, content: m.content + "\n" + randomPayload() }
      : m
  );

  const t0  = Date.now();
  const res = http.post(
    ENDPOINTS.llm_via_agentgateway,
    JSON.stringify({
      model:      BEDROCK_MODEL_ID,
      max_tokens: 256,
      stream:     false,
      messages:   paddedMessages,
    }),
    {
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store", "X-Session-Id": sessionId },
      tags:    { call_type: "llm", agent: "test-math" },
    }
  );
  check(res, { "llm gateway 200": (r) => r.status === 200 });
  return Date.now() - t0;
}

/**
 * Agent2 LLM call — Anthropic Messages format direct to Bedrock Runtime
 * with SigV4 authentication. This replicates what kagent's litellm/boto3
 * Bedrock provider does under the hood.
 */
function llmCallDirectBedrock(sessionId, messages) {
  const paddedMessages = messages.map((m, i) =>
    i === messages.length - 1 && m.role === "user"
      ? { ...m, content: m.content + "\n" + randomPayload() }
      : m
  );

  const body = JSON.stringify({
    anthropic_version: "bedrock-2023-05-31",
    max_tokens:        256,
    messages:          paddedMessages,
  });

  const headers = signedBedrockHeaders(body);
  headers["Cache-Control"] = "no-store";
  headers["X-Session-Id"]  = sessionId;

  const t0  = Date.now();
  const res = http.post(ENDPOINTS.llm_direct_bedrock, body, {
    headers,
    tags: { call_type: "llm", agent: "bedrock-direct-test" },
  });
  check(res, { "llm bedrock 200": (r) => r.status === 200 });
  return Date.now() - t0;
}

// ─── AGENT1 (test-math): agentgateway for LLM + MCP ────────────────────────

export function agent1Session() {
  const sessionId = uuidv4();
  const messages  = [{ role: "user", content: "Benchmark task " + sessionId }];
  const numLoops  = Math.floor(Math.random() * 3) + 2; // 2–4 iterations

  for (let loop = 0; loop < numLoops; loop++) {
    const iterStart = Date.now();
    let mcpTime = 0;

    // ≥2 MCP tool calls in first loop, 1 per subsequent loop
    const numMCP = loop === 0 ? 2 : 1;
    for (let t = 0; t < numMCP; t++) {
      mcpTime += mcpToolCall(sessionId, `${loop}-${t}`);
    }
    mcpLatencyAgent1.add(mcpTime);

    // Feed tool results back into conversation, then 1 LLM call via agentgateway
    messages.push({ role: "user", content: `Tool results from loop ${loop}: [${numMCP} tool calls completed]` });
    const llmTime = llmCallViaGateway(sessionId, messages);
    messages.push({ role: "assistant", content: `LLM response loop ${loop}` });
    totalCallsAgent1.add(1);

    llmWallAgent1.add(llmTime);
    // Subtract both LLM and MCP wall time to isolate gateway routing + HTTP overhead
    loopLatencyAgent1.add(Date.now() - iterStart - llmTime - mcpTime);
    loopIterationCount.add(1);
    sleep(0.1);
  }
  sleep(0.5);
}

// ─── AGENT2 (bedrock-direct-test): direct Bedrock, no agentgateway, no MCP ─

export function agent2Session() {
  const sessionId = uuidv4();
  const messages  = [{ role: "user", content: "Benchmark task " + sessionId }];
  const numLoops  = Math.floor(Math.random() * 3) + 2; // match Agent1 loop distribution

  for (let loop = 0; loop < numLoops; loop++) {
    const iterStart = Date.now();

    // For subsequent loops, append a follow-up user message (loop 0 already has the initial one)
    if (loop > 0) {
      messages.push({ role: "user", content: `Follow-up question loop ${loop}` });
    }

    // No MCP calls — SigV4-signed direct Bedrock call
    const llmTime = llmCallDirectBedrock(sessionId, messages);
    messages.push({ role: "assistant", content: `LLM response loop ${loop}` });
    totalCallsAgent2.add(1);

    llmWallAgent2.add(llmTime);
    loopLatencyAgent2.add(Date.now() - iterStart - llmTime);
    loopIterationCount.add(1);
    sleep(0.1);
  }
  sleep(0.5);
}
