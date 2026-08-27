import assert from "node:assert/strict";
import test from "node:test";

import {
  DashboardConfigError,
  loadDashboardConfig,
} from "../src/server/config.ts";
import { DockerClient } from "../src/server/docker-client.ts";
import { DependencyClientError } from "../src/server/http.ts";
import { RoleClient } from "../src/server/role-client.ts";
import { deriveAgentState } from "../src/server/status-derivation.ts";
import { ROLE_BY_SLUG } from "../src/shared/roles.ts";
import type {
  DockerContainerSnapshot,
  RoleStatusPayload,
} from "../src/shared/contracts.ts";

const config = loadDashboardConfig({});

function response(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

function status(
  role = "planner",
  overrides: Partial<RoleStatusPayload> = {},
): RoleStatusPayload {
  return {
    role: role as RoleStatusPayload["role"],
    orchestratorEnabled: true,
    generatedAt: "2026-08-26T06:00:00Z",
    queue: { pendingDue: 0, pendingDelayed: 0, active: 0, blocked: 0 },
    items: [],
    ...overrides,
  };
}

function container(
  state: DockerContainerSnapshot["state"] = "RUNNING",
  health: DockerContainerSnapshot["health"] = "healthy",
): DockerContainerSnapshot {
  return {
    containerId: "a".repeat(64),
    name: "hermes-planner",
    role: "planner",
    image: "image",
    state,
    statusText: "Up",
    health,
    startedAt: null,
    finishedAt: null,
    restartCount: 0,
  };
}

test("configuration is canonical and fails closed for unsafe or incomplete settings", () => {
  assert.equal(config.dockerProxyUrl.href, "http://docker-socket-proxy:2375/");
  assert.deepEqual(
    config.roleServices,
    Object.fromEntries(
      Object.entries(ROLE_BY_SLUG).map(([role, definition]) => [
        role,
        definition.serviceName,
      ]),
    ),
  );
  for (const environment of [
    { DOCKER_PROXY_URL: "https://docker-socket-proxy:2375" },
    { DOCKER_PROXY_URL: "http://token@docker-socket-proxy:2375" },
    { DOCKER_PROXY_URL: "http://docker-socket-proxy:2375/evil" },
    { ROLE_SERVICES: "planner=hermes-planner" },
    {
      ROLE_SERVICES:
        "planner=hermes-planner,planner=hermes-planner,builder=hermes-builder,reviewer=hermes-reviewer,release=hermes-release,incident=hermes-incident,learning=hermes-learning",
    },
    { ROLE_STATUS_PORT: "0" },
    { DEPENDENCY_TIMEOUT_MS: "0" },
    { DEPENDENCY_TIMEOUT_MS: "4000", OVERVIEW_TIMEOUT_MS: "3000" },
  ])
    assert.throws(() => loadDashboardConfig(environment), DashboardConfigError);
});

test("Docker client only uses list and selected inspect GET routes with an encoded label filter", async () => {
  const requests: Array<{ url: URL; method: string }> = [];
  const id = "a".repeat(64);
  const fetchImplementation: typeof fetch = async (input, init) => {
    const url = new URL(String(input));
    requests.push({ url, method: init?.method ?? "GET" });
    if (url.pathname === "/containers/json")
      return response([
        {
          Id: id,
          Status: "Up 2 minutes",
          Labels: { "hermeteam.agent": "true", "hermeteam.role": "planner" },
        },
        { Id: "b".repeat(64), Status: "ignored", Labels: {} },
      ]);
    return response({
      Id: id,
      Name: "/hermes-planner",
      Config: {
        Image: "hermes:test",
        Labels: { "hermeteam.agent": "true", "hermeteam.role": "planner" },
      },
      State: {
        Status: "running",
        Health: { Status: "healthy" },
        StartedAt: "2026-08-26T06:00:00Z",
        FinishedAt: "0001-01-01T00:00:00Z",
      },
      RestartCount: 2,
    });
  };
  const records = await new DockerClient({
    proxyUrl: config.dockerProxyUrl,
    timeoutMs: 20,
    fetchImplementation,
  }).listRoleContainers();
  assert.equal(records.planner.state, "RUNNING");
  assert.equal(records.builder.state, "MISSING");
  assert.equal(requests.length, 2);
  assert.equal(requests[0]?.method, "GET");
  assert.equal(requests[0]?.url.pathname, "/containers/json");
  assert.deepEqual(
    JSON.parse(requests[0]?.url.searchParams.get("filters") ?? ""),
    { label: ["hermeteam.agent=true"] },
  );
  assert.equal(requests[1]?.url.pathname, `/containers/${id}/json`);
  assert.ok(
    requests.every(
      ({ method, url }) =>
        method === "GET" &&
        (/^\/containers\/json$/.test(url.pathname) ||
          /^\/containers\/[a-f0-9]+\/json$/.test(url.pathname)),
    ),
  );
});

test("Docker client normalizes all Docker conditions and rejects unsafe role observations", async () => {
  const states = [
    ["running", "healthy", "RUNNING"],
    ["running", "starting", "STARTING"],
    ["running", "unhealthy", "UNHEALTHY"],
    ["restarting", undefined, "RESTARTING"],
    ["paused", undefined, "PAUSED"],
    ["exited", undefined, "STOPPED"],
    ["bogus", undefined, "UNKNOWN"],
  ] as const;
  for (const [dockerState, health, expected] of states) {
    const fetchImplementation: typeof fetch = async (input) =>
      new URL(String(input)).pathname === "/containers/json"
        ? response([
            {
              Id: "a".repeat(64),
              Status: "state",
              Labels: {
                "hermeteam.agent": "true",
                "hermeteam.role": "planner",
              },
            },
          ])
        : response({
            Id: "a".repeat(64),
            Name: "/p",
            Config: {
              Image: "i",
              Labels: {
                "hermeteam.agent": "true",
                "hermeteam.role": "planner",
              },
            },
            State: {
              Status: dockerState,
              ...(health === undefined ? {} : { Health: { Status: health } }),
              StartedAt: "2026-08-26T06:00:00Z",
              FinishedAt: "0001-01-01T00:00:00Z",
            },
            RestartCount: 0,
          });
    assert.equal(
      (
        await new DockerClient({
          proxyUrl: config.dockerProxyUrl,
          timeoutMs: 20,
          fetchImplementation,
        }).listRoleContainers()
      ).planner.state,
      expected,
    );
  }
  const badFetch: typeof fetch = async () =>
    response([
      {
        Id: "a".repeat(64),
        Status: "x",
        Labels: { "hermeteam.agent": "true", "hermeteam.role": "unknown" },
      },
    ]);
  await assert.rejects(
    () =>
      new DockerClient({
        proxyUrl: config.dockerProxyUrl,
        timeoutMs: 20,
        fetchImplementation: badFetch,
      }).listRoleContainers(),
    DependencyClientError,
  );
  const duplicateFetch: typeof fetch = async () =>
    response([
      {
        Id: "a".repeat(64),
        Status: "x",
        Labels: { "hermeteam.agent": "true", "hermeteam.role": "planner" },
      },
      {
        Id: "b".repeat(64),
        Status: "x",
        Labels: { "hermeteam.agent": "true", "hermeteam.role": "planner" },
      },
    ]);
  await assert.rejects(
    () =>
      new DockerClient({
        proxyUrl: config.dockerProxyUrl,
        timeoutMs: 20,
        fetchImplementation: duplicateFetch,
      }).listRoleContainers(),
    DependencyClientError,
  );
});

test("role client calls only fixed status route and returns bounded source errors", async () => {
  const urls: URL[] = [];
  const client = new RoleClient({
    roleServices: config.roleServices,
    statusPort: 8650,
    timeoutMs: 20,
    fetchImplementation: async (input) => {
      urls.push(new URL(String(input)));
      return response(status());
    },
  });
  assert.equal((await client.readStatus("planner")).role, "planner");
  assert.equal(urls[0]?.href, "http://hermes-planner:8650/status");
  const mismatch = new RoleClient({
    roleServices: config.roleServices,
    statusPort: 8650,
    timeoutMs: 20,
    fetchImplementation: async () => response(status("builder")),
  });
  await assert.rejects(
    () => mismatch.readStatus("planner"),
    (error: unknown) =>
      error instanceof DependencyClientError &&
      error.message === "malformed_response" &&
      !error.message.includes("hermes"),
  );
  const invalidContent = new RoleClient({
    roleServices: config.roleServices,
    statusPort: 8650,
    timeoutMs: 20,
    fetchImplementation: async () =>
      new Response("secret /private/path", {
        headers: { "content-type": "text/plain" },
      }),
  });
  await assert.rejects(
    () => invalidContent.readStatus("planner"),
    (error: unknown) =>
      error instanceof DependencyClientError &&
      error.message === "malformed_response",
  );
  const busy = new RoleClient({
    roleServices: config.roleServices,
    statusPort: 8650,
    timeoutMs: 20,
    fetchImplementation: async () =>
      response({ error: { code: "sqlite_busy" } }, { status: 503 }),
  });
  await assert.rejects(
    () => busy.readStatus("planner"),
    (error: unknown) =>
      error instanceof DependencyClientError && error.code === "sqlite_busy",
  );
});

test("dependency clients reject oversized, malformed, and cancelled dependency responses", async () => {
  const oversized = new RoleClient({
    roleServices: config.roleServices,
    statusPort: 8650,
    timeoutMs: 20,
    fetchImplementation: async () =>
      new Response("x".repeat(131_073), {
        headers: { "content-type": "application/json" },
      }),
  });
  await assert.rejects(
    () => oversized.readStatus("planner"),
    (error: unknown) =>
      error instanceof DependencyClientError &&
      error.code === "malformed_response",
  );
  const delayed = new RoleClient({
    roleServices: config.roleServices,
    statusPort: 8650,
    timeoutMs: 1,
    fetchImplementation: async (_input, init) =>
      new Promise<Response>((_resolve, reject) =>
        init?.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        ),
      ),
  });
  await assert.rejects(
    () => delayed.readStatus("planner"),
    (error: unknown) =>
      error instanceof DependencyClientError && error.code === "timeout",
  );
});

test("agent-state derivation implements exact precedence without treating running as working", () => {
  const cases: Array<
    [
      DockerContainerSnapshot["state"],
      DockerContainerSnapshot["health"],
      RoleStatusPayload | null,
      boolean,
      string,
    ]
  > = [
    ["MISSING", "unknown", null, false, "UNAVAILABLE"],
    ["STOPPED", "none", status(), false, "UNAVAILABLE"],
    ["UNHEALTHY", "unhealthy", status(), false, "UNAVAILABLE"],
    ["RESTARTING", "none", status(), false, "UNAVAILABLE"],
    ["PAUSED", "none", status(), false, "UNKNOWN"],
    ["STARTING", "starting", status(), false, "UNKNOWN"],
    ["UNKNOWN", "unknown", status(), false, "UNKNOWN"],
    ["RUNNING", "healthy", null, true, "UNAVAILABLE"],
    [
      "RUNNING",
      "healthy",
      status("planner", {
        queue: { pendingDue: 1, pendingDelayed: 1, active: 1, blocked: 1 },
      }),
      false,
      "BLOCKED",
    ],
    [
      "RUNNING",
      "healthy",
      status("planner", {
        queue: { pendingDue: 1, pendingDelayed: 1, active: 1, blocked: 0 },
      }),
      false,
      "WORKING",
    ],
    [
      "RUNNING",
      "healthy",
      status("planner", {
        queue: { pendingDue: 1, pendingDelayed: 1, active: 0, blocked: 0 },
      }),
      false,
      "QUEUED",
    ],
    [
      "RUNNING",
      "healthy",
      status("planner", {
        queue: { pendingDue: 0, pendingDelayed: 1, active: 0, blocked: 0 },
      }),
      false,
      "WAITING",
    ],
    [
      "RUNNING",
      "healthy",
      status("planner", { orchestratorEnabled: false }),
      false,
      "DISABLED",
    ],
    ["RUNNING", "healthy", status(), false, "IDLE"],
  ];
  for (const [state, health, roleStatus, statusReadFailed, expected] of cases)
    assert.equal(
      deriveAgentState({
        container: container(state, health),
        status: roleStatus,
        statusReadFailed,
      }),
      expected,
    );
});
