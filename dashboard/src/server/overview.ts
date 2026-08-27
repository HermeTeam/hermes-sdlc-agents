import { parseOverviewResponse } from "../shared/contracts.ts";
import { ROLE_SLUGS } from "../shared/roles.ts";
import type {
  DockerContainerSnapshot,
  OverviewResponse,
  QueueCounters,
  RoleStatusPayload,
  SourceErrorCode,
} from "../shared/contracts.ts";
import type { RoleSlug } from "../shared/roles.ts";
import { DependencyClientError } from "./http.ts";
import { deriveAgentState } from "./status-derivation.ts";

export interface DockerOverviewSource {
  listRoleContainers(): Promise<
    Readonly<Record<RoleSlug, DockerContainerSnapshot>>
  >;
}

export interface RoleOverviewSource {
  readStatus(role: RoleSlug): Promise<RoleStatusPayload>;
}

export interface OverviewCoordinatorOptions {
  readonly docker: DockerOverviewSource;
  readonly roles: RoleOverviewSource;
  readonly timeoutMs: number;
  readonly now?: () => Date;
  readonly cacheTtlMs?: number;
}

interface SourceSuccess<T> {
  readonly ok: true;
  readonly value: T;
}

interface SourceFailure {
  readonly ok: false;
  readonly code: SourceErrorCode;
}

type SourceResult<T> = SourceSuccess<T> | SourceFailure;

const EMPTY_QUEUE: QueueCounters = Object.freeze({
  pendingDue: 0,
  pendingDelayed: 0,
  active: 0,
  blocked: 0,
});
const MAX_CACHE_TTL_MS = 2_000;

export class OverviewCoordinator {
  readonly #docker: DockerOverviewSource;
  readonly #roles: RoleOverviewSource;
  readonly #timeoutMs: number;
  readonly #now: () => Date;
  readonly #cacheTtlMs: number;
  #inFlight: Promise<OverviewResponse> | null = null;
  #cached: {
    readonly expiresAt: number;
    readonly value: OverviewResponse;
  } | null = null;

  public constructor(options: OverviewCoordinatorOptions) {
    if (!Number.isSafeInteger(options.timeoutMs) || options.timeoutMs < 1) {
      throw new TypeError("timeoutMs must be a positive safe integer");
    }
    if (
      options.cacheTtlMs !== undefined &&
      (!Number.isSafeInteger(options.cacheTtlMs) ||
        options.cacheTtlMs < 0 ||
        options.cacheTtlMs > MAX_CACHE_TTL_MS)
    ) {
      throw new TypeError(
        "cacheTtlMs must be between zero and 2000 milliseconds",
      );
    }
    this.#docker = options.docker;
    this.#roles = options.roles;
    this.#timeoutMs = options.timeoutMs;
    this.#now = options.now ?? (() => new Date());
    this.#cacheTtlMs = options.cacheTtlMs ?? 0;
  }

  public getOverview(): Promise<OverviewResponse> {
    const now = Date.now();
    if (this.#cached !== null && this.#cached.expiresAt > now) {
      return Promise.resolve(this.#cached.value);
    }
    if (this.#inFlight !== null) return this.#inFlight;
    const pending = this.#collect().then((value) => {
      if (this.#cacheTtlMs > 0) {
        this.#cached = Object.freeze({
          expiresAt: Date.now() + this.#cacheTtlMs,
          value,
        });
      }
      return value;
    });
    this.#inFlight = pending;
    void pending.finally(() => {
      if (this.#inFlight === pending) this.#inFlight = null;
    });
    return pending;
  }

  async #collect(): Promise<OverviewResponse> {
    const deadline = new AggregateDeadline(this.#timeoutMs);
    const docker = deadline.limit(this.#docker.listRoleContainers());
    const statuses = Object.fromEntries(
      ROLE_SLUGS.map((role) => [
        role,
        deadline.limit(this.#roles.readStatus(role)),
      ]),
    ) as Record<RoleSlug, Promise<SourceResult<RoleStatusPayload>>>;
    const [dockerResult, ...roleResults] = await Promise.all([
      docker,
      ...ROLE_SLUGS.map((role) => statuses[role]),
    ]);
    const response = {
      generatedAt: this.#now().toISOString(),
      partial: !dockerResult.ok || roleResults.some((result) => !result.ok),
      roles: ROLE_SLUGS.map((role, index) => {
        const roleResult = roleResults[index];
        if (roleResult === undefined) throw new Error("missing role result");
        const container = dockerResult.ok
          ? dockerResult.value[role]
          : unavailableContainer(role);
        const status = roleResult.ok ? roleResult.value : null;
        const statusReadFailed = !roleResult.ok;
        const roleSourceError = !roleResult.ok
          ? createSourceError("role-status", roleResult.code)
          : !dockerResult.ok
            ? createSourceError("docker", dockerResult.code)
            : null;
        return {
          role,
          container: {
            state: container.state,
            health: container.health,
            statusText: container.statusText,
            restartCount: container.restartCount,
          },
          agentState: deriveAgentState({ container, status, statusReadFailed }),
          orchestratorEnabled: status?.orchestratorEnabled ?? false,
          queue: status?.queue ?? EMPTY_QUEUE,
          items: status?.items ?? [],
          sourceError: roleSourceError,
        };
      }),
    };
    try {
      return parseOverviewResponse(response);
    } catch {
      // The coordinator never returns an unvalidated aggregate. This fallback
      // remains a strict contract-shaped partial response.
      return parseOverviewResponse({
        generatedAt: this.#now().toISOString(),
        partial: true,
        roles: ROLE_SLUGS.map((role) => unavailableRole(role)),
      });
    } finally {
      deadline.close();
    }
  }
}

class AggregateDeadline {
  readonly #timer: ReturnType<typeof setTimeout>;
  readonly #timeout: Promise<SourceFailure>;

  public constructor(timeoutMs: number) {
    let expire: ((value: SourceFailure) => void) | undefined;
    this.#timeout = new Promise<SourceFailure>((resolve) => {
      expire = resolve;
    });
    this.#timer = setTimeout(
      () => expire?.({ ok: false, code: "timeout" }),
      timeoutMs,
    );
  }

  public async limit<T>(operation: Promise<T>): Promise<SourceResult<T>> {
    const settled: Promise<SourceResult<T>> = operation.then(
      (value): SourceResult<T> => ({ ok: true, value }),
      (error: unknown): SourceResult<T> => ({
        ok: false,
        code: errorCode(error),
      }),
    );
    return Promise.race([settled, this.#timeout]);
  }

  public close(): void {
    clearTimeout(this.#timer);
  }
}

function errorCode(error: unknown): SourceErrorCode {
  return error instanceof DependencyClientError ? error.code : "unknown";
}

function createSourceError(
  source: "docker" | "role-status",
  code: SourceErrorCode,
): {
  readonly source: "docker" | "role-status";
  readonly code: SourceErrorCode;
  readonly message: string;
} {
  return Object.freeze({ source, code, message: "Source data is unavailable" });
}

function unavailableContainer(role: RoleSlug): DockerContainerSnapshot {
  return Object.freeze({
    containerId: `unknown:${role}`,
    name: `hermes-${role}`,
    role,
    image: "unknown",
    state: "UNKNOWN",
    statusText: "Container state unavailable",
    health: "unknown",
    startedAt: null,
    finishedAt: null,
    restartCount: 0,
  });
}

function unavailableRole(role: RoleSlug): object {
  const container = unavailableContainer(role);
  return {
    role,
    container: {
      state: container.state,
      health: container.health,
      statusText: container.statusText,
      restartCount: 0,
    },
    agentState: "UNKNOWN",
    orchestratorEnabled: false,
    queue: EMPTY_QUEUE,
    items: [],
    sourceError: createSourceError("docker", "unknown"),
  };
}
