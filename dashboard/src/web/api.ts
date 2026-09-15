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

export interface PendingRiskApproval {
  readonly request_id: string;
  readonly intent: string;
  readonly tool_id: string;
  readonly capability: string;
  readonly requested_category: string;
  readonly allowed_category: string;
  readonly recommended_tool_id: string | null;
  readonly reason: string;
  readonly created_at: string;
  readonly agent_id: string | null;
  readonly run_id: string | null;
  readonly repository: string | null;
  readonly branch: string | null;
  readonly args_hash: string | null;
}

export interface RiskGovernanceState {
  readonly emergency_stop: boolean;
  readonly max_auto_category: string;
  readonly execution_mode: string | null;
  readonly tool_exceptions: readonly string[];
  readonly capability_overrides: Readonly<Record<string, string>>;
  readonly pending_approvals: readonly PendingRiskApproval[];
}

export type RiskGovernanceAction =
  | {
      readonly type: "allow-once";
      readonly request_id: string;
      readonly tool_id: string;
    }
  | {
      readonly type: "tool-exception";
      readonly tool_id: string;
    }
  | {
      readonly type: "capability-risk";
      readonly capability: string;
      readonly category: string;
    }
  | {
      readonly type: "emergency-stop";
      readonly enabled: boolean;
    };

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

export async function fetchRiskGovernance(
  governanceKey: string,
  signal?: AbortSignal,
): Promise<RiskGovernanceState> {
  const response = await fetch("/api/risk-governance", {
    method: "GET",
    ...(signal === undefined ? {} : { signal }),
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${governanceKey}`,
    },
  });
  if (!response.ok) throw new Error(`risk governance unavailable (${response.status})`);
  return parseRiskGovernance((await response.json()) as unknown);
}

export async function applyRiskGovernance(
  governanceKey: string,
  action: RiskGovernanceAction,
): Promise<RiskGovernanceState> {
  const response = await fetch("/api/risk-governance/action", {
    method: "POST",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${governanceKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(action),
  });
  if (!response.ok) throw new Error(`risk governance update failed (${response.status})`);
  return parseRiskGovernance((await response.json()) as unknown);
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

function parseRiskGovernance(value: unknown): RiskGovernanceState {
  if (!isRecord(value)) throw new TypeError("invalid risk governance response");
  if (
    typeof value.emergency_stop !== "boolean" ||
    typeof value.max_auto_category !== "string" ||
    !Array.isArray(value.tool_exceptions) ||
    !value.tool_exceptions.every((item) => typeof item === "string") ||
    !isRecord(value.capability_overrides) ||
    !Object.values(value.capability_overrides).every((item) => typeof item === "string") ||
    !Array.isArray(value.pending_approvals)
  ) {
    throw new TypeError("invalid risk governance response");
  }
  return Object.freeze({
    emergency_stop: value.emergency_stop,
    max_auto_category: value.max_auto_category,
    execution_mode: optionalString(value.execution_mode),
    tool_exceptions: Object.freeze([...value.tool_exceptions]),
    capability_overrides: Object.freeze({ ...value.capability_overrides }),
    pending_approvals: Object.freeze(
      value.pending_approvals.map((item) => {
        if (!isRecord(item)) throw new TypeError("invalid risk approval");
        return Object.freeze({
          request_id: requiredString(item.request_id, "request_id"),
          intent: requiredString(item.intent, "intent"),
          tool_id: requiredString(item.tool_id, "tool_id"),
          capability: requiredString(item.capability, "capability"),
          requested_category: requiredString(item.requested_category, "requested_category"),
          allowed_category: requiredString(item.allowed_category, "allowed_category"),
          recommended_tool_id: optionalString(item.recommended_tool_id),
          reason: requiredString(item.reason, "reason"),
          created_at: requiredString(item.created_at, "created_at"),
          agent_id: optionalString(item.agent_id),
          run_id: optionalString(item.run_id),
          repository: optionalString(item.repository),
          branch: optionalString(item.branch),
          args_hash: optionalString(item.args_hash),
        });
      }),
    ),
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

function optionalString(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  return requiredString(value, "string");
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
