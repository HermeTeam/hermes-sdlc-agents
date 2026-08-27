export type FetchImplementation = typeof fetch;

export const MAX_DEPENDENCY_RESPONSE_BYTES = 131_072;

export class DependencyClientError extends Error {
  public readonly code:
    | "timeout"
    | "unavailable"
    | "malformed_response"
    | "sqlite_busy"
    | "unknown";

  public constructor(code: DependencyClientError["code"]) {
    super(code);
    this.name = "DependencyClientError";
    this.code = code;
  }
}

export async function fetchJson(
  fetchImplementation: FetchImplementation,
  url: URL,
  timeoutMs: number,
): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImplementation(url, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    if (!response.ok) {
      if (
        response.status === 503 &&
        (response.headers.get("content-type") ?? "").startsWith(
          "application/json",
        )
      ) {
        const body = new Uint8Array(await response.arrayBuffer());
        if (body.byteLength <= MAX_DEPENDENCY_RESPONSE_BYTES) {
          try {
            const payload = JSON.parse(
              new TextDecoder("utf-8", { fatal: true }).decode(body),
            ) as { error?: { code?: unknown } };
            if (payload.error?.code === "sqlite_busy")
              throw new DependencyClientError("sqlite_busy");
          } catch (error) {
            if (error instanceof DependencyClientError) throw error;
          }
        }
      }
      throw new DependencyClientError("unavailable");
    }
    const contentType = response.headers.get("content-type") ?? "";
    if (!/^application\/json(?:\s*;|$)/i.test(contentType)) {
      throw new DependencyClientError("malformed_response");
    }
    const length = response.headers.get("content-length");
    if (
      length !== null &&
      (!/^[0-9]+$/.test(length) ||
        Number(length) > MAX_DEPENDENCY_RESPONSE_BYTES)
    ) {
      throw new DependencyClientError("malformed_response");
    }
    const body = new Uint8Array(await response.arrayBuffer());
    if (body.byteLength > MAX_DEPENDENCY_RESPONSE_BYTES) {
      throw new DependencyClientError("malformed_response");
    }
    try {
      return JSON.parse(
        new TextDecoder("utf-8", { fatal: true }).decode(body),
      ) as unknown;
    } catch {
      throw new DependencyClientError("malformed_response");
    }
  } catch (error) {
    if (error instanceof DependencyClientError) {
      throw error;
    }
    if (controller.signal.aborted) {
      throw new DependencyClientError("timeout");
    }
    throw new DependencyClientError("unavailable");
  } finally {
    clearTimeout(timer);
  }
}
