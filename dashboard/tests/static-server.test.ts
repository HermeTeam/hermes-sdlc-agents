import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  createDashboardApplication,
  listenDashboard,
} from "../src/server/index.ts";
import type { OverviewResponse } from "../src/shared/contracts.ts";

const overview: OverviewResponse = {
  generatedAt: "2026-08-27T00:00:00Z",
  partial: false,
  roles: [],
};

async function withServer(
  run: (baseUrl: string) => Promise<void>,
): Promise<void> {
  const root = await mkdtemp(join(tmpdir(), "dashboard-static-"));
  await writeFile(
    join(root, "index.html"),
    "<!doctype html><script type=module src='/assets/app.js'></script>",
  );
  await (await import("node:fs/promises")).mkdir(join(root, "assets"));
  await writeFile(join(root, "assets", "app.js"), "console.log('ok');");
  const app = createDashboardApplication({
    overview: { getOverview: async () => overview },
    staticRoot: root,
  });
  await listenDashboard(app, 0);
  const address = app.server.address();
  assert.ok(address && typeof address !== "string");
  try {
    await run(`http://127.0.0.1:${address.port}`);
  } finally {
    await app.close();
  }
}

test("serves only root and approved hashed-style assets with hardened headers", async () => {
  await withServer(async (baseUrl) => {
    const root = await fetch(`${baseUrl}/`);
    assert.equal(root.status, 200);
    assert.equal(root.headers.get("cache-control"), "no-store");
    assert.match(
      root.headers.get("content-security-policy") ?? "",
      /script-src 'self'/,
    );
    const asset = await fetch(`${baseUrl}/assets/app.js`);
    assert.equal(asset.status, 200);
    assert.equal(
      asset.headers.get("cache-control"),
      "public, max-age=31536000, immutable",
    );
    assert.equal(asset.headers.get("x-content-type-options"), "nosniff");
  });
});

test("does not expose traversal, dotfiles, source maps, or static API fallbacks", async () => {
  await withServer(async (baseUrl) => {
    for (const pathname of [
      "//",
      "/assets/../index.html",
      "/.env",
      "/assets/app.js.map",
      "/unknown",
      "/api/missing",
    ]) {
      assert.equal(
        (await fetch(`${baseUrl}${pathname}`)).status,
        404,
        pathname,
      );
    }
    assert.equal((await fetch(`${baseUrl}/api/overview?x=1`)).status, 404);
    assert.equal((await fetch(`${baseUrl}/`, { method: "POST" })).status, 405);
  });
});
