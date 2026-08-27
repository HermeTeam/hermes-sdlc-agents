import type {
  AgentState,
  DockerContainerSnapshot,
  RoleStatusPayload,
} from "../shared/contracts.ts";

export interface AgentStateDerivationInput {
  readonly container: Pick<DockerContainerSnapshot, "state" | "health">;
  readonly status: RoleStatusPayload | null;
  readonly statusReadFailed: boolean;
}

export function deriveAgentState(input: AgentStateDerivationInput): AgentState {
  const container = input?.container;
  if (container === null || typeof container !== "object") return "UNKNOWN";
  if (
    ["MISSING", "STOPPED", "UNHEALTHY", "RESTARTING"].includes(container.state)
  )
    return "UNAVAILABLE";
  if (container.state !== "RUNNING" || container.health === "unknown")
    return "UNKNOWN";
  if (input.statusReadFailed || input.status === null) return "UNAVAILABLE";
  const status = input.status;
  if (!validStatus(status)) return "UNKNOWN";
  if (status.queue.blocked > 0) return "BLOCKED";
  if (status.queue.active > 0) return "WORKING";
  if (status.queue.pendingDue > 0) return "QUEUED";
  if (status.queue.pendingDelayed > 0) return "WAITING";
  if (!status.orchestratorEnabled) return "DISABLED";
  return "IDLE";
}

function validStatus(status: RoleStatusPayload): boolean {
  const queue = status?.queue;
  return (
    typeof status?.orchestratorEnabled === "boolean" &&
    queue !== null &&
    typeof queue === "object" &&
    [queue.pendingDue, queue.pendingDelayed, queue.active, queue.blocked].every(
      (value) => Number.isSafeInteger(value) && value >= 0,
    )
  );
}
