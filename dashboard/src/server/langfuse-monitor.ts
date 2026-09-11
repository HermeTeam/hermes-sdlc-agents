import process from "node:process";

export type LangfuseMonitorStatus = "unconfigured" | "ok" | "degraded";

export interface LangfuseModelMetric {
  readonly model: string;
  readonly observations: number;
  readonly totalCostUsd: number | null;
}

export interface LangfuseMonitorSnapshot {
  readonly configured: boolean;
  readonly status: LangfuseMonitorStatus;
  readonly generatedAt: string;
  readonly baseUrl: string | null;
  readonly windowMinutes: number;
  readonly metrics: {
    readonly observations: number | null;
    readonly p95LatencyMs: number | null;
    readonly totalTokens: number | null;
    readonly totalCostUsd: number | null;
  };
  readonly models: readonly LangfuseModelMetric[];
  readonly errorCode: string | null;
}

export interface LangfuseMonitorOptions {
  readonly baseUrl: URL;
  readonly publicKey: string;
  readonly secretKey: string;
  readonly windowMinutes: number;
  readonly timeoutMs: number;
  readonly fetchImpl?: typeof fetch;
}

type Environment = Readonly<Record<string, string | undefined>>;

const DEFAULT_BASE_URL = "https://cloud.langfuse.com";
const DEFAULT_WINDOW_MINUTES = 60;
const DEFAULT_TIMEOUT_MS = 3_000;
const MAX_WINDOW_MINUTES = 24 * 60;
const MAX_TIMEOUT_MS = 15_000;

export class LangfuseMonitor {
  private readonly fetchImpl: typeof fetch;

  public constructor(private readonly options: LangfuseMonitorOptions) {
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  public async getSnapshot(): Promise<LangfuseMonitorSnapshot> {
    const generatedAt = new Date().toISOString();
    const to = new Date();
    const from = new Date(to.getTime() - this.options.windowMinutes * 60_000);
    try {
      const [summaryRows, modelRows] = await Promise.all([
        this.queryMetrics({
          view: "observations",
          metrics: [
            { measure: "count", aggregation: "count" },
            { measure: "latency", aggregation: "p95" },
            { measure: "totalTokens", aggregation: "sum" },
            { measure: "totalCost", aggregation: "sum" },
          ],
          dimensions: [],
          filters: [],
          fromTimestamp: from.toISOString(),
          toTimestamp: to.toISOString(),
          config: { row_limit: 1 },
        }),
        this.queryMetrics({
          view: "observations",
          metrics: [
            { measure: "count", aggregation: "count" },
            { measure: "totalCost", aggregation: "sum" },
          ],
          dimensions: [{ field: "providedModelName" }],
          filters: [],
          fromTimestamp: from.toISOString(),
          toTimestamp: to.toISOString(),
          orderBy: [{ field: "sum_totalCost", direction: "desc" }],
          config: { row_limit: 8 },
        }),
      ]);
      const summary = summaryRows[0] ?? {};
      return Object.freeze({
        configured: true,
        status: "ok",
        generatedAt,
        baseUrl: this.options.baseUrl.toString().replace(/\/$/, ""),
        windowMinutes: this.options.windowMinutes,
        metrics: Object.freeze({
          observations: metricNumber(summary, "count_count"),
          p95LatencyMs: metricNumber(summary, "p95_latency"),
          totalTokens: metricNumber(summary, "sum_totalTokens"),
          totalCostUsd: metricNumber(summary, "sum_totalCost"),
        }),
        models: Object.freeze(
          modelRows
            .map((row) => ({
              model: metricString(row, "providedModelName") ?? "unknown",
              observations: metricNumber(row, "count_count") ?? 0,
              totalCostUsd: metricNumber(row, "sum_totalCost"),
            }))
            .filter((row) => row.observations > 0),
        ),
        errorCode: null,
      });
    } catch {
      return degradedSnapshot(
        this.options.baseUrl,
        this.options.windowMinutes,
        generatedAt,
      );
    }
  }

  private async queryMetrics(query: Readonly<Record<string, unknown>>): Promise<readonly Record<string, unknown>[]> {
    const endpoint = new URL("api/public/v2/metrics", ensureTrailingSlash(this.options.baseUrl));
    endpoint.searchParams.set("query", JSON.stringify(query));
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.options.timeoutMs);
    try {
      const authorization = Buffer.from(
        `${this.options.publicKey}:${this.options.secretKey}`,
        "utf8",
      ).toString("base64");
      const response = await this.fetchImpl(endpoint, {
        method: "GET",
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          Authorization: `Basic ${authorization}`,
        },
      });
      if (!response.ok) throw new Error("langfuse metrics request failed");
      const payload = (await response.json()) as unknown;
      if (!isRecord(payload) || !Array.isArray(payload.data)) {
        throw new Error("invalid Langfuse metrics response");
      }
      return payload.data.filter(isRecord);
    } finally {
      clearTimeout(timer);
    }
  }
}

export function createLangfuseMonitorFromEnvironment(
  environment: Environment = process.env,
): LangfuseMonitor | null {
  const publicKey = environment.LANGFUSE_MONITOR_PUBLIC_KEY?.trim() ?? "";
  const secretKey = environment.LANGFUSE_MONITOR_SECRET_KEY?.trim() ?? "";
  if (!publicKey || !secretKey) return null;
  const baseUrl = parseBaseUrl(
    environment.LANGFUSE_MONITOR_BASE_URL?.trim() || DEFAULT_BASE_URL,
  );
  const windowMinutes = parseBoundedInteger(
    environment.LANGFUSE_MONITOR_WINDOW_MINUTES,
    DEFAULT_WINDOW_MINUTES,
    MAX_WINDOW_MINUTES,
    "LANGFUSE_MONITOR_WINDOW_MINUTES",
  );
  const timeoutMs = parseBoundedInteger(
    environment.LANGFUSE_MONITOR_TIMEOUT_MS,
    DEFAULT_TIMEOUT_MS,
    MAX_TIMEOUT_MS,
    "LANGFUSE_MONITOR_TIMEOUT_MS",
  );
  return new LangfuseMonitor({
    baseUrl,
    publicKey,
    secretKey,
    windowMinutes,
    timeoutMs,
  });
}

export function unconfiguredLangfuseSnapshot(
  windowMinutes = DEFAULT_WINDOW_MINUTES,
): LangfuseMonitorSnapshot {
  return Object.freeze({
    configured: false,
    status: "unconfigured",
    generatedAt: new Date().toISOString(),
    baseUrl: null,
    windowMinutes,
    metrics: Object.freeze({
      observations: null,
      p95LatencyMs: null,
      totalTokens: null,
      totalCostUsd: null,
    }),
    models: Object.freeze([]),
    errorCode: null,
  });
}

function degradedSnapshot(
  baseUrl: URL,
  windowMinutes: number,
  generatedAt: string,
): LangfuseMonitorSnapshot {
  return Object.freeze({
    configured: true,
    status: "degraded",
    generatedAt,
    baseUrl: baseUrl.toString().replace(/\/$/, ""),
    windowMinutes,
    metrics: Object.freeze({
      observations: null,
      p95LatencyMs: null,
      totalTokens: null,
      totalCostUsd: null,
    }),
    models: Object.freeze([]),
    errorCode: "langfuse_unavailable",
  });
}

function parseBaseUrl(value: string): URL {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new TypeError("LANGFUSE_MONITOR_BASE_URL must be a valid URL");
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username !== "" ||
    url.password !== "" ||
    url.search !== "" ||
    url.hash !== ""
  ) {
    throw new TypeError("LANGFUSE_MONITOR_BASE_URL must be an http(s) URL without credentials, query or fragment");
  }
  return url;
}

function parseBoundedInteger(
  value: string | undefined,
  fallback: number,
  maximum: number,
  name: string,
): number {
  if (value === undefined || value.trim() === "") return fallback;
  if (!/^[1-9][0-9]*$/.test(value)) {
    throw new TypeError(`${name} must be a positive integer`);
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed > maximum) {
    throw new TypeError(`${name} exceeds its supported bound`);
  }
  return parsed;
}

function ensureTrailingSlash(url: URL): URL {
  const normalized = new URL(url.toString());
  if (!normalized.pathname.endsWith("/")) normalized.pathname += "/";
  return normalized;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function metricNumber(row: Record<string, unknown>, key: string): number | null {
  const value = row[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function metricString(row: Record<string, unknown>, key: string): string | null {
  const value = row[key];
  return typeof value === "string" && value.trim() !== "" ? value : null;
}
