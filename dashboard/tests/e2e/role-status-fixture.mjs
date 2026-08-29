import { createServer } from "node:http";

const role = required("ROLE");
const scenario = process.env.SCENARIO ?? "idle";
const canary = "t11-canary-secret-must-never-reach-browser";
const port = Number(process.env.PORT ?? "8650");

const queues = {
  working: { pendingDue: 0, pendingDelayed: 0, active: 1, blocked: 0 },
  queued: { pendingDue: 1, pendingDelayed: 0, active: 0, blocked: 0 },
  waiting: { pendingDue: 0, pendingDelayed: 1, active: 0, blocked: 0 },
  blocked: { pendingDue: 0, pendingDelayed: 0, active: 0, blocked: 1 },
  idle: { pendingDue: 0, pendingDelayed: 0, active: 0, blocked: 0 },
};

function required(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function item(status, suffix) {
  return {
    assignmentKey: `${role}-${suffix}`,
    assignmentStatus: status,
    workItem: {
      provider: "github",
      repositoryId: "hermeteam/dashboard",
      externalId: `#${suffix}`,
      title: `${role} ${status.toLowerCase()} work`,
      url: `https://github.com/hermeteam/dashboard/issues/${suffix}`,
    },
    run:
      status === "STARTED"
        ? {
            hermesRunId: `${role}-run`,
            status: "ACTIVE",
            attemptNumber: 1,
            startedAt: "2026-08-28T00:00:00.000Z",
          }
        : null,
    nextRetryAt: status === "PENDING" ? "2026-08-29T00:00:00.000Z" : null,
    blockedReason:
      status === "BLOCKED_CONFIG" ? "fixture configuration blocked" : null,
    lastErrorCode: status === "BLOCKED_CONFIG" ? "FIXTURE_BLOCKED" : null,
  };
}

function payload() {
  const status =
    scenario === "working"
      ? "STARTED"
      : scenario === "blocked"
        ? "BLOCKED_CONFIG"
        : "PENDING";
  return {
    role,
    orchestratorEnabled: true,
    generatedAt: "2026-08-28T00:00:00.000Z",
    queue: queues[scenario] ?? queues.idle,
    items: scenario === "idle" ? [] : [item(status, scenario)],
  };
}

const server = createServer(async (request, response) => {
  if (request.method !== "GET")
    return response.writeHead(405, { Allow: "GET" }).end();
  if (request.url === "/health") return response.writeHead(200).end("ok");
  if (request.url !== "/status") return response.writeHead(404).end();
  if (scenario === "timeout") return;
  if (scenario === "malformed") {
    return response
      .writeHead(200, { "content-type": "application/json" })
      .end(JSON.stringify({ role, rawFixtureSecret: canary }));
  }
  response
    .writeHead(200, { "content-type": "application/json" })
    .end(JSON.stringify(payload()));
});
server.listen(port, "0.0.0.0");
