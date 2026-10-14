/**
 * Platform console (E30): TutorTrack staff see every organisation, tenant health and SaaS
 * metrics on the root host; organisation users are kept out. The e2e stack runs with
 * PLATFORM_REQUIRE_MFA=false (docs/test-plan/README.md). Test plan: TP-E30.
 */
import { expect, test } from "./fixtures";

/** The console lives on the root host, not an organisation's subdomain. */
const ROOT_URL = process.env.E2E_ROOT_URL ?? "http://localhost:5173";

test("platform staff find both organisations and open one", async ({ pageAs }) => {
  const page = await pageAs("platform", ROOT_URL);
  await page.goto("/platform");
  const nav = page.getByRole("navigation", { name: "TutorTrack console" });
  await expect(nav).toBeVisible();
  await expect(page.getByRole("heading", { name: "Organisations" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Bright Minds Tutoring" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Northside Learning" })).toBeVisible();

  await page.getByRole("link", { name: "Bright Minds Tutoring" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: /Bright Minds Tutoring/ }),
  ).toBeVisible();
});

test("platform staff see tenant health and SaaS metrics", async ({ pageAs }) => {
  const page = await pageAs("platform", ROOT_URL);
  await page.goto("/platform");
  const nav = page.getByRole("navigation", { name: "TutorTrack console" });
  await nav.getByRole("link", { name: "Health" }).click();
  await expect(page.getByRole("heading", { name: "Tenant health" })).toBeVisible();
  await expect(page.getByText("Bright Minds Tutoring").first()).toBeVisible();

  await nav.getByRole("link", { name: "SaaS metrics" }).click();
  await expect(page.getByRole("heading", { name: "SaaS metrics" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "MRR by month" })).toBeVisible();

  await nav.getByRole("link", { name: "Support" }).click();
  await expect(page.getByText("Invoice runs").first()).toBeVisible();
});

test("an organisation admin cannot use the console", async ({ pageAs, apiAs }) => {
  const page = await pageAs("admin", ROOT_URL);
  await page.goto("/platform");
  await expect(page.getByText("The console is for TutorTrack staff.")).toBeVisible();
  const api = await apiAs("admin", ROOT_URL);
  const response = await api.raw("GET", "/api/v1/platform/tenants");
  expect([401, 403]).toContain(response.status());
});
