export const ROLE_SLUGS = [
  "planner",
  "project-manager",
  "builder",
  "reviewer",
  "release",
  "incident",
  "learning",
] as const;

export type RoleSlug = (typeof ROLE_SLUGS)[number];

export interface RoleDefinition {
  readonly slug: RoleSlug;
  readonly displayName: string;
  readonly serviceName: `hermes-${string}`;
}

export class RoleRegistryError extends Error {
  public constructor(message: string) {
    super(message);
    this.name = "RoleRegistryError";
  }
}

const EXPECTED_ROLE_SLUGS = new Set<string>(ROLE_SLUGS);

export function isRoleSlug(value: unknown): value is RoleSlug {
  return typeof value === "string" && EXPECTED_ROLE_SLUGS.has(value);
}

export function parseRoleSlug(value: unknown): RoleSlug {
  if (!isRoleSlug(value)) {
    throw new RoleRegistryError(
      `Unknown HermeTeam role slug: ${String(value)}`,
    );
  }
  return value;
}

export function createRoleRegistry(
  entries: readonly RoleDefinition[],
): readonly RoleDefinition[] {
  if (entries.length !== ROLE_SLUGS.length) {
    throw new RoleRegistryError(
      `Expected ${ROLE_SLUGS.length} role entries, received ${entries.length}`,
    );
  }

  const seenSlugs = new Set<string>();
  const seenServices = new Set<string>();
  const registry = entries.map((entry, index) => {
    if (!isRoleSlug(entry.slug)) {
      throw new RoleRegistryError(
        `Unknown role at index ${index}: ${String(entry.slug)}`,
      );
    }
    if (entry.slug !== ROLE_SLUGS[index]) {
      throw new RoleRegistryError(
        `Role at index ${index} must be ${ROLE_SLUGS[index]}`,
      );
    }
    if (seenSlugs.has(entry.slug)) {
      throw new RoleRegistryError(`Duplicate role slug: ${entry.slug}`);
    }
    if (seenServices.has(entry.serviceName)) {
      throw new RoleRegistryError(
        `Duplicate role service name: ${entry.serviceName}`,
      );
    }
    if (entry.serviceName !== `hermes-${entry.slug}`) {
      throw new RoleRegistryError(
        `Service name must match role slug: ${entry.slug}`,
      );
    }
    if (entry.displayName.trim().length === 0) {
      throw new RoleRegistryError(`Role display name is empty: ${entry.slug}`);
    }

    seenSlugs.add(entry.slug);
    seenServices.add(entry.serviceName);
    return Object.freeze({ ...entry });
  });

  for (const slug of ROLE_SLUGS) {
    if (!seenSlugs.has(slug)) {
      throw new RoleRegistryError(`Missing canonical role: ${slug}`);
    }
  }

  return Object.freeze(registry);
}

export const ROLE_REGISTRY = createRoleRegistry([
  { slug: "planner", displayName: "Planner", serviceName: "hermes-planner" },
  {
    slug: "project-manager",
    displayName: "Project Manager",
    serviceName: "hermes-project-manager",
  },
  { slug: "builder", displayName: "Builder", serviceName: "hermes-builder" },
  { slug: "reviewer", displayName: "Reviewer", serviceName: "hermes-reviewer" },
  { slug: "release", displayName: "Release", serviceName: "hermes-release" },
  { slug: "incident", displayName: "Incident", serviceName: "hermes-incident" },
  { slug: "learning", displayName: "Learning", serviceName: "hermes-learning" },
] satisfies readonly RoleDefinition[]);

export const ROLE_BY_SLUG: Readonly<Record<RoleSlug, RoleDefinition>> =
  Object.freeze(
    Object.fromEntries(
      ROLE_REGISTRY.map((role) => [role.slug, role]),
    ) as Record<RoleSlug, RoleDefinition>,
  );
