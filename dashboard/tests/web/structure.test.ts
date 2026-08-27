import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("web source structure", () => {
  it("keeps responsive and reduced-motion safeguards without raw HTML insertion", () => {
    const css = readFileSync("src/web/styles.css", "utf8");
    const app = readFileSync("src/web/App.tsx", "utf8");
    expect(css).toMatch(/@media\s*\(max-width:\s*800px\)/);
    expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    expect(css).toMatch(/min-height:\s*44px/);
    expect(app).not.toContain("dangerouslySetInnerHTML");
    expect(app).not.toContain("innerHTML");
  });
});
