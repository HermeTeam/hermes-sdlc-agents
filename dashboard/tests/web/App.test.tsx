import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../../src/web/App.tsx";

const roleSlugs = [
  "planner",
  "project-manager",
  "builder",
  "reviewer",
  "release",
  "incident",
  "learning",
] as const;
function overview(partial = false) {
  return {
    generatedAt: "2026-08-27T10:00:00Z",
    partial,
    roles: roleSlugs.map((role, index) => ({
      role,
      container: {
        state: index === 5 ? "STOPPED" : "RUNNING",
        health: index === 5 ? "none" : "healthy",
        statusText: "ok",
        restartCount: 0,
      },
      agentState:
        index === 0
          ? "WORKING"
          : index === 1
            ? "BLOCKED"
            : index === 4
              ? "UNAVAILABLE"
              : index === 6
                ? "WAITING"
                : "IDLE",
      orchestratorEnabled: true,
      queue: {
        pendingDue: index === 2 ? 2 : 0,
        pendingDelayed: index === 6 ? 1 : 0,
        active: index === 0 ? 1 : 0,
        blocked: index === 1 ? 1 : 0,
      },
      items:
        index === 0
          ? [
              {
                assignmentKey: "github:org/repo:1",
                assignmentStatus: "STARTED",
                workItem: {
                  provider: "github",
                  repositoryId: "org/repo",
                  externalId: "1",
                  title: "<img src=x onerror=alert(1)> Active work",
                  url: "https://github.com/org/repo/issues/1",
                },
                run: {
                  hermesRunId: "run-1",
                  status: "ACTIVE",
                  attemptNumber: 1,
                  startedAt: "2026-08-27T09:55:00Z",
                },
                nextRetryAt: null,
                blockedReason: null,
                lastErrorCode: null,
              },
            ]
          : [],
      sourceError:
        index === 4
          ? {
              source: "role-status",
              code: "timeout",
              message: "Request timed out",
            }
          : null,
    })),
  };
}
function langfuse(configured = false) {
  return configured
    ? {
        configured: true,
        status: "ok",
        generatedAt: "2026-09-11T15:00:00Z",
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
      }
    : {
        configured: false,
        status: "unconfigured",
        generatedAt: "2026-09-11T15:00:00Z",
        baseUrl: null,
        windowMinutes: 60,
        metrics: {
          observations: null,
          p95LatencyMs: null,
          totalTokens: null,
          totalCostUsd: null,
        },
        models: [],
        errorCode: null,
      };
}
function response(data: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}
function requestPath(input: RequestInfo | URL): string {
  const value = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
  return new URL(value, "http://dashboard.test").pathname;
}
function renderApp() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("dashboard SPA", () => {
  it("shows first-load state, full error, and retry", async () => {
    let overviewCalls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (requestPath(input) === "/api/langfuse-monitor") return response(langfuse());
      overviewCalls += 1;
      return overviewCalls === 1 ? response({}, 503) : response(overview());
    });
    renderApp();
    expect(
      screen.getByText(/Loading local runtime overview/),
    ).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Unable to load/,
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByRole("heading", { name: "Agent roles" }),
    ).toBeInTheDocument();
    expect(overviewCalls).toBe(2);
  });
  it("renders seven roles, metrics, escaped text, and safe provider links", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
      requestPath(input) === "/api/langfuse-monitor"
        ? response(langfuse())
        : response(overview()),
    );
    renderApp();
    expect(await screen.findByText("Planner")).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(12);
    expect(
      screen.getByText("Containers running").parentElement,
    ).toHaveTextContent("6/7");
    fireEvent.click(screen.getAllByText(/View current queue/)[0]!);
    const link = screen.getAllByRole("link", { name: /<img src=x/ })[0]!;
    expect(link).toHaveAttribute(
      "href",
      "https://github.com/org/repo/issues/1",
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(document.querySelector("img")).toBeNull();
    expect(
      screen.queryByRole("button", {
        name: /start|stop|restart|delete|console/i,
      }),
    ).toBeNull();
  });
  it("renders server-side Langfuse metrics without exposing credentials", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
      requestPath(input) === "/api/langfuse-monitor"
        ? response(langfuse(true))
        : response(overview()),
    );
    renderApp();
    expect(await screen.findByRole("heading", { name: "LLM monitoring · Langfuse" })).toBeInTheDocument();
    expect(screen.getByText("Observations").parentElement).toHaveTextContent("42");
    expect(screen.getByText("p95 latency").parentElement).toHaveTextContent("1,234 ms");
    expect(screen.getByText("qwen/qwen3-coder")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Open Langfuse/ });
    expect(link).toHaveAttribute("href", "https://cloud.langfuse.com");
    expect(document.body.textContent).not.toMatch(/pk-lf-|sk-lf-/);
  });
  it("keeps prior data and marks it stale when a manual refresh fails", async () => {
    let overviewCalls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (requestPath(input) === "/api/langfuse-monitor") return response(langfuse());
      overviewCalls += 1;
      return overviewCalls === 1 ? response(overview()) : response({}, 503);
    });
    renderApp();
    expect(await screen.findByText("Planner")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(
      await screen.findByText(/Showing last successful data/),
    ).toBeInTheDocument();
    expect(screen.getByText("Planner")).toBeInTheDocument();
  });
  it("localizes partial trouble and has a keyboard disclosure", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
      requestPath(input) === "/api/langfuse-monitor"
        ? response(langfuse())
        : response(overview(true)),
    );
    renderApp();
    expect(await screen.findByText(/Partial data/)).toBeInTheDocument();
    expect(
      screen.getAllByText(/Queue status unavailable: Request timed out/)[0],
    ).toBeInTheDocument();
    const summary = screen.getAllByText(/View current queue/)[0]!;
    summary.focus();
    fireEvent.click(summary);
    expect(summary.closest("details")).toHaveProperty("open", true);
  });
  it("polls runtime every five seconds only while visible and refetches on resume", async () => {
    vi.useFakeTimers();
    let overviewCalls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (requestPath(input) === "/api/langfuse-monitor") return response(langfuse());
      overviewCalls += 1;
      return response(overview());
    });
    renderApp();
    await vi.advanceTimersByTimeAsync(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(overviewCalls).toBe(2);
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    fireEvent(document, new Event("visibilitychange"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(overviewCalls).toBe(2);
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    fireEvent(document, new Event("visibilitychange"));
    await act(async () => {
      await Promise.resolve();
    });
    expect(overviewCalls).toBe(3);
  });
});
