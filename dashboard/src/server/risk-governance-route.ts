import type { IncomingMessage, ServerResponse } from "node:http";

import type {
  RiskGovernanceAction,
  RiskGovernanceClient,
} from "./risk-governance-client.ts";

const MAX_BODY_BYTES = 8_192;
const SECURITY_HEADERS = {
  "X-Content-Type-Options": "nosniff",
  "Cache-Control": "no-store",
} as const;

export interface RiskGovernanceRouteOptions {
  readonly client: Pick<RiskGovernanceClient, "getState" | "apply">;
  readonly userKey: string;
}

export async function handleRiskGovernanceRoute(
  request: IncomingMessage,
  response: ServerResponse,
  options: RiskGovernanceRouteOptions | undefined,
): Promise<boolean> {
  const requestUrl = request.url ?? "";
  if (!requestUrl.startsWith("/api/risk-governance")) return false;
  if (options === undefined) {
    sendJson(response, 503, { error: { code: "risk_governance_unconfigured" } });
    return true;
  }
  if (request.headers.authorization !== `Bearer ${options.userKey}`) {
    sendJson(response, 401, { error: { code: "unauthorized" } });
    return true;
  }
  try {
    if (request.method === "GET" && requestUrl === "/api/risk-governance") {
      sendJson(response, 200, await options.client.getState());
      return true;
    }
    if (request.method === "POST" && requestUrl === "/api/risk-governance/action") {
      const body = await readJsonBody(request);
      const action = parseAction(body);
      sendJson(response, 200, await options.client.apply(action));
      return true;
    }
    sendJson(response, 405, { error: { code: "method_not_allowed" } });
    return true;
  } catch (error) {
    if (error instanceof RequestValidationError) {
      sendJson(response, 400, { error: { code: "invalid_request" } });
      return true;
    }
    sendJson(response, 503, { error: { code: "risk_governance_unavailable" } });
    return true;
  }
}

class RequestValidationError extends Error {}

async function readJsonBody(request: IncomingMessage): Promise<unknown> {
  const length = Number(request.headers["content-length"] ?? 0);
  if (!Number.isSafeInteger(length) || length <= 0 || length > MAX_BODY_BYTES) {
    throw new RequestValidationError();
  }
  const chunks: Buffer[] = [];
  let total = 0;
  for await (const chunk of request) {
    const value = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    total += value.length;
    if (total > MAX_BODY_BYTES) throw new RequestValidationError();
    chunks.push(value);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8")) as unknown;
  } catch {
    throw new RequestValidationError();
  }
}

function parseAction(input: unknown): RiskGovernanceAction {
  if (!isRecord(input) || typeof input.type !== "string")
    throw new RequestValidationError();
  switch (input.type) {
    case "allow-once":
      return {
        type: "allow-once",
        request_id: boundedString(input.request_id, 100),
        tool_id: boundedString(input.tool_id, 300),
      };
    case "tool-exception":
      return {
        type: "tool-exception",
        tool_id: boundedString(input.tool_id, 300),
      };
    case "capability-risk":
      return {
        type: "capability-risk",
        capability: boundedString(input.capability, 160),
        category: parseCategory(input.category),
      };
    case "emergency-stop":
      if (typeof input.enabled !== "boolean") throw new RequestValidationError();
      return { type: "emergency-stop", enabled: input.enabled };
    default:
      throw new RequestValidationError();
  }
}

function parseCategory(value: unknown): string {
  const category = boundedString(value, 20).toUpperCase();
  if (!["SAFE", "LOW", "MEDIUM", "HIGH", "CRITICAL"].includes(category))
    throw new RequestValidationError();
  return category;
}

function boundedString(value: unknown, max: number): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > max ||
    /[\u0000-\u001f\u007f]/.test(value)
  ) {
    throw new RequestValidationError();
  }
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function sendJson(response: ServerResponse, status: number, body: unknown): void {
  const content = JSON.stringify(body);
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": String(Buffer.byteLength(content, "utf8")),
    ...SECURITY_HEADERS,
  });
  response.end(content);
}
