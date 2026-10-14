import { defineConfig, devices } from "@playwright/test";

import "./e2e/support/localhost-dns";

// E2E runs against a seeded stack (`seed_demo`): the API on :8010, the admin app on :5173
// and the portal on :5174/portal/ (both built and served with `vite preview`, see
// docs/test-plan/README.md and the CI e2e job). Specs create their own data, so they can run
// in any order; run them with one worker locally on small machines (`--workers=1`).
export default defineConfig({
  testDir: "./e2e",
  testIgnore: ["**/support/**"],
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://brightminds.localhost:5173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    // The portal registers a service worker (offline shell); keep it out of the way so
    // every test sees the network as it is.
    serviceWorkers: "block",
    locale: "en-GB",
    timezoneId: "Europe/London",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});
