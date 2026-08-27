import assert from "node:assert/strict";
import { once } from "node:events";
import { createServer } from "node:http";
import test from "node:test";

import {
  createDashboardApplication,
  listenDashboard,
} from "../src/server/index.ts";
import { OverviewCoordinator } from "../src/server/overview.ts";
import { ROLE_SLUGS } from "../src/shared/roles.ts";
import type {
  DockerContainerSnapshot,
  RoleStatusPayload,
} from "../src/shared/contracts.ts";
import type { RoleSlug } from "../src/shared/roles.ts";
import { DependencyClientError } from "../src/server/http.ts";

function container(role: RoleSlug): DockerContainerSnapshot {
  return {
    containerId: "a".repeat(64),
    name: `hermes-${role}`,
    role,
    image: "i",
    state: "RUNNING",
    statusText: "Up",
    health: "healthy",
    startedAt: null,
    finishedAt: null,
    restartCount: 0,
  };
}

function status(role: RoleSlug, active = 0): RoleStatusPayload {
  return {
    role,
    orchestratorEnabled: true,
    generatedAt: "2026-08-26T00:00:00.000Z",
    queue: { pendingDue: 0, pendingDelayed: 0, active, blocked: 0 },
    items: [],
  };
}

function coordinator(
  overrides: Partial<{
    docker(): Promise<Readonly<Record<RoleSlug, DockerContainerSnapshot>>>;
    role(role: RoleSlug): Promise<RoleStatusPayload>;
    timeoutMs: number;
    cacheTtlMs: number;
  }> = {},
): OverviewCoordinator {
  const snapshot = Object.fromEntries(
    ROLE_SLUGS.map((role) => [role, container(role)]),
  ) as Record<RoleSlug, DockerContainerSnapshot>;
  const cache =
    overrides.cacheTtlMs === undefined
      ? {}
      : { cacheTtlMs: overrides.cacheTtlMs };
  return new OverviewCoordinator({
    docker: { listRoleContainers: overrides.docker ?? (async () => snapshot) },
    roles: { readStatus: overrides.role ?? (async (role) => status(role)) },
    timeoutMs: overrides.timeoutMs ?? 100,
    now: () => new Date("2026-08-26T00:00:00.000Z"),
    ...cache,
  });
}

test("overview aggregates canonical roles concurrently and preserves derivation precedence", async () => {
  const started: RoleSlug[] = [];
  let release: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => (release = resolve));
  const result = coordinator({
    role: async (role) => {
      started.push(role);
      await gate;
      return status(role, role === "planner" ? 1 : 0);
    },
  }).getOverview();
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.deepEqual(started, [...ROLE_SLUGS]);
  release?.();
  const overview = await result;
  assert.equal(overview.partial, false);
  assert.deepEqual(
    overview.roles.map(({ role }) => role),
    ROLE_SLUGS,
  );
  assert.equal(overview.roles[0]?.agentState, "WORKING");
});

test("overview isolates source faults, bounds aggregate deadline, avoids leaks, and coalesces", async () => {
  let calls = 0;
  const overview = coordinator({
    docker: async () => {
      throw new DependencyClientError("unavailable");
    },
    role: async (role) => {
      calls += 1;
      if (role === "release") throw new Error("http://secret.example/raw-body");
      return status(role);
    },
    cacheTtlMs: 1_000,
  });
  const [first, second] = await Promise.all([
    overview.getOverview(),
    overview.getOverview(),
  ]);
  assert.equal(calls, ROLE_SLUGS.length);
  assert.equal(first, second);
  assert.equal(first.partial, true);
  assert.equal(first.roles[0]?.container.state, "UNKNOWN");
  assert.equal(first.roles[4]?.sourceError?.code, "unknown");
  assert.doesNotMatch(JSON.stringify(first), /secret|raw-body|example/);
  const deadline = coordinator({
    role: async () => new Promise<RoleStatusPayload>(() => undefined),
    timeoutMs: 15,
  });
  const timed = await deadline.getOverview();
  assert.equal(timed.partial, true);
  assert.ok(timed.roles.every((role) => role.sourceError?.code === "timeout"));
});

test("real ephemeral HTTP host has only hardened read-only routes and closes cleanly", async () => {
  const dependency = createServer((_request, response) => response.end());
  dependency.listen(0, "127.0.0.1");
  await once(dependency, "listening");
  const app = createDashboardApplication({ overview: coordinator() });
  await listenDashboard(app, 0);
  const address = app.server.address();
  assert.ok(address !== null && typeof address !== "string");
  const base = `http://127.0.0.1:${address.port}`;
  const health = await fetch(`${base}/health`);
  assert.deepEqual(await health.json(), { status: "ok" });
  assert.equal(
    health.headers
      .get("content-security-policy")
      ?.includes("default-src 'self'"),
    true,
  );
  assert.equal(health.headers.get("access-control-allow-origin"), null);
  assert.equal(health.headers.get("server"), null);
  const api = await fetch(`${base}/api/overview`);
  assert.equal(api.status, 200);
  assert.equal(((await api.json()) as { roles: unknown[] }).roles.length, 7);
  const missing = await fetch(`${base}/else`);
  assert.equal(missing.status, 404);
  for (const method of ["HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]) {
    const response = await fetch(`${base}/health`, { method });
    assert.equal(response.status, 405);
    assert.equal(response.headers.get("allow"), "GET");
  }
  await app.close();
  await new Promise<void>((resolve) => dependency.close(() => resolve()));
});
