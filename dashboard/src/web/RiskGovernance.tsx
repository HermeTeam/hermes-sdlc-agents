import { useState } from "react";

import {
  applyRiskGovernance,
  fetchRiskGovernance,
  type PendingRiskApproval,
  type RiskGovernanceAction,
  type RiskGovernanceState,
} from "./api.ts";

export function RiskGovernance() {
  const [key, setKey] = useState("");
  const [state, setState] = useState<RiskGovernanceState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const connect = async () => {
    if (key.length < 24) {
      setError("Governance key must contain at least 24 characters.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setState(await fetchRiskGovernance(key));
    } catch {
      setState(null);
      setError("Unable to unlock risk governance. Check the governance key and gateway status.");
    } finally {
      setBusy(false);
    }
  };

  const apply = async (action: RiskGovernanceAction) => {
    setBusy(true);
    setError(null);
    try {
      setState(await applyRiskGovernance(key, action));
    } catch {
      setError("Risk governance update failed. No local UI state was assumed to be applied.");
    } finally {
      setBusy(false);
    }
  };

  if (state === null) {
    return (
      <section className="risk-governance" aria-labelledby="risk-governance-title">
        <div className="role-top">
          <div>
            <p className="eyebrow">Least-privilege authority</p>
            <h2 id="risk-governance-title">Risk governance</h2>
            <p className="muted">
              Read-only runtime monitoring stays public locally. Risk overrides require a separate governance key.
            </p>
          </div>
        </div>
        <div className="governance-unlock">
          <label>
            Governance key
            <input
              type="password"
              autoComplete="off"
              value={key}
              onChange={(event) => setKey(event.target.value)}
              placeholder="Enter governance key"
            />
          </label>
          <button type="button" disabled={busy} onClick={() => void connect()}>
            {busy ? "Unlocking…" : "Unlock controls"}
          </button>
        </div>
        {error && <p className="governance-error" role="alert">{error}</p>}
      </section>
    );
  }

  return (
    <section className="risk-governance" aria-labelledby="risk-governance-title">
      <div className="role-top">
        <div>
          <p className="eyebrow">Least-privilege authority</p>
          <h2 id="risk-governance-title">Risk governance</h2>
          <p className="muted">
            Automatic ceiling: <strong>{state.max_auto_category}</strong> · Pending approvals: {state.pending_approvals.length}
          </p>
        </div>
        <div className="emergency-actions">
          {state.emergency_stop ? (
            <button
              type="button"
              className="emergency-resume"
              disabled={busy}
              onClick={() => void apply({ type: "emergency-stop", enabled: false })}
            >
              Resume governed execution
            </button>
          ) : (
            <button
              type="button"
              className="emergency-stop"
              disabled={busy}
              onClick={() => void apply({ type: "emergency-stop", enabled: true })}
            >
              Запретить все и немедленно
            </button>
          )}
        </div>
      </div>

      {state.emergency_stop && (
        <aside className="emergency-banner" role="alert">
          <strong>Emergency stop active.</strong> The capability resolver exposes no executable tools until governance explicitly resumes execution.
        </aside>
      )}
      {error && <p className="governance-error" role="alert">{error}</p>}

      <div className="risk-grid">
        <section>
          <h3>Pending risky tool requests</h3>
          {state.pending_approvals.length === 0 ? (
            <p className="muted">No tool currently requires human risk authority.</p>
          ) : (
            <div className="approval-list">
              {state.pending_approvals.map((approval) => (
                <ApprovalCard
                  key={approval.request_id}
                  approval={approval}
                  busy={busy}
                  onAction={apply}
                />
              ))}
            </div>
          )}
        </section>

        <aside className="governance-summary">
          <h3>Active policy exceptions</h3>
          <p><strong>{state.tool_exceptions.length}</strong> tool exceptions</p>
          <p><strong>{Object.keys(state.capability_overrides).length}</strong> capability risk overrides</p>
          {state.tool_exceptions.length > 0 && (
            <details>
              <summary>Tool exceptions</summary>
              <ul>
                {state.tool_exceptions.map((tool) => <li key={tool}><code>{tool}</code></li>)}
              </ul>
            </details>
          )}
          {Object.keys(state.capability_overrides).length > 0 && (
            <details>
              <summary>Capability overrides</summary>
              <ul>
                {Object.entries(state.capability_overrides).map(([capability, category]) => (
                  <li key={capability}><code>{capability}</code> → {category}</li>
                ))}
              </ul>
            </details>
          )}
          <button type="button" className="secondary" disabled={busy} onClick={() => void connect()}>
            Refresh governance
          </button>
        </aside>
      </div>
    </section>
  );
}

function ApprovalCard({
  approval,
  busy,
  onAction,
}: {
  approval: PendingRiskApproval;
  busy: boolean;
  onAction: (action: RiskGovernanceAction) => Promise<void>;
}) {
  return (
    <article className="approval-card">
      <div className="approval-header">
        <div>
          <strong>{approval.capability}</strong>
          <p className="muted"><code>{approval.tool_id}</code></p>
        </div>
        <span className="risk-pill">{approval.requested_category}</span>
      </div>
      <p><strong>Agent intent:</strong> {approval.intent}</p>
      <p>{approval.reason}</p>
      {approval.recommended_tool_id && (
        <p className="safer-alternative">
          Safer sufficient alternative: <code>{approval.recommended_tool_id}</code>
        </p>
      )}
      <div className="approval-actions">
        <button
          type="button"
          disabled={busy}
          onClick={() => void onAction({
            type: "allow-once",
            request_id: approval.request_id,
            tool_id: approval.tool_id,
          })}
        >
          Allow once
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => void onAction({ type: "tool-exception", tool_id: approval.tool_id })}
        >
          Add tool exception
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => void onAction({
            type: "capability-risk",
            capability: approval.capability,
            category: approval.allowed_category,
          })}
        >
          Set all {approval.capability} to {approval.allowed_category}
        </button>
      </div>
      <p className="muted">Requested {new Date(approval.created_at).toLocaleString()}</p>
    </article>
  );
}
