import { parseOverviewResponse } from "../shared/contracts.ts";
import type { OverviewResponse } from "../shared/contracts.ts";

export async function fetchOverview(
  signal?: AbortSignal,
): Promise<OverviewResponse> {
  const response = await fetch("/api/overview", {
    method: "GET",
    ...(signal === undefined ? {} : { signal }),
    headers: { Accept: "application/json" },
  });
  if (!response.ok)
    throw new Error("The dashboard overview is temporarily unavailable.");
  return parseOverviewResponse((await response.json()) as unknown);
}
