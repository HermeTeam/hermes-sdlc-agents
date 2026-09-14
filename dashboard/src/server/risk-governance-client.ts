const MAX_RESPONSE_BYTES = 131_072;

export interface RiskGovernanceState {
  readonly emergency_stop: boolean;
  readonly max_auto_category: string;
  readonly tool_exceptions: readonly string[];
  readonly capability_overrides: Readonly<Record<string, string>>;
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

  public async apply(action: RiskGovernanceAction): Promise<unknown> {
    const [path, body] = actionRequest(action);
    return this.request(path, {
      method: "POST",
      body: JSON.stringify(body),
    });
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
    )
  ) {
    throw new TypeError("invalid risk governance state");
  }
  return Object.freeze({
    emergency_stop: value.emergency_stop,
    max_auto_category: value.max_auto_category,
    tool_exceptions: Object.freeze([...value.tool_exceptions]),
    capability_overrides: Object.freeze({ ...value.capability_overrides }),
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
