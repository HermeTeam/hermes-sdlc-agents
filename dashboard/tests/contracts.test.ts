import assert from "node:assert/strict";
import test from "node:test";

import {
  ContractValidationError,
  MAX_QUEUE_ITEMS,
  parseDockerContainerSnapshot,
  parseOverviewResponse,
  parseRoleStatusPayload,
} from "../src/shared/contracts.ts";
import {
  createRoleRegistry,
  parseRoleSlug,
  ROLE_REGISTRY,
  RoleRegistryError,
} from "../src/shared/roles.ts";

interface StatusFixture {
  role: string;
  orchestratorEnabled: boolean;
  generatedAt: string;
  queue: {
    pendingDue: number;
    pendingDelayed: number;
    active: number;
    blocked: number;
  };
  items: Array<{
    assignmentKey: string;
    assignmentStatus: string;
    workItem: {
      provider: string;
      repositoryId: string;
      externalId: string;
      title: string;
      url: string;
    };
    run: {
      hermesRunId: string;
      status: string;
      attemptNumber: number;
      startedAt: string;
    } | null;
    nextRetryAt: string | null;
    blockedReason: string | null;
    lastErrorCode: string | null;
  }>;
}

const validStatus: StatusFixture = {
  role: "planner",
  orchestratorEnabled: true,
  generatedAt: "2026-08-26T06:00:00Z",
  queue: {
    pendingDue: 2,
    pendingDelayed: 1,
    active: 1,
    blocked: 1,
  },
  items: [
    {
      assignmentKey: "github:org/repo:issue:123:planner:v2:abc",
      assignmentStatus: "STARTED",
      workItem: {
        provider: "github",
        repositoryId: "org/repo",
        externalId: "123",
        title: "Add dashboard",
        url: "https://github.com/org/repo/issues/123",
      },
      run: {
        hermesRunId: "run_abc",
        status: "ACTIVE",
        attemptNumber: 1,
        startedAt: "2026-08-26T05:55:00Z",
      },
      nextRetryAt: null,
      blockedReason: null,
      lastErrorCode: null,
    },
  ],
};

function clone<T>(value: T): T {
  return structuredClone(value);
}

function expectContractFailure(operation: () => unknown): void {
  assert.throws(operation, ContractValidationError);
}

test("registry contains exactly the canonical seven roles in stable order", () => {
  assert.deepEqual(
    ROLE_REGISTRY.map((role) => [
      role.slug,
      role.displayName,
      role.serviceName,
    ]),
    [
      ["planner", "Planner", "hermes-planner"],
      ["project-manager", "Project Manager", "hermes-project-manager"],
      ["builder", "Builder", "hermes-builder"],
      ["reviewer", "Reviewer", "hermes-reviewer"],
      ["release", "Release", "hermes-release"],
      ["incident", "Incident", "hermes-incident"],
      ["learning", "Learning", "hermes-learning"],
    ],
  );
  assert.equal(Object.isFrozen(ROLE_REGISTRY), true);
  assert.equal(Object.isFrozen(ROLE_REGISTRY[0]), true);
});

test("registry rejects duplicate, unknown, and missing role definitions", () => {
  const duplicate = clone(ROLE_REGISTRY) as Array<
    (typeof ROLE_REGISTRY)[number]
  >;
  duplicate[1] = duplicate[0]!;
  assert.throws(() => createRoleRegistry(duplicate), RoleRegistryError);
  assert.throws(
    () => createRoleRegistry(ROLE_REGISTRY.slice(0, -1)),
    RoleRegistryError,
  );
  assert.throws(() => parseRoleSlug("operator"), RoleRegistryError);
});

test("parses the TRD role status sample into a frozen sanitized contract", () => {
  const parsed = parseRoleStatusPayload(validStatus);
  assert.deepEqual(parsed, validStatus);
  assert.equal(Object.isFrozen(parsed), true);
  assert.equal(Object.isFrozen(parsed.items), true);
  assert.equal(
    parsed.items[0]?.workItem.url,
    "https://github.com/org/repo/issues/123",
  );
});

test("rejects malformed counters, unsupported statuses, and an oversized item list", () => {
  const malformedCounter = clone(validStatus);
  malformedCounter.queue.active = -1;
  expectContractFailure(() => parseRoleStatusPayload(malformedCounter));

  const unsupportedAssignmentStatus = clone(validStatus);
  unsupportedAssignmentStatus.items[0]!.assignmentStatus = "RUNNING";
  expectContractFailure(() =>
    parseRoleStatusPayload(unsupportedAssignmentStatus),
  );

  const oversized = clone(validStatus);
  oversized.items = Array.from({ length: MAX_QUEUE_ITEMS + 1 }, () =>
    clone(validStatus.items[0]!),
  );
  expectContractFailure(() => parseRoleStatusPayload(oversized));
});

test("rejects unsafe provider URLs and unsupported Docker states", () => {
  const unsafeUrl = clone(validStatus);
  unsafeUrl.items[0]!.workItem.url = "http://github.com/org/repo/issues/123";
  expectContractFailure(() => parseRoleStatusPayload(unsafeUrl));

  const unsafeCredentialsUrl = clone(validStatus);
  unsafeCredentialsUrl.items[0]!.workItem.url =
    "https://token@example.com/private";
  expectContractFailure(() => parseRoleStatusPayload(unsafeCredentialsUrl));

  const docker = {
    containerId: "abc123",
    name: "hermes-planner",
    role: "planner",
    image: "hermes:latest",
    state: "BROKEN",
    statusText: "Unknown",
    health: "unknown",
    startedAt: null,
    finishedAt: null,
    restartCount: 0,
  };
  expectContractFailure(() => parseDockerContainerSnapshot(docker));
});

test("strict validation rejects sensitive and raw fields rather than silently retaining them", () => {
  const withSecret = { ...clone(validStatus), apiServerKey: "canary-secret" };
  expectContractFailure(() => parseRoleStatusPayload(withSecret));

  const withRawPayload = clone(validStatus) as StatusFixture & {
    items: Array<StatusFixture["items"][number] & { rawStatus?: object }>;
  };
  withRawPayload.items[0]!.rawStatus = { token: "canary-secret" };
  expectContractFailure(() => parseRoleStatusPayload(withRawPayload));
});

test("overview requires all roles in canonical order and rejects unknown agent state", () => {
  const overview = {
    generatedAt: "2026-08-26T06:00:00Z",
    partial: false,
    roles: ROLE_REGISTRY.map((role) => ({
      role: role.slug,
      container: {
        state: "RUNNING",
        health: "healthy",
        statusText: "Up 10 minutes",
        restartCount: 0,
      },
      agentState: "IDLE",
      orchestratorEnabled: true,
      queue: { pendingDue: 0, pendingDelayed: 0, active: 0, blocked: 0 },
      items: [],
      sourceError: null,
    })),
  };
  assert.equal(parseOverviewResponse(overview).roles.length, 7);

  const unordered = clone(overview);
  unordered.roles.reverse();
  expectContractFailure(() => parseOverviewResponse(unordered));

  const unsupportedState = clone(overview) as {
    roles: Array<{ agentState: string }>;
  } & typeof overview;
  unsupportedState.roles[0]!.agentState = "HEALTHY";
  expectContractFailure(() => parseOverviewResponse(unsupportedState));
});
