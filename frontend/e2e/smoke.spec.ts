import { expect, test } from "@playwright/test";

test("API is healthy", async ({ request }) => {
  const response = await request.get("/healthz");
  expect(response.ok()).toBeTruthy();
});

test("admin app loads and asks unauthenticated users to sign in", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
});

test("the seeded owner signs in and reaches the app", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@tutortrack.localhost");
  await page.getByLabel("Password").fill(process.env.SEED_ADMIN_PASSWORD ?? "tutortrack");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Welcome" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
});
