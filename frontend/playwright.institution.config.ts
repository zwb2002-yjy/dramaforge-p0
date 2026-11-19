import { defineConfig, devices } from "@playwright/test";

const isolatedApi = "http://institution-api-quality:8000";
if (
  process.env.DRAMAFORGE_E2E_API_URL !== isolatedApi ||
  (process.env.DRAMAFORGE_API_URL !== undefined && process.env.DRAMAFORGE_API_URL !== isolatedApi)
) {
  throw new Error("Institution tests require the isolated quality API");
}

export default defineConfig({
  testDir: "./tests/institution",
  globalSetup: "./tests/e2e/global-setup.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 60_000,
  globalTimeout: 1_800_000,
  reporter: [["list"]],
  outputDir: "./test-results/institution",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: {
      executablePath: process.env.DRAMAFORGE_E2E_EXECUTABLE_PATH,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    },
  },
});
