import { createServer } from "node:http";
import { readFile, realpath, stat } from "node:fs/promises";
import { resolve, sep } from "node:path";
import process from "node:process";
import type { IncomingMessage, Server, ServerResponse } from "node:http";

import { loadDashboardConfig } from "./config.ts";
import { DockerClient } from "./docker-client.ts";
import { OverviewCoordinator } from "./overview.ts";
import { RoleClient } from "./role-client.ts";

const MAX_RESPONSE_BYTES = 131_072;
const MAX_STATIC_BYTES = 4_194_304;
const MAX_REQUEST_BODY_BYTES = 8_192;
const MAX_REQUEST_URL_LENGTH = 2_048;
const DEFAULT_BIND = "127.0.0.1";
const DEFAULT_PORT = 8_080;
const SECURITY_HEADERS = {
  "Content-Security-Policy":
    "default-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'; script-src 'self'; style-src 'self'",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "X-Frame-Options": "DENY",
  "Permissions-Policy":
    "accelerometer=(), camera=(), geolocation=(), microphone=(), payment=(), usb=()",
} as const;
const CONTENT_TYPES: Readonly<Record<string, string>> = {
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".woff2": "font/woff2",
};

export interface DashboardApplication {
  readonly server: Server;
  close(): Promise<void>;
}

export interface DashboardApplicationOptions {
  readonly overview: Pick<OverviewCoordinator, "getOverview">;
  readonly staticRoot?: string;
}

export function createDashboardApplication(
  options: DashboardApplicationOptions,
): DashboardApplication {
  const server = createServer(
    { maxHeaderSize: 8_192, requestTimeout: 5_000, headersTimeout: 5_000 },
    (request, response) => void handleRequest(request, response, options),
  );
  server.on("clientError", (_error, socket) => socket.destroy());
  return Object.freeze({ server, close: () => closeServer(server) });
}

export function validateDashboardBind(
  bind: string,
  containerMode = false,
): string {
  if (["127.0.0.1", "::1", "localhost"].includes(bind)) return bind;
  if (containerMode && bind === "0.0.0.0") return bind;
  throw new TypeError(
    "dashboard bind must be loopback unless validated container mode is enabled",
  );
}

export async function listenDashboard(
  app: DashboardApplication,
  port = DEFAULT_PORT,
  bind = DEFAULT_BIND,
  containerMode = false,
): Promise<void> {
  validateDashboardBind(bind, containerMode);
  if (!Number.isSafeInteger(port) || port < 0 || port > 65_535)
    throw new TypeError("dashboard port must be a valid port");
  await new Promise<void>((resolveListen, reject) => {
    app.server.once("error", reject);
    app.server.listen({ host: bind, port }, () => {
      app.server.off("error", reject);
      resolveListen();
    });
  });
}

async function handleRequest(
  request: IncomingMessage,
  response: ServerResponse,
  options: DashboardApplicationOptions,
): Promise<void> {
  discardRequestBody(request);
  const contentLength = Number(request.headers["content-length"] ?? 0);
  if (
    !Number.isSafeInteger(contentLength) ||
    contentLength > MAX_REQUEST_BODY_BYTES
  )
    return sendJson(response, 413, { error: { code: "request_too_large" } });
  if (request.method !== "GET")
    return sendJson(
      response,
      405,
      { error: { code: "method_not_allowed" } },
      { Allow: "GET" },
    );
  const requestUrl = request.url;
  if (requestUrl === undefined || requestUrl.length > MAX_REQUEST_URL_LENGTH)
    return sendJson(response, 404, { error: { code: "not_found" } });
  let pathname: string;
  try {
    pathname = new URL(requestUrl, "http://dashboard.invalid").pathname;
  } catch {
    return sendJson(response, 404, { error: { code: "not_found" } });
  }
  if (pathname === "/health") return sendJson(response, 200, { status: "ok" });
  if (pathname === "/api/overview" && requestUrl === "/api/overview") {
    try {
      return sendJson(response, 200, await options.overview.getOverview());
    } catch {
      return sendJson(response, 503, {
        error: { code: "overview_unavailable" },
      });
    }
  }
  if (pathname.startsWith("/api/"))
    return sendJson(response, 404, { error: { code: "not_found" } });
  if (
    options.staticRoot !== undefined &&
    (await sendStatic(response, pathname, options.staticRoot))
  )
    return;
  sendJson(response, 404, { error: { code: "not_found" } });
}

async function sendStatic(
  response: ServerResponse,
  pathname: string,
  staticRoot: string,
): Promise<boolean> {
  const relative =
    pathname === "/"
      ? "index.html"
      : pathname.startsWith("/assets/")
        ? pathname.slice(1)
        : null;
  if (
    relative === null ||
    relative.includes("..") ||
    relative.split("/").some((part) => part.startsWith("."))
  )
    return false;
  const extension = relative.slice(relative.lastIndexOf("."));
  if (
    (relative !== "index.html" && !CONTENT_TYPES[extension]) ||
    relative.endsWith(".map")
  )
    return false;
  try {
    const root = await realpath(staticRoot);
    const file = resolve(root, relative);
    if (!file.startsWith(`${root}${sep}`)) return false;
    const details = await stat(file);
    if (!details.isFile() || details.size > MAX_STATIC_BYTES) return false;
    response.writeHead(200, {
      "Content-Type":
        relative === "index.html"
          ? "text/html; charset=utf-8"
          : CONTENT_TYPES[extension]!,
      "Content-Length": String(details.size),
      "Cache-Control":
        relative === "index.html"
          ? "no-store"
          : "public, max-age=31536000, immutable",
      ...SECURITY_HEADERS,
    });
    response.end(await readFile(file));
    return true;
  } catch {
    return false;
  }
}

function discardRequestBody(request: IncomingMessage): void {
  let bytesRead = 0;
  request.on("data", (chunk: Buffer) => {
    bytesRead += chunk.length;
    if (bytesRead > MAX_REQUEST_BODY_BYTES) request.destroy();
  });
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
    ...SECURITY_HEADERS,
    ...extraHeaders,
  });
  response.end(content);
}
function closeServer(server: Server): Promise<void> {
  return new Promise((resolveClose, reject) =>
    server.close((error) =>
      error === undefined ? resolveClose() : reject(error),
    ),
  );
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
  const app = createDashboardApplication({
    overview,
    staticRoot: process.env.DASHBOARD_STATIC_ROOT ?? "dist/web",
  });
  await listenDashboard(
    app,
    Number(process.env.DASHBOARD_PORT ?? DEFAULT_PORT),
    process.env.DASHBOARD_BIND ?? DEFAULT_BIND,
    process.env.DASHBOARD_CONTAINER_MODE === "true",
  );
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
)
  void main().catch(() => (process.exitCode = 1));
