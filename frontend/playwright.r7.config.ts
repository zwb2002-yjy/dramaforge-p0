import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.DRAMAFORGE_R7_BROWSER_BASE_URL ?? "http://127.0.0.1:8080";

export default defineConfig({
  testDir: "./tests/live",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  globalTimeout: 180_000,
  reporter: [["list"]],
  use: {
    baseURL,
    trace: "off",
    screenshot: "off",
    video: "off",
    launchOptions: process.env.DRAMAFORGE_E2E_EXECUTABLE_PATH
      ? {
          executablePath: process.env.DRAMAFORGE_E2E_EXECUTABLE_PATH,
          args: ["--no-sandbox", "--disable-dev-shm-usage"],
        }
      : undefined,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
