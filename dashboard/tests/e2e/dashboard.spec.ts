import { expect, test } from "@playwright/test";

test("production dashboard safely renders the degraded seven-role fixture", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      !message.text().includes("404 (Not Found)")
    )
      errors.push(message.text());
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "HermeTeam Dashboard" }),
  ).toBeVisible();
  await expect(page.locator("article.role-card")).toHaveCount(7);
  await expect(page.getByText("Agents working")).toBeVisible();
  await expect(page.getByText("Partial data.")).toBeVisible();
  const queue = page.getByText("View current queue").first();
  await queue.focus();
  await page.keyboard.press("Enter");
  await expect(
    page
      .getByRole("listitem")
      .getByRole("link", { name: "planner started work" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Refresh" }).click();
  const link = page.getByRole("link", { name: "planner started work" }).first();
  await expect(link).toHaveAttribute("rel", /noopener/);
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(page.locator("body")).not.toContainText(
    "t11-canary-secret-must-never-reach-browser",
  );
  expect(errors).toEqual([]);
});

test("mobile production layout does not horizontally overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator("article.role-card")).toHaveCount(7);
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
});
