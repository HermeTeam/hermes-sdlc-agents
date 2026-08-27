import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { ROLE_BY_SLUG } from "../shared/roles.ts";
import type {
  AgentState,
  OverviewResponse,
  RoleOverview,
  SanitizedRoleStatusItem,
} from "../shared/contracts.ts";
import { fetchOverview } from "./api.ts";

const POLL_MS = 5_000;
const stateTone = (
  state: string,
): "success" | "warning" | "danger" | "neutral" => {
  const normalized = state.toUpperCase();
  return ["RUNNING", "HEALTHY", "WORKING", "IDLE"].includes(normalized)
    ? "success"
    : ["BLOCKED", "STOPPED", "UNHEALTHY"].includes(normalized)
      ? "danger"
      : ["UNAVAILABLE", "WAITING", "QUEUED", "STARTING", "RESTARTING"].includes(
            normalized,
          )
        ? "warning"
        : "neutral";
};

function displayAgent(state: AgentState): string {
  return state === "WORKING"
    ? "Working"
    : state.charAt(0) + state.slice(1).toLowerCase();
}

function StatusBadge({ label, value }: { label: string; value: string }) {
  const tone = stateTone(value);
  return (
    <span className={`badge ${tone}`}>
      <span aria-hidden="true">●</span>
      {label} · {value}
    </span>
  );
}

function WorkLink({ item }: { item: SanitizedRoleStatusItem }) {
  return (
    <a href={item.workItem.url} target="_blank" rel="noopener noreferrer">
      {item.workItem.title}
    </a>
  );
}

function QueueRow({ item }: { item: SanitizedRoleStatusItem }) {
  return (
    <li className="queue-row">
      <div>
        <div className="queue-title">
          <StatusBadge label="Status" value={item.assignmentStatus} />
          <WorkLink item={item} />
        </div>
        <p>
          {item.workItem.provider} · {item.workItem.externalId}
          {item.run ? ` · run ${item.run.attemptNumber}` : ""}
        </p>
      </div>
      <span>
        {item.nextRetryAt
          ? `Retry ${new Date(item.nextRetryAt).toLocaleTimeString()}`
          : (item.blockedReason ??
            item.lastErrorCode ??
            item.run?.status ??
            item.assignmentStatus)}
      </span>
    </li>
  );
}

function RoleCard({ role }: { role: RoleOverview }) {
  const definition = ROLE_BY_SLUG[role.role];
  const active = role.items.find((item) => item.assignmentStatus === "STARTED");
  const message = role.sourceError
    ? `Queue status unavailable: ${role.sourceError.message}`
    : role.agentState === "BLOCKED"
      ? (active?.blockedReason ??
        role.items.find((item) => item.blockedReason)?.blockedReason ??
        "Blocked work needs investigation.")
      : role.agentState === "WAITING"
        ? "Delayed retry is scheduled."
        : active
          ? undefined
          : "No current work. Healthy agent, empty queue.";
  return (
    <article
      className={`role-card ${stateTone(role.agentState)}`}
      aria-labelledby={`role-${role.role}`}
    >
      <div className="role-main">
        <div className="role-top">
          <div>
            <h3 id={`role-${role.role}`}>{definition.displayName}</h3>
            <p className="muted">{definition.serviceName}</p>
          </div>
          <div className="badges">
            <StatusBadge label="Docker" value={role.container.state} />
            <StatusBadge label="Agent" value={displayAgent(role.agentState)} />
          </div>
        </div>
        <div
          className={`work ${role.sourceError || role.agentState === "BLOCKED" ? "attention" : ""}`}
        >
          <strong>
            {active
              ? "Active work"
              : role.sourceError
                ? "Queue status unavailable"
                : role.agentState === "BLOCKED"
                  ? "Blocked work"
                  : "Current work"}
          </strong>
          {active ? <WorkLink item={active} /> : <p>{message}</p>}
        </div>
        <dl
          className="queue-summary"
          aria-label={`${definition.displayName} queue counts`}
        >
          <div>
            <dt>Active</dt>
            <dd>{role.queue.active}</dd>
          </div>
          <div>
            <dt>Pending</dt>
            <dd>{role.queue.pendingDue}</dd>
          </div>
          <div>
            <dt>Delayed</dt>
            <dd>{role.queue.pendingDelayed}</dd>
          </div>
          <div>
            <dt>Blocked</dt>
            <dd>{role.queue.blocked}</dd>
          </div>
        </dl>
      </div>
      <details>
        <summary>
          View current queue{" "}
          <span>
            {role.items.length} item{role.items.length === 1 ? "" : "s"} ▾
          </span>
        </summary>
        <ul className="queue-list">
          {role.items.length ? (
            role.items.map((item) => (
              <QueueRow key={item.assignmentKey} item={item} />
            ))
          ) : (
            <li className="empty-queue">No current queue items.</li>
          )}
        </ul>
      </details>
    </article>
  );
}

function Summary({ overview }: { overview: OverviewResponse }) {
  const roles = overview.roles;
  const totals = roles.reduce(
    (result, role) => ({
      pending: result.pending + role.queue.pendingDue,
      blocked: result.blocked + role.queue.blocked,
      working: result.working + Number(role.agentState === "WORKING"),
      unavailable:
        result.unavailable + Number(role.agentState === "UNAVAILABLE"),
    }),
    { pending: 0, blocked: 0, working: 0, unavailable: 0 },
  );
  const running = roles.filter(
    (role) => role.container.state === "RUNNING",
  ).length;
  const metrics = [
    ["Containers running", `${running}/7`],
    ["Agents working", String(totals.working)],
    ["Pending work", String(totals.pending)],
    ["Blocked work", String(totals.blocked)],
    ["Unavailable roles", String(totals.unavailable)],
  ];
  return (
    <section className="summary-grid" aria-label="Team summary">
      {metrics.map(([label, value]) => (
        <article className="metric" key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
        </article>
      ))}
    </section>
  );
}

export function App() {
  const query = useQuery({
    queryKey: ["overview"],
    queryFn: ({ signal }) => fetchOverview(signal),
    refetchInterval: POLL_MS,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  });
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "visible") void query.refetch();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [query.refetch]);
  if (query.isPending && !query.data)
    return (
      <main className="shell" aria-busy="true">
        <a className="skip" href="#roles">
          Skip to roles
        </a>
        <header>
          <h1>HermeTeam Dashboard</h1>
        </header>
        <p className="skeleton">Loading local runtime overview…</p>
      </main>
    );
  if (!query.data)
    return (
      <main className="shell full-error" role="alert">
        <h1>HermeTeam Dashboard</h1>
        <p>Unable to load the local runtime overview.</p>
        <button type="button" onClick={() => void query.refetch()}>
          Retry
        </button>
      </main>
    );
  const refreshed = new Date(query.data.generatedAt).toLocaleTimeString();
  return (
    <main className="shell">
      <a className="skip" href="#roles">
        Skip to roles
      </a>
      <header className="topbar">
        <div>
          <h1>HermeTeam Dashboard</h1>
          <p className="muted">Local runtime overview · read-only MVP</p>
        </div>
        <div className="actions">
          <p>
            <strong>Updated {refreshed}</strong>
            <br />
            <span className="muted">Docker &amp; role queues</span>
          </p>
          <button
            type="button"
            disabled={query.isFetching}
            aria-describedby="refresh-note"
            onClick={() => void query.refetch()}
          >
            {query.isFetching ? "Refreshing…" : "Refresh"}
          </button>
          <span id="refresh-note" className="sr-only">
            Request the latest Docker and role queue status.
          </span>
        </div>
      </header>
      {query.data.partial && (
        <aside className="notice" role="status">
          <strong>Partial data.</strong> One or more role sources are
          unavailable; successful role data is still shown.
        </aside>
      )}
      {query.isRefetchError && (
        <aside className="notice stale" role="status">
          <strong>Showing last successful data.</strong> The latest refresh
          failed.
        </aside>
      )}
      <section className="hero">
        <div>
          <p className="eyebrow">Team runtime</p>
          <h2>See agent health before work piles up.</h2>
          <p>Current container health and role-local work queues.</p>
        </div>
        <p className="poll">● Auto-refresh every 5 seconds</p>
      </section>
      <Summary overview={query.data} />
      <section id="roles" aria-labelledby="roles-title">
        <h2 id="roles-title">Agent roles</h2>
        <p className="muted">
          Docker condition and queue state are intentionally shown separately.
        </p>
        <div className="roles">
          {query.data.roles.map((role) => (
            <RoleCard key={role.role} role={role} />
          ))}
        </div>
      </section>
    </main>
  );
}
