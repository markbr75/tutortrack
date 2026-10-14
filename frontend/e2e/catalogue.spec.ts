/**
 * Catalogue and pricing (E06): create a service with default rates, check a price, and see
 * that roles without rate permissions cannot change it. Test plan: TP-E06.
 */
import { expect, test, uid } from "./fixtures";

test("an admin creates a one-to-one service with charge and pay rates", async ({ pageAs }) => {
  const name = `E2E Chemistry ${uid()}`;
  const page = await pageAs("admin");
  await page.goto("/catalogue");
  await expect(page.getByRole("heading", { name: "Catalogue and pricing" })).toBeVisible();

  const form = page
    .locator("form")
    .filter({ has: page.getByRole("heading", { name: "New service" }) });
  await form.getByLabel("Name").fill(name);
  await form.getByLabel("Lesson length (minutes)").fill("60");
  await form.getByLabel("Pricing").selectOption({ label: "Per hour" });
  await form.getByLabel("Charge rate").fill("52.50");
  await form.getByLabel("Tutor pay").selectOption({ label: "Fixed rate" });
  await form.getByLabel("Pay rate").fill("30");
  await form.getByRole("button", { name: "Create service" }).click();

  const row = page.getByRole("row").filter({ hasText: name });
  await expect(row).toBeVisible();
  await expect(row).toContainText("£52.50");
  await expect(row).toContainText("£30.00");
  await expect(row).toContainText("Active");
});

test("the price check rounds a 90-minute lesson from the hourly rate", async ({ pageAs }) => {
  const page = await pageAs("owner");
  await page.goto("/catalogue");
  await page.getByRole("tab", { name: "Price check" }).click();
  await page.getByLabel("Service").selectOption({ label: "GCSE Maths 1:1" });
  await page.getByLabel("Lesson length (minutes)").fill("90");
  await page.getByLabel("Tutor", { exact: true }).selectOption({ label: "Nia Adeyemi" });
  await page.getByRole("checkbox", { name: /Arjun/ }).check();
  await page.getByRole("button", { name: "Check price" }).click();
  // £45/h x 1.5 h charged; £28/h x 1.5 h paid.
  await expect(page.getByRole("heading", { name: "Charged to clients: £67.50" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Paid to tutors: £42.00" })).toBeVisible();
});

test("a coordinator can browse the catalogue but not change services", async ({ pageAs }) => {
  const page = await pageAs("coordinator");
  await page.goto("/catalogue");
  await expect(page.getByRole("cell", { name: "GCSE Maths 1:1" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "New service" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Edit / })).toHaveCount(0);
});
