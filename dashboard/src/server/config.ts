import process from "node:process";

import { ROLE_BY_SLUG, ROLE_SLUGS } from "../shared/roles.ts";
import type { RoleSlug } from "../shared/roles.ts";

export const DEPENDENCY_TIMEOUT_MS = 2_000;
export const OVERVIEW_TIMEOUT_MS = 3_000;
export const DEFAULT_STATUS_PORT = 8_650;
export const DEFAULT_DOCKER_PROXY_URL = "http://docker-socket-proxy:2375";

export interface DashboardConfig {
  readonly dockerProxyUrl: URL;
  readonly roleServices: Readonly<Record<RoleSlug, string>>;
  readonly roleStatusPort: number;
  readonly dependencyTimeoutMs: number;
  readonly overviewTimeoutMs: number;
}

export class DashboardConfigError extends Error {
  public constructor(message: string) {
    super(message);
    this.name = "DashboardConfigError";
  }
}

type Environment = Readonly<Record<string, string | undefined>>;

export function loadDashboardConfig(
  environment: Environment = process.env,
): DashboardConfig {
  const roleServices = parseRoleServices(environment.ROLE_SERVICES);
  const dockerProxyUrl = parseDockerProxyUrl(
    environment.DOCKER_PROXY_URL ?? DEFAULT_DOCKER_PROXY_URL,
  );
  const roleStatusPort = parsePort(
    environment.ROLE_STATUS_PORT ?? String(DEFAULT_STATUS_PORT),
    "ROLE_STATUS_PORT",
  );
  const dependencyTimeoutMs = parseTimeout(
    environment.DEPENDENCY_TIMEOUT_MS,
    DEPENDENCY_TIMEOUT_MS,
    "DEPENDENCY_TIMEOUT_MS",
  );
  const overviewTimeoutMs = parseTimeout(
    environment.OVERVIEW_TIMEOUT_MS,
    OVERVIEW_TIMEOUT_MS,
    "OVERVIEW_TIMEOUT_MS",
  );

  if (overviewTimeoutMs < dependencyTimeoutMs) {
    throw new DashboardConfigError(
      "OVERVIEW_TIMEOUT_MS must not be less than DEPENDENCY_TIMEOUT_MS",
    );
  }

  return Object.freeze({
    dockerProxyUrl,
    roleServices,
    roleStatusPort,
    dependencyTimeoutMs,
    overviewTimeoutMs,
  });
}

export function parseRoleServices(
  value: string | undefined,
): Readonly<Record<RoleSlug, string>> {
  const mappings: Partial<Record<RoleSlug, string>> = {};
  const source = value === undefined ? canonicalRoleServices() : value;
  const entries = typeof source === "string" ? source.split(",") : [];
  if (entries.length !== ROLE_SLUGS.length) {
    throw new DashboardConfigError(
      "ROLE_SERVICES must define every canonical role exactly once",
    );
  }

  for (const entry of entries) {
    const match = /^([a-z][a-z-]*)=([a-z][a-z0-9-]*)$/.exec(entry);
    if (match === null) {
      throw new DashboardConfigError(
        "ROLE_SERVICES contains an invalid mapping",
      );
    }
    const [, role, service] = match;
    if (
      !ROLE_SLUGS.includes(role as RoleSlug) ||
      service !== `hermes-${role}`
    ) {
      throw new DashboardConfigError(
        "ROLE_SERVICES must use canonical role service mappings",
      );
    }
    if (mappings[role as RoleSlug] !== undefined) {
      throw new DashboardConfigError("ROLE_SERVICES contains a duplicate role");
    }
    mappings[role as RoleSlug] = service;
  }

  for (const role of ROLE_SLUGS) {
    if (mappings[role] !== ROLE_BY_SLUG[role].serviceName) {
      throw new DashboardConfigError(
        "ROLE_SERVICES is missing a canonical role service",
      );
    }
  }
  return Object.freeze(mappings as Record<RoleSlug, string>);
}

function canonicalRoleServices(): string {
  return ROLE_SLUGS.map(
    (role) => `${role}=${ROLE_BY_SLUG[role].serviceName}`,
  ).join(",");
}

function parseDockerProxyUrl(value: string): URL {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new DashboardConfigError(
      "DOCKER_PROXY_URL must be a valid canonical proxy URL",
    );
  }
  if (
    url.protocol !== "http:" ||
    url.hostname !== "docker-socket-proxy" ||
    url.port !== "2375" ||
    url.username !== "" ||
    url.password !== "" ||
    url.pathname !== "/" ||
    url.search !== "" ||
    url.hash !== ""
  ) {
    throw new DashboardConfigError(
      "DOCKER_PROXY_URL must be http://docker-socket-proxy:2375",
    );
  }
  return url;
}

function parsePort(value: string, name: string): number {
  if (!/^[1-9][0-9]{0,4}$/.test(value)) {
    throw new DashboardConfigError(`${name} must be a valid port`);
  }
  const port = Number(value);
  if (!Number.isSafeInteger(port) || port > 65_535) {
    throw new DashboardConfigError(`${name} must be a valid port`);
  }
  return port;
}

function parseTimeout(
  value: string | undefined,
  fallback: number,
  name: string,
): number {
  if (value === undefined) {
    return fallback;
  }
  if (!/^[1-9][0-9]{0,5}$/.test(value)) {
    throw new DashboardConfigError(
      `${name} must be a bounded positive integer`,
    );
  }
  const timeout = Number(value);
  if (!Number.isSafeInteger(timeout) || timeout > 60_000) {
    throw new DashboardConfigError(
      `${name} must be a bounded positive integer`,
    );
  }
  return timeout;
}
