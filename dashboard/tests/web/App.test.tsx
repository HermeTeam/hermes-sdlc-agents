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
function response(data: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
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
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(await response({}, 503))
      .mockResolvedValueOnce(await response(overview()));
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
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
  it("renders seven roles, metrics, escaped text, and safe provider links", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(await response(overview()));
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
  it("keeps prior data and marks it stale when a manual refresh fails", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(await response(overview()))
      .mockResolvedValueOnce(await response({}, 503));
    renderApp();
    expect(await screen.findByText("Planner")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(
      await screen.findByText(/Showing last successful data/),
    ).toBeInTheDocument();
    expect(screen.getByText("Planner")).toBeInTheDocument();
  });
  it("localizes partial trouble and has a keyboard disclosure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      await response(overview(true)),
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
  it("polls every five seconds only while visible and refetches on resume", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(await response(overview()));
    renderApp();
    await vi.advanceTimersByTimeAsync(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    fireEvent(document, new Event("visibilitychange"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    fireEvent(document, new Event("visibilitychange"));
    await act(async () => {
      await Promise.resolve();
    });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
