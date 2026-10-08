import { expect, test } from "@playwright/test";

test("API is healthy", async ({ request }) => {
  const response = await request.get("/healthz");
  expect(response.ok()).toBeTruthy();
});

test("admin app loads and asks unauthenticated users to sign in", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
});
