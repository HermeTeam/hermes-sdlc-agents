import assert from "node:assert/strict";
import test from "node:test";

import {
  createDashboardApplication,
  listenDashboard,
} from "../src/server/index.ts";
import type { LangfuseMonitorSnapshot } from "../src/server/langfuse-monitor.ts";

const snapshot: LangfuseMonitorSnapshot = {
  configured: true,
  status: "ok",
  generatedAt: "2026-09-11T15:00:00.000Z",
  baseUrl: "https://cloud.langfuse.com",
  windowMinutes: 60,
  metrics: {
    observations: 42,
    p95LatencyMs: 1234,
    totalTokens: 98765,
    totalCostUsd: 1.2345,
  },
  models: [
    { model: "qwen/qwen3-coder", observations: 40, totalCostUsd: 1.2 },
  ],
  errorCode: null,
};

test("dashboard exposes sanitized Langfuse monitoring server-side", async () => {
  const app = createDashboardApplication({
    overview: { getOverview: async () => ({}) as never },
    langfuseMonitor: { getSnapshot: async () => snapshot },
  });
  try {
    await listenDashboard(app, 0, "127.0.0.1");
    const address = app.server.address();
    assert.notEqual(address, null);
    assert.equal(typeof address, "object");
    if (address === null || typeof address === "string") throw new Error("unexpected server address");
    const response = await fetch(`http://127.0.0.1:${address.port}/api/langfuse-monitor`);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("cache-control"), "no-store");
    const payload = await response.json() as LangfuseMonitorSnapshot;
    assert.equal(payload.status, "ok");
    assert.equal(payload.metrics.observations, 42);
    assert.equal(JSON.stringify(payload).includes("sk-lf-"), false);
  } finally {
    await app.close();
  }
});

test("dashboard reports Langfuse monitor as unconfigured without credentials", async () => {
  const app = createDashboardApplication({
    overview: { getOverview: async () => ({}) as never },
  });
  try {
    await listenDashboard(app, 0, "127.0.0.1");
    const address = app.server.address();
    if (address === null || typeof address === "string") throw new Error("unexpected server address");
    const response = await fetch(`http://127.0.0.1:${address.port}/api/langfuse-monitor`);
    assert.equal(response.status, 200);
    const payload = await response.json() as LangfuseMonitorSnapshot;
    assert.equal(payload.configured, false);
    assert.equal(payload.status, "unconfigured");
  } finally {
    await app.close();
  }
});
