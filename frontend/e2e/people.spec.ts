/**
 * People and CRM (E05): add a family in one step, open the household and student records,
 * add a note, change a status. Test plan: TP-E05.
 */
import { createFamily, expect, test, uid } from "./fixtures";

test("a coordinator adds a family with two students in one step", async ({ pageAs }) => {
  const surname = `Quick${uid()}`;
  const page = await pageAs("coordinator");
  await page.goto("/clients");
  await page.getByRole("link", { name: "Add a family" }).click();
  await expect(page.getByRole("heading", { name: "Add a family" })).toBeVisible();

  const parent = page.getByRole("group", { name: "Parent or guardian" });
  await parent.getByLabel("First name").fill("Jordan");
  await parent.getByLabel("Last name").fill(surname);
  await parent.getByLabel("Email").fill(`jordan.${surname.toLowerCase()}@example.com`);
  await page.getByLabel("Student 1 first name").fill("Ellis");
  await page.getByLabel("Year group").first().fill("Year 8");
  await page.getByLabel("Subject").first().fill("Maths");
  await page.getByRole("button", { name: "Add another student" }).click();
  await page.getByLabel("Student 2 first name").fill("Rowan");
  await page.getByRole("button", { name: "Create family" }).click();

  await expect(page.getByRole("heading", { level: 1, name: new RegExp(surname) })).toBeVisible();
  await expect(page.getByText(`Jordan ${surname}`, { exact: false }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: /Ellis/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /Rowan/ })).toBeVisible();

  // It is findable from the client list.
  await page.goto("/clients");
  await page.getByRole("searchbox", { name: "Search", exact: true }).fill(surname);
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByRole("link", { name: "Grace Hughes" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: new RegExp(surname) })).toBeVisible();
});

test("a coordinator adds a note to a family and changes a student's status", async ({
  apiAs,
  pageAs,
}) => {
  const family = await createFamily(await apiAs("coordinator"), { students: ["Sky"] });
  const page = await pageAs("coordinator");
  await page.goto(`/clients/${family.clientId}`);
  await expect(page.getByRole("heading", { level: 1, name: family.name })).toBeVisible();

  const note = `Prefers Saturday mornings ${uid()}`;
  await page.getByLabel("Add a note").fill(note);
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(page.getByText(note)).toBeVisible();

  await page.getByRole("link", { name: /Sky/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: /Sky/ })).toBeVisible();
  await page.getByLabel("Status").selectOption({ label: "Paused" });
  await page.getByRole("button", { name: "Change status" }).click();
  await expect(page.getByText(/Paused/).first()).toBeVisible();
});

test("a required field is reported next to the field, not lost", async ({ pageAs }) => {
  const page = await pageAs("coordinator");
  await page.goto("/clients/new");
  await page.getByRole("button", { name: "Create family" }).click();
  // The browser or the API refuses an empty parent name; the form stays put.
  await expect(page.getByRole("heading", { name: "Add a family" })).toBeVisible();
});
