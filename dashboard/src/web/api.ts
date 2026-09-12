import { parseOverviewResponse } from "../shared/contracts.ts";
import type { OverviewResponse } from "../shared/contracts.ts";

export interface LangfuseModelMetric {
  readonly model: string;
  readonly observations: number;
  readonly totalCostUsd: number | null;
}

export interface LangfuseMonitorSnapshot {
  readonly configured: boolean;
  readonly status: "unconfigured" | "ok" | "degraded";
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

export async function fetchOverview(
  signal?: AbortSignal,
): Promise<OverviewResponse> {
  const response = await fetch("/api/overview", {
    method: "GET",
    ...(signal === undefined ? {} : { signal }),
    headers: { Accept: "application/json" },
  });
  if (!response.ok)
    throw new Error("The dashboard overview is temporarily unavailable.");
  return parseOverviewResponse((await response.json()) as unknown);
}

export async function fetchLangfuseMonitor(
  signal?: AbortSignal,
): Promise<LangfuseMonitorSnapshot> {
  const response = await fetch("/api/langfuse-monitor", {
    method: "GET",
    ...(signal === undefined ? {} : { signal }),
    headers: { Accept: "application/json" },
  });
  if (!response.ok)
    throw new Error("Langfuse monitoring is temporarily unavailable.");
  return parseLangfuseMonitor((await response.json()) as unknown);
}

function parseLangfuseMonitor(value: unknown): LangfuseMonitorSnapshot {
  if (!isRecord(value)) throw new TypeError("invalid Langfuse monitor response");
  const status = value.status;
  if (status !== "unconfigured" && status !== "ok" && status !== "degraded") {
    throw new TypeError("invalid Langfuse monitor status");
  }
  const metrics = value.metrics;
  if (!isRecord(metrics) || !Array.isArray(value.models)) {
    throw new TypeError("invalid Langfuse monitor metrics");
  }
  return Object.freeze({
    configured: value.configured === true,
    status,
    generatedAt: requiredString(value.generatedAt, "generatedAt"),
    baseUrl: nullableString(value.baseUrl),
    windowMinutes: requiredNumber(value.windowMinutes, "windowMinutes"),
    metrics: Object.freeze({
      observations: nullableNumber(metrics.observations),
      p95LatencyMs: nullableNumber(metrics.p95LatencyMs),
      totalTokens: nullableNumber(metrics.totalTokens),
      totalCostUsd: nullableNumber(metrics.totalCostUsd),
    }),
    models: Object.freeze(
      value.models.map((item) => {
        if (!isRecord(item)) throw new TypeError("invalid Langfuse model metric");
        return Object.freeze({
          model: requiredString(item.model, "model"),
          observations: requiredNumber(item.observations, "observations"),
          totalCostUsd: nullableNumber(item.totalCostUsd),
        });
      }),
    ),
    errorCode: nullableString(value.errorCode),
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== "string" || value === "") {
    throw new TypeError(`invalid ${field}`);
  }
  return value;
}

function nullableString(value: unknown): string | null {
  return value === null ? null : requiredString(value, "string");
}

function requiredNumber(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new TypeError(`invalid ${field}`);
  }
  return value;
}

function nullableNumber(value: unknown): number | null {
  return value === null ? null : requiredNumber(value, "number");
}
