import { parseDockerContainerSnapshot } from "../shared/contracts.ts";
import { isRoleSlug, ROLE_BY_SLUG, ROLE_SLUGS } from "../shared/roles.ts";
import type { DockerContainerSnapshot } from "../shared/contracts.ts";
import type { RoleSlug } from "../shared/roles.ts";
import { DependencyClientError, fetchJson } from "./http.ts";
import type { FetchImplementation } from "./http.ts";

export { DependencyClientError as DockerClientError } from "./http.ts";

export interface DockerClientOptions {
  readonly proxyUrl: URL;
  readonly timeoutMs: number;
  readonly fetchImplementation?: FetchImplementation;
}

interface DockerListEntry {
  readonly id: string;
  readonly role: RoleSlug;
  readonly statusText: string;
}

export class DockerClient {
  readonly #proxyUrl: URL;
  readonly #timeoutMs: number;
  readonly #fetch: FetchImplementation;

  public constructor(options: DockerClientOptions) {
    this.#proxyUrl = new URL(options.proxyUrl);
    this.#timeoutMs = options.timeoutMs;
    this.#fetch = options.fetchImplementation ?? fetch;
  }

  public async listRoleContainers(): Promise<
    Readonly<Record<RoleSlug, DockerContainerSnapshot>>
  > {
    const listUrl = new URL("/containers/json", this.#proxyUrl);
    listUrl.searchParams.set("all", "true");
    listUrl.searchParams.set(
      "filters",
      JSON.stringify({ label: ["hermeteam.agent=true"] }),
    );
    const payload = await fetchJson(this.#fetch, listUrl, this.#timeoutMs);
    const entries = parseList(payload);
    const snapshots = new Map<RoleSlug, DockerContainerSnapshot>();
    for (const entry of entries) {
      const inspectUrl = new URL(
        `/containers/${encodeURIComponent(entry.id)}/json`,
        this.#proxyUrl,
      );
      const inspected = await fetchJson(
        this.#fetch,
        inspectUrl,
        this.#timeoutMs,
      );
      snapshots.set(entry.role, normalizeInspect(inspected, entry));
    }
    return Object.freeze(
      Object.fromEntries(
        ROLE_SLUGS.map((role) => [
          role,
          snapshots.get(role) ?? missingSnapshot(role),
        ]),
      ) as Record<RoleSlug, DockerContainerSnapshot>,
    );
  }
}

function parseList(payload: unknown): readonly DockerListEntry[] {
  if (!Array.isArray(payload)) {
    throw new DependencyClientError("malformed_response");
  }
  const entries: DockerListEntry[] = [];
  const roles = new Set<RoleSlug>();
  for (const value of payload) {
    const record = object(value);
    const labels = optionalObject(record.Labels);
    if (labels["hermeteam.agent"] !== "true") {
      continue;
    }
    const role = labels["hermeteam.role"];
    if (!isRoleSlug(role)) {
      throw new DependencyClientError("malformed_response");
    }
    if (roles.has(role)) {
      throw new DependencyClientError("malformed_response");
    }
    const id = boundedText(record.Id);
    const statusText = boundedText(record.Status);
    if (id === null || !/^[a-f0-9]{12,64}$/.test(id) || statusText === null) {
      throw new DependencyClientError("malformed_response");
    }
    roles.add(role);
    entries.push({ id, role, statusText });
  }
  return entries;
}

function normalizeInspect(
  payload: unknown,
  entry: DockerListEntry,
): DockerContainerSnapshot {
  const record = object(payload);
  const state = object(record.State);
  const config = object(record.Config);
  const labels = optionalObject(config.Labels);
  if (
    record.Id !== entry.id ||
    labels["hermeteam.agent"] !== "true" ||
    labels["hermeteam.role"] !== entry.role
  ) {
    throw new DependencyClientError("malformed_response");
  }
  const name = boundedText(record.Name)?.replace(/^\//, "");
  const image = boundedText(config.Image);
  const status = boundedText(state.Status);
  const restartCount = record.RestartCount;
  if (
    name === undefined ||
    name === "" ||
    image === null ||
    status === null ||
    !Number.isSafeInteger(restartCount) ||
    typeof restartCount !== "number" ||
    restartCount < 0
  ) {
    throw new DependencyClientError("malformed_response");
  }
  const healthValue =
    state.Health === undefined ? "none" : object(state.Health).Status;
  const health =
    healthValue === "healthy" ||
    healthValue === "starting" ||
    healthValue === "unhealthy"
      ? healthValue
      : healthValue === undefined
        ? "none"
        : "unknown";
  const normalizedState = dockerState(status, health);
  const snapshot = {
    containerId: entry.id,
    name,
    role: entry.role,
    image,
    state: normalizedState,
    statusText: entry.statusText,
    health,
    startedAt: timestampOrNull(state.StartedAt),
    finishedAt: timestampOrNull(state.FinishedAt),
    restartCount,
  };
  try {
    return parseDockerContainerSnapshot(snapshot);
  } catch {
    throw new DependencyClientError("malformed_response");
  }
}

function dockerState(
  status: string,
  health: "healthy" | "starting" | "unhealthy" | "none" | "unknown",
): DockerContainerSnapshot["state"] {
  if (status === "restarting") return "RESTARTING";
  if (status === "paused") return "PAUSED";
  if (["created", "exited", "dead"].includes(status)) return "STOPPED";
  if (status !== "running") return "UNKNOWN";
  if (health === "unhealthy") return "UNHEALTHY";
  if (health === "starting") return "STARTING";
  return health === "unknown" ? "UNKNOWN" : "RUNNING";
}

function missingSnapshot(role: RoleSlug): DockerContainerSnapshot {
  return Object.freeze({
    containerId: `missing:${role}`,
    name: ROLE_BY_SLUG[role].serviceName,
    role,
    image: "unknown",
    state: "MISSING",
    statusText: "Container not found",
    health: "unknown",
    startedAt: null,
    finishedAt: null,
    restartCount: 0,
  });
}

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new DependencyClientError("malformed_response");
  return value as Record<string, unknown>;
}

function optionalObject(value: unknown): Record<string, unknown> {
  return value === null || value === undefined ? {} : object(value);
}

function boundedText(value: unknown): string | null {
  return typeof value === "string" &&
    value.length <= 500 &&
    !/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/.test(value)
    ? value
    : null;
}

function timestampOrNull(value: unknown): string | null {
  if (value === "0001-01-01T00:00:00Z" || value === "") return null;
  if (typeof value !== "string" || Number.isNaN(Date.parse(value)))
    throw new DependencyClientError("malformed_response");
  return new Date(value).toISOString();
}
