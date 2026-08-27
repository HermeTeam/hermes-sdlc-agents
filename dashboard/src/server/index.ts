import { createServer } from "node:http";
import process from "node:process";
import type { IncomingMessage, Server, ServerResponse } from "node:http";

import { loadDashboardConfig } from "./config.ts";
import { DockerClient } from "./docker-client.ts";
import { OverviewCoordinator } from "./overview.ts";
import { RoleClient } from "./role-client.ts";

const MAX_RESPONSE_BYTES = 131_072;
const MAX_REQUEST_URL_LENGTH = 2_048;
const DEFAULT_BIND = "127.0.0.1";
const DEFAULT_PORT = 8_080;

export interface DashboardApplication {
  readonly server: Server;
  close(): Promise<void>;
}

export interface DashboardApplicationOptions {
  readonly overview: Pick<OverviewCoordinator, "getOverview">;
}

export function createDashboardApplication(
  options: DashboardApplicationOptions,
): DashboardApplication {
  const server = createServer(
    { maxHeaderSize: 8_192, requestTimeout: 5_000, headersTimeout: 5_000 },
    (request, response) => handleRequest(request, response, options.overview),
  );
  server.on("clientError", (_error, socket) => {
    socket.destroy();
  });
  return Object.freeze({
    server,
    close: () => closeServer(server),
  });
}

export function validateLoopbackBind(bind: string): string {
  if (!["127.0.0.1", "::1", "localhost"].includes(bind)) {
    throw new TypeError("dashboard bind must be a loopback address");
  }
  return bind;
}

export async function listenDashboard(
  app: DashboardApplication,
  port = DEFAULT_PORT,
  bind = DEFAULT_BIND,
): Promise<void> {
  validateLoopbackBind(bind);
  if (!Number.isSafeInteger(port) || port < 0 || port > 65_535) {
    throw new TypeError("dashboard port must be a valid port");
  }
  await new Promise<void>((resolve, reject) => {
    app.server.once("error", reject);
    app.server.listen({ host: bind, port }, () => {
      app.server.off("error", reject);
      resolve();
    });
  });
}

async function handleRequest(
  request: IncomingMessage,
  response: ServerResponse,
  overview: Pick<OverviewCoordinator, "getOverview">,
): Promise<void> {
  discardRequestBody(request);
  if (request.method !== "GET") {
    sendJson(
      response,
      405,
      { error: { code: "method_not_allowed" } },
      { Allow: "GET" },
    );
    return;
  }
  const url = request.url;
  if (url === undefined || url.length > MAX_REQUEST_URL_LENGTH) {
    sendJson(response, 404, { error: { code: "not_found" } });
    return;
  }
  if (url === "/health") {
    sendJson(response, 200, { status: "ok" });
    return;
  }
  if (url === "/api/overview") {
    try {
      sendJson(response, 200, await overview.getOverview());
    } catch {
      sendJson(response, 503, { error: { code: "overview_unavailable" } });
    }
    return;
  }
  sendJson(response, 404, { error: { code: "not_found" } });
}

function discardRequestBody(request: IncomingMessage): void {
  request.on("error", () => undefined);
  request.resume();
}

function sendJson(
  response: ServerResponse,
  status: number,
  body: unknown,
  extraHeaders: Readonly<Record<string, string>> = {},
): void {
  let content: string;
  try {
    content = JSON.stringify(body);
  } catch {
    content = JSON.stringify({ error: { code: "internal_error" } });
    status = 500;
  }
  if (Buffer.byteLength(content, "utf8") > MAX_RESPONSE_BYTES) {
    content = JSON.stringify({ error: { code: "response_too_large" } });
    status = 503;
  }
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": String(Buffer.byteLength(content, "utf8")),
    "Cache-Control": "no-store",
    "Content-Security-Policy":
      "default-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'; script-src 'self'; style-src 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy":
      "accelerometer=(), camera=(), geolocation=(), microphone=(), payment=(), usb=()",
    ...extraHeaders,
  });
  response.end(content);
}

function closeServer(server: Server): Promise<void> {
  return new Promise((resolve, reject) => {
    server.close((error) => (error === undefined ? resolve() : reject(error)));
  });
}

async function main(): Promise<void> {
  const config = loadDashboardConfig();
  const overview = new OverviewCoordinator({
    docker: new DockerClient({
      proxyUrl: config.dockerProxyUrl,
      timeoutMs: config.dependencyTimeoutMs,
    }),
    roles: new RoleClient({
      roleServices: config.roleServices,
      statusPort: config.roleStatusPort,
      timeoutMs: config.dependencyTimeoutMs,
    }),
    timeoutMs: config.overviewTimeoutMs,
    cacheTtlMs: 2_000,
  });
  const app = createDashboardApplication({ overview });
  await listenDashboard(app);
  let closing = false;
  const shutdown = (): void => {
    if (closing) return;
    closing = true;
    void app.close().finally(() => process.exit(0));
  };
  process.once("SIGTERM", shutdown);
  process.once("SIGINT", shutdown);
}

if (
  process.argv[1] !== undefined &&
  import.meta.url === new URL(`file://${process.argv[1]}`).href
) {
  void main().catch(() => (process.exitCode = 1));
}
