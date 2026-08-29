import { defineConfig } from "@playwright/test";

const baseURL = process.env.DASHBOARD_E2E_BASE_URL;
if (!baseURL)
  throw new Error("DASHBOARD_E2E_BASE_URL is required for browser E2E");

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 15_000,
  retries: 0,
  workers: 1,
  use: {
    baseURL,
    browserName: "chromium",
    headless: true,
    launchOptions: {
      executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
    },
  },
});
