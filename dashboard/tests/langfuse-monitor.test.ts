import assert from "node:assert/strict";
import test from "node:test";

import {
  LangfuseMonitor,
  createLangfuseMonitorFromEnvironment,
  unconfiguredLangfuseSnapshot,
} from "../src/server/langfuse-monitor.ts";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

test("Langfuse monitor remains unconfigured until both credentials exist", () => {
  assert.equal(createLangfuseMonitorFromEnvironment({}), null);
  assert.equal(
    createLangfuseMonitorFromEnvironment({
      LANGFUSE_MONITOR_PUBLIC_KEY: "pk-lf-test",
    }),
    null,
  );
  const snapshot = unconfiguredLangfuseSnapshot();
  assert.equal(snapshot.configured, false);
  assert.equal(snapshot.status, "unconfigured");
  assert.equal(snapshot.metrics.observations, null);
});

test("Langfuse monitor queries bounded v2 metrics server-side and normalizes numeric strings", async () => {
  let calls = 0;
  const fetchImpl = (async (input: string | URL | Request, init?: RequestInit) => {
    calls += 1;
    const url = new URL(
      typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url,
    );
    assert.equal(url.pathname, "/api/public/v2/metrics");
    assert.match(String(init?.headers && (init.headers as Record<string, string>).Authorization), /^Basic /);
    const query = JSON.parse(url.searchParams.get("query") ?? "{}") as {
      dimensions?: unknown[];
      fromTimestamp?: string;
      toTimestamp?: string;
      config?: { row_limit?: number };
    };
    assert.equal(typeof query.fromTimestamp, "string");
    assert.equal(typeof query.toTimestamp, "string");
    if ((query.dimensions ?? []).length === 0) {
      assert.equal(query.config?.row_limit, 1);
      return jsonResponse({
        data: [
          {
            count_count: "42",
            p95_latency: "1234.5",
            sum_totalTokens: "98765",
            sum_totalCost: "1.2345",
          },
        ],
      });
    }
    assert.equal(query.config?.row_limit, 8);
    return jsonResponse({
      data: [
        {
          providedModelName: "qwen/qwen3-coder",
          count_count: "40",
          sum_totalCost: "1.2",
        },
        {
          providedModelName: "google/gemini-2.5-flash-lite",
          count_count: 2,
          sum_totalCost: 0.0345,
        },
      ],
    });
  }) as typeof fetch;

  const monitor = new LangfuseMonitor({
    baseUrl: new URL("https://cloud.langfuse.com"),
    publicKey: "pk-lf-test",
    secretKey: "sk-lf-test",
    windowMinutes: 60,
    timeoutMs: 1_000,
    fetchImpl,
  });
  const snapshot = await monitor.getSnapshot();
  assert.equal(calls, 2);
  assert.equal(snapshot.status, "ok");
  assert.equal(snapshot.configured, true);
  assert.equal(snapshot.metrics.observations, 42);
  assert.equal(snapshot.metrics.p95LatencyMs, 1234.5);
  assert.equal(snapshot.metrics.totalTokens, 98765);
  assert.equal(snapshot.metrics.totalCostUsd, 1.2345);
  assert.equal(snapshot.models[0]?.model, "qwen/qwen3-coder");
  assert.equal(snapshot.models[0]?.observations, 40);
});

test("Langfuse monitor degrades without leaking upstream errors", async () => {
  const fetchImpl = (async () => {
    throw new Error("secret upstream diagnostic");
  }) as typeof fetch;
  const monitor = new LangfuseMonitor({
    baseUrl: new URL("https://cloud.langfuse.com"),
    publicKey: "pk-lf-test",
    secretKey: "sk-lf-test",
    windowMinutes: 30,
    timeoutMs: 100,
    fetchImpl,
  });
  const snapshot = await monitor.getSnapshot();
  assert.equal(snapshot.status, "degraded");
  assert.equal(snapshot.errorCode, "langfuse_unavailable");
  assert.equal(JSON.stringify(snapshot).includes("secret upstream diagnostic"), false);
});

test("Langfuse monitor rejects unsafe base URLs and oversized windows", () => {
  assert.throws(
    () =>
      createLangfuseMonitorFromEnvironment({
        LANGFUSE_MONITOR_PUBLIC_KEY: "pk-lf-test",
        LANGFUSE_MONITOR_SECRET_KEY: "sk-lf-test",
        LANGFUSE_MONITOR_BASE_URL: "https://user:pass@example.com",
      }),
    /BASE_URL/,
  );
  assert.throws(
    () =>
      createLangfuseMonitorFromEnvironment({
        LANGFUSE_MONITOR_PUBLIC_KEY: "pk-lf-test",
        LANGFUSE_MONITOR_SECRET_KEY: "sk-lf-test",
        LANGFUSE_MONITOR_WINDOW_MINUTES: "999999",
      }),
    /WINDOW_MINUTES/,
  );
});
