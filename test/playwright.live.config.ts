import { defineConfig, devices } from "@playwright/test";

// Live suite: runs against the real Dhan feed and the real account. It does not
// assume a fresh database or simulator prices. Use `npm run test:live`.
export default defineConfig({
  testDir: "./live",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:8000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
