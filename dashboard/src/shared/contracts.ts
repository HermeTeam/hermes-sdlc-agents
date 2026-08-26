import { parseRoleSlug, ROLE_SLUGS } from "./roles.ts";
import type { RoleSlug } from "./roles.ts";

export const MAX_QUEUE_ITEMS = 50;
export const MAX_SAFE_TEXT_LENGTH = 500;
export const MAX_ERROR_CODE_LENGTH = 100;

export const CONTAINER_STATES = [
  "RUNNING",
  "STARTING",
  "UNHEALTHY",
  "RESTARTING",
  "PAUSED",
  "STOPPED",
  "MISSING",
  "UNKNOWN",
] as const;
export type ContainerState = (typeof CONTAINER_STATES)[number];

export const DOCKER_HEALTH_STATES = [
  "healthy",
  "starting",
  "unhealthy",
  "none",
  "unknown",
] as const;
export type DockerHealthState = (typeof DOCKER_HEALTH_STATES)[number];

export const ASSIGNMENT_STATUSES = [
  "PENDING",
  "STARTED",
  "COMPLETED",
  "BLOCKED_CONFIG",
  "FAILED_FINAL",
  "CANCELLED",
  "TIMEOUT",
] as const;
export type AssignmentStatus = (typeof ASSIGNMENT_STATUSES)[number];

export const RUN_STATUSES = [
  "ACTIVE",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
  "TIMEOUT",
  "LOST",
  "INVALID_OUTPUT",
  "STALE_OUTPUT",
] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];

export const AGENT_STATES = [
  "UNAVAILABLE",
  "BLOCKED",
  "WORKING",
  "QUEUED",
  "WAITING",
  "DISABLED",
  "IDLE",
  "UNKNOWN",
] as const;
export type AgentState = (typeof AGENT_STATES)[number];

export const SOURCE_ERROR_CODES = [
  "timeout",
  "unavailable",
  "malformed_response",
  "sqlite_busy",
  "unknown",
] as const;
export type SourceErrorCode = (typeof SOURCE_ERROR_CODES)[number];

export interface DockerContainerSnapshot {
  readonly containerId: string;
  readonly name: string;
  readonly role: RoleSlug;
  readonly image: string;
  readonly state: ContainerState;
  readonly statusText: string;
  readonly health: DockerHealthState;
  readonly startedAt: string | null;
  readonly finishedAt: string | null;
  readonly restartCount: number;
}

export interface QueueCounters {
  readonly pendingDue: number;
  readonly pendingDelayed: number;
  readonly active: number;
  readonly blocked: number;
}

export interface SanitizedWorkItem {
  readonly provider: "github" | "gitlab";
  readonly repositoryId: string;
  readonly externalId: string;
  readonly title: string;
  readonly url: string;
}

export interface SanitizedRun {
  readonly hermesRunId: string;
  readonly status: RunStatus;
  readonly attemptNumber: number;
  readonly startedAt: string;
}

export interface SanitizedRoleStatusItem {
  readonly assignmentKey: string;
  readonly assignmentStatus: AssignmentStatus;
  readonly workItem: SanitizedWorkItem;
  readonly run: SanitizedRun | null;
  readonly nextRetryAt: string | null;
  readonly blockedReason: string | null;
  readonly lastErrorCode: string | null;
}

export interface RoleStatusPayload {
  readonly role: RoleSlug;
  readonly orchestratorEnabled: boolean;
  readonly generatedAt: string;
  readonly queue: QueueCounters;
  readonly items: readonly SanitizedRoleStatusItem[];
}

export interface ContainerOverview {
  readonly state: ContainerState;
  readonly health: DockerHealthState;
  readonly statusText: string;
  readonly restartCount: number;
}

export interface SourceError {
  readonly source: "docker" | "role-status";
  readonly code: SourceErrorCode;
  readonly message: string;
}

export interface RoleOverview {
  readonly role: RoleSlug;
  readonly container: ContainerOverview;
  readonly agentState: AgentState;
  readonly orchestratorEnabled: boolean;
  readonly queue: QueueCounters;
  readonly items: readonly SanitizedRoleStatusItem[];
  readonly sourceError: SourceError | null;
}

export interface OverviewResponse {
  readonly generatedAt: string;
  readonly partial: boolean;
  readonly roles: readonly RoleOverview[];
}

export class ContractValidationError extends Error {
  public constructor(message: string) {
    super(message);
    this.name = "ContractValidationError";
  }
}

export function parseRoleStatusPayload(input: unknown): RoleStatusPayload {
  const value = objectAt(input, "role status");
  assertExactKeys(
    value,
    ["role", "orchestratorEnabled", "generatedAt", "queue", "items"],
    "role status",
  );
  return Object.freeze({
    role: parseRole("role status.role", value.role),
    orchestratorEnabled: booleanAt(value, "orchestratorEnabled"),
    generatedAt: timestampAt(value, "generatedAt"),
    queue: parseQueueCounters(value.queue),
    items: parseItems(value.items),
  });
}

export function parseOverviewResponse(input: unknown): OverviewResponse {
  const value = objectAt(input, "overview response");
  assertExactKeys(
    value,
    ["generatedAt", "partial", "roles"],
    "overview response",
  );
  const roles = arrayAt(value, "roles");
  if (roles.length !== ROLE_SLUGS.length) {
    fail(
      `overview response.roles must contain exactly ${ROLE_SLUGS.length} canonical roles`,
    );
  }
  const parsedRoles = roles.map((role, index) =>
    parseRoleOverview(role, index),
  );
  assertCanonicalRoleOrder(
    parsedRoles.map(({ role }) => role),
    "overview response.roles",
  );
  return Object.freeze({
    generatedAt: timestampAt(value, "generatedAt"),
    partial: booleanAt(value, "partial"),
    roles: Object.freeze(parsedRoles),
  });
}

export function parseDockerContainerSnapshot(
  input: unknown,
): DockerContainerSnapshot {
  const value = objectAt(input, "Docker container snapshot");
  assertExactKeys(
    value,
    [
      "containerId",
      "name",
      "role",
      "image",
      "state",
      "statusText",
      "health",
      "startedAt",
      "finishedAt",
      "restartCount",
    ],
    "Docker container snapshot",
  );
  return Object.freeze({
    containerId: identifierAt(value, "containerId"),
    name: safeTextAt(value, "name"),
    role: parseRole("Docker container snapshot.role", value.role),
    image: safeTextAt(value, "image"),
    state: enumAt(value, "state", CONTAINER_STATES),
    statusText: safeTextAt(value, "statusText"),
    health: enumAt(value, "health", DOCKER_HEALTH_STATES),
    startedAt: nullableTimestampAt(value, "startedAt"),
    finishedAt: nullableTimestampAt(value, "finishedAt"),
    restartCount: nonNegativeIntegerAt(value, "restartCount"),
  });
}

export function parseQueueCounters(input: unknown): QueueCounters {
  const value = objectAt(input, "queue");
  assertExactKeys(
    value,
    ["pendingDue", "pendingDelayed", "active", "blocked"],
    "queue",
  );
  return Object.freeze({
    pendingDue: nonNegativeIntegerAt(value, "pendingDue"),
    pendingDelayed: nonNegativeIntegerAt(value, "pendingDelayed"),
    active: nonNegativeIntegerAt(value, "active"),
    blocked: nonNegativeIntegerAt(value, "blocked"),
  });
}

function parseRoleOverview(input: unknown, index: number): RoleOverview {
  const value = objectAt(input, `overview response.roles[${index}]`);
  assertExactKeys(
    value,
    [
      "role",
      "container",
      "agentState",
      "orchestratorEnabled",
      "queue",
      "items",
      "sourceError",
    ],
    `overview response.roles[${index}]`,
  );
  return Object.freeze({
    role: parseRole(`overview response.roles[${index}].role`, value.role),
    container: parseContainerOverview(value.container),
    agentState: enumAt(value, "agentState", AGENT_STATES),
    orchestratorEnabled: booleanAt(value, "orchestratorEnabled"),
    queue: parseQueueCounters(value.queue),
    items: parseItems(value.items),
    sourceError: parseSourceError(value.sourceError),
  });
}

function parseContainerOverview(input: unknown): ContainerOverview {
  const value = objectAt(input, "container overview");
  assertExactKeys(
    value,
    ["state", "health", "statusText", "restartCount"],
    "container overview",
  );
  return Object.freeze({
    state: enumAt(value, "state", CONTAINER_STATES),
    health: enumAt(value, "health", DOCKER_HEALTH_STATES),
    statusText: safeTextAt(value, "statusText"),
    restartCount: nonNegativeIntegerAt(value, "restartCount"),
  });
}

function parseItems(input: unknown): readonly SanitizedRoleStatusItem[] {
  const values = arrayAt({ items: input }, "items");
  if (values.length > MAX_QUEUE_ITEMS) {
    fail(`items must contain at most ${MAX_QUEUE_ITEMS} values`);
  }
  return Object.freeze(values.map((item, index) => parseItem(item, index)));
}

function parseItem(input: unknown, index: number): SanitizedRoleStatusItem {
  const value = objectAt(input, `items[${index}]`);
  assertExactKeys(
    value,
    [
      "assignmentKey",
      "assignmentStatus",
      "workItem",
      "run",
      "nextRetryAt",
      "blockedReason",
      "lastErrorCode",
    ],
    `items[${index}]`,
  );
  return Object.freeze({
    assignmentKey: identifierAt(value, "assignmentKey"),
    assignmentStatus: enumAt(value, "assignmentStatus", ASSIGNMENT_STATUSES),
    workItem: parseWorkItem(value.workItem),
    run: value.run === null ? null : parseRun(value.run),
    nextRetryAt: nullableTimestampAt(value, "nextRetryAt"),
    blockedReason: nullableSafeTextAt(value, "blockedReason"),
    lastErrorCode: nullableErrorCodeAt(value, "lastErrorCode"),
  });
}

function parseWorkItem(input: unknown): SanitizedWorkItem {
  const value = objectAt(input, "work item");
  assertExactKeys(
    value,
    ["provider", "repositoryId", "externalId", "title", "url"],
    "work item",
  );
  const provider = enumAt(value, "provider", ["github", "gitlab"] as const);
  return Object.freeze({
    provider,
    repositoryId: identifierAt(value, "repositoryId"),
    externalId: identifierAt(value, "externalId"),
    title: safeTextAt(value, "title"),
    url: providerUrlAt(value, "url"),
  });
}

function parseRun(input: unknown): SanitizedRun {
  const value = objectAt(input, "run");
  assertExactKeys(
    value,
    ["hermesRunId", "status", "attemptNumber", "startedAt"],
    "run",
  );
  return Object.freeze({
    hermesRunId: identifierAt(value, "hermesRunId"),
    status: enumAt(value, "status", RUN_STATUSES),
    attemptNumber: positiveIntegerAt(value, "attemptNumber"),
    startedAt: timestampAt(value, "startedAt"),
  });
}

function parseSourceError(input: unknown): SourceError | null {
  if (input === null) {
    return null;
  }
  const value = objectAt(input, "source error");
  assertExactKeys(value, ["source", "code", "message"], "source error");
  return Object.freeze({
    source: enumAt(value, "source", ["docker", "role-status"] as const),
    code: enumAt(value, "code", SOURCE_ERROR_CODES),
    message: safeTextAt(value, "message"),
  });
}

function assertCanonicalRoleOrder(
  roles: readonly RoleSlug[],
  path: string,
): void {
  for (const [index, expected] of ROLE_SLUGS.entries()) {
    if (roles[index] !== expected) {
      fail(
        `${path} must use canonical role order; expected ${expected} at index ${index}`,
      );
    }
  }
}

function objectAt(input: unknown, path: string): Record<string, unknown> {
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    fail(`${path} must be an object`);
  }
  return input as Record<string, unknown>;
}

function arrayAt(
  object: Record<string, unknown>,
  key: string,
): readonly unknown[] {
  const value = object[key];
  if (!Array.isArray(value)) {
    fail(`${key} must be an array`);
  }
  return value;
}

function assertExactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
  path: string,
): void {
  const allowed = new Set(keys);
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) {
      fail(`${path} contains unsupported field: ${key}`);
    }
  }
  for (const key of keys) {
    if (!(key in value)) {
      fail(`${path} is missing required field: ${key}`);
    }
  }
}

function parseRole(path: string, value: unknown): RoleSlug {
  try {
    return parseRoleSlug(value);
  } catch {
    fail(`${path} must be a canonical role slug`);
  }
}

function enumAt<const T extends readonly string[]>(
  object: Record<string, unknown>,
  key: string,
  allowed: T,
): T[number] {
  const value = object[key];
  if (typeof value !== "string" || !allowed.includes(value)) {
    fail(`${key} has unsupported value: ${String(value)}`);
  }
  return value as T[number];
}

function booleanAt(object: Record<string, unknown>, key: string): boolean {
  const value = object[key];
  if (typeof value !== "boolean") {
    fail(`${key} must be a boolean`);
  }
  return value;
}

function nonNegativeIntegerAt(
  object: Record<string, unknown>,
  key: string,
): number {
  const value = object[key];
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    fail(`${key} must be a non-negative safe integer`);
  }
  return value;
}

function positiveIntegerAt(
  object: Record<string, unknown>,
  key: string,
): number {
  const value = nonNegativeIntegerAt(object, key);
  if (value < 1) {
    fail(`${key} must be a positive safe integer`);
  }
  return value;
}

function identifierAt(object: Record<string, unknown>, key: string): string {
  const value = safeTextAt(object, key);
  if (value.trim().length === 0) {
    fail(`${key} must not be empty`);
  }
  return value;
}

function safeTextAt(object: Record<string, unknown>, key: string): string {
  const value = object[key];
  if (
    typeof value !== "string" ||
    value.length > MAX_SAFE_TEXT_LENGTH ||
    /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/.test(value)
  ) {
    fail(`${key} must be a bounded plain-text string`);
  }
  return value;
}

function nullableSafeTextAt(
  object: Record<string, unknown>,
  key: string,
): string | null {
  return object[key] === null ? null : safeTextAt(object, key);
}

function nullableErrorCodeAt(
  object: Record<string, unknown>,
  key: string,
): string | null {
  if (object[key] === null) {
    return null;
  }
  const value = safeTextAt(object, key);
  if (value.length > MAX_ERROR_CODE_LENGTH) {
    fail(`${key} must be at most ${MAX_ERROR_CODE_LENGTH} characters`);
  }
  return value;
}

function timestampAt(object: Record<string, unknown>, key: string): string {
  const value = object[key];
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})$/.test(
      value,
    ) ||
    Number.isNaN(Date.parse(value))
  ) {
    fail(`${key} must be an ISO-8601 timestamp with an offset`);
  }
  return value;
}

function nullableTimestampAt(
  object: Record<string, unknown>,
  key: string,
): string | null {
  return object[key] === null ? null : timestampAt(object, key);
}

function providerUrlAt(object: Record<string, unknown>, key: string): string {
  const value = safeTextAt(object, key);
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    fail(`${key} must be an absolute HTTPS URL`);
  }
  if (
    url.protocol !== "https:" ||
    url.hostname.length === 0 ||
    url.username.length > 0 ||
    url.password.length > 0 ||
    url.hash.length > 0
  ) {
    fail(`${key} must be a credential-free HTTPS URL without a fragment`);
  }
  return url.toString();
}

function fail(message: string): never {
  throw new ContractValidationError(message);
}
