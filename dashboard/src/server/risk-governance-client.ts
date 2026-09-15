const MAX_RESPONSE_BYTES = 131_072;

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

export class RiskGovernanceClient {
  public constructor(
    private readonly baseUrl: URL,
    private readonly adminKey: string,
    private readonly timeoutMs: number,
    private readonly fetchImplementation: typeof fetch = fetch,
  ) {}

  public async getState(): Promise<RiskGovernanceState> {
    return parseState(
      await this.request("/v1/governance", {
        method: "GET",
      }),
    );
  }

  public async apply(action: RiskGovernanceAction): Promise<RiskGovernanceState> {
    const [path, body] = actionRequest(action);
    return parseState(
      await this.request(path, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    );
  }

  private async request(
    path: string,
    init: Pick<RequestInit, "method" | "body">,
  ): Promise<unknown> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const url = new URL(path, this.baseUrl);
      const response = await this.fetchImplementation(url, {
        ...init,
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${this.adminKey}`,
          ...(init.body === undefined
            ? {}
            : { "Content-Type": "application/json" }),
        },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("risk_governance_unavailable");
      const length = response.headers.get("content-length");
      if (
        length !== null &&
        (!/^[0-9]+$/.test(length) || Number(length) > MAX_RESPONSE_BYTES)
      ) {
        throw new Error("risk_governance_malformed");
      }
      const raw = new Uint8Array(await response.arrayBuffer());
      if (raw.byteLength > MAX_RESPONSE_BYTES)
        throw new Error("risk_governance_malformed");
      return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)) as unknown;
    } catch (error) {
      if (controller.signal.aborted) throw new Error("risk_governance_timeout");
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }
}

function actionRequest(
  action: RiskGovernanceAction,
): readonly [string, Readonly<Record<string, unknown>>] {
  switch (action.type) {
    case "allow-once":
      return [
        "/v1/governance/allow-once",
        { request_id: action.request_id, tool_id: action.tool_id },
      ];
    case "tool-exception":
      return [
        "/v1/governance/tool-exception",
        { tool_id: action.tool_id },
      ];
    case "capability-risk":
      return [
        "/v1/governance/capability-risk",
        { capability: action.capability, category: action.category },
      ];
    case "emergency-stop":
      return ["/v1/governance/emergency-stop", { enabled: action.enabled }];
  }
}

function parseState(value: unknown): RiskGovernanceState {
  if (!isRecord(value)) throw new TypeError("invalid risk governance state");
  if (
    typeof value.emergency_stop !== "boolean" ||
    typeof value.max_auto_category !== "string" ||
    !Array.isArray(value.tool_exceptions) ||
    !value.tool_exceptions.every((item) => typeof item === "string") ||
    !isRecord(value.capability_overrides) ||
    !Object.values(value.capability_overrides).every(
      (item) => typeof item === "string",
    ) ||
    !Array.isArray(value.pending_approvals)
  ) {
    throw new TypeError("invalid risk governance state");
  }
  const capabilityOverrides: Record<string, string> = {};
  for (const [capability, category] of Object.entries(value.capability_overrides)) {
    capabilityOverrides[capability] = requiredString(category);
  }
  return Object.freeze({
    emergency_stop: value.emergency_stop,
    max_auto_category: value.max_auto_category,
    execution_mode: optionalString(value.execution_mode),
    tool_exceptions: Object.freeze([...value.tool_exceptions]),
    capability_overrides: Object.freeze(capabilityOverrides),
    pending_approvals: Object.freeze(value.pending_approvals.map(parseApproval)),
  });
}

function parseApproval(value: unknown): PendingRiskApproval {
  if (!isRecord(value)) throw new TypeError("invalid pending risk approval");
  return Object.freeze({
    request_id: requiredString(value.request_id),
    intent: requiredString(value.intent),
    tool_id: requiredString(value.tool_id),
    capability: requiredString(value.capability),
    requested_category: requiredString(value.requested_category),
    allowed_category: requiredString(value.allowed_category),
    recommended_tool_id: optionalString(value.recommended_tool_id),
    reason: requiredString(value.reason),
    created_at: requiredString(value.created_at),
    agent_id: optionalString(value.agent_id),
    run_id: optionalString(value.run_id),
    repository: optionalString(value.repository),
    branch: optionalString(value.branch),
    args_hash: optionalString(value.args_hash),
  });
}

function requiredString(value: unknown): string {
  if (typeof value !== "string" || value.length === 0)
    throw new TypeError("expected string");
  return value;
}

function optionalString(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  return requiredString(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
