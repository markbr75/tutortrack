/**
 * E33 T07: the sequence editor. The usability check from the epic, as a journey: an owner
 * changes when invoices go out in a few steps, then puts the default back.
 */
import AxeBuilder from "@axe-core/playwright";

import { expect, test } from "./fixtures";

test("an owner changes when invoices go out, then resets it", async ({ pageAs }) => {
  const page = await pageAs("owner");
  await page.goto("/workflows");
  await page.getByRole("link", { name: "Invoicing cycle" }).click();
  const start = page.getByRole("region", { name: "Start" });
  await start.getByRole("button", { name: "Edit" }).click();
  await start.getByLabel("Day of the month").selectOption("5");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(/^Saved\./)).toBeVisible();
  await expect(start.getByText(/Every month on day 5/)).toBeVisible();

  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: "Reset to default" }).click();
  await expect(page.getByText("Reset to the default.")).toBeVisible();
});

test("the editor passes the WCAG 2.2 AA scan with a card open", async ({ pageAs }) => {
  const page = await pageAs("owner");
  await page.goto("/workflows");
  await page.getByRole("link", { name: "Payment chasing" }).click();
  await page.getByRole("region", { name: "Step 1" }).getByRole("button", { name: "Edit" }).click();
  await page.waitForLoadState("networkidle");
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
});
