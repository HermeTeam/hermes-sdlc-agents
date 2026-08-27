import { parseRoleStatusPayload } from "../shared/contracts.ts";
import type { RoleStatusPayload } from "../shared/contracts.ts";
import type { RoleSlug } from "../shared/roles.ts";
import { DependencyClientError, fetchJson } from "./http.ts";
import type { FetchImplementation } from "./http.ts";

export { DependencyClientError as RoleClientError } from "./http.ts";

export interface RoleClientOptions {
  readonly roleServices: Readonly<Record<RoleSlug, string>>;
  readonly statusPort: number;
  readonly timeoutMs: number;
  readonly fetchImplementation?: FetchImplementation;
}

export class RoleClient {
  readonly #services: Readonly<Record<RoleSlug, string>>;
  readonly #statusPort: number;
  readonly #timeoutMs: number;
  readonly #fetch: FetchImplementation;

  public constructor(options: RoleClientOptions) {
    this.#services = options.roleServices;
    this.#statusPort = options.statusPort;
    this.#timeoutMs = options.timeoutMs;
    this.#fetch = options.fetchImplementation ?? fetch;
  }

  public async readStatus(expectedRole: RoleSlug): Promise<RoleStatusPayload> {
    const url = new URL(
      `http://${this.#services[expectedRole]}:${this.#statusPort}/status`,
    );
    let payload: unknown;
    try {
      payload = await fetchJson(this.#fetch, url, this.#timeoutMs);
    } catch (error) {
      if (error instanceof DependencyClientError) throw error;
      throw new DependencyClientError("unavailable");
    }
    try {
      const status = parseRoleStatusPayload(payload);
      if (status.role !== expectedRole) throw new Error("role mismatch");
      return status;
    } catch {
      throw new DependencyClientError("malformed_response");
    }
  }
}
