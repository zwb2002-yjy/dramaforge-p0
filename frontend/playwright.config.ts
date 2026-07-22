import { defineConfig, devices } from "@playwright/test";

const e2ePort = Number.parseInt(process.env.DRAMAFORGE_E2E_PORT ?? "4173", 10);

/**
 * E2E config: global setup owns the in-process Vite server lifecycle so Windows
 * does not need to tear down a shell process tree after the tests complete.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  globalSetup: "./tests/e2e/global-setup.ts",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 30_000,
  globalTimeout: 180_000,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${e2ePort}`,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
