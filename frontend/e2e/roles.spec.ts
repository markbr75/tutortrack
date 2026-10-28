/**
 * Roles and tenancy (E02, E03): each seeded role signs in and sees only its navigation;
 * the API refuses what the role may not do; another organisation's data never appears.
 * Test plan: TP-E03 (permissions), TP-E02 (tenant isolation).
 */
import { ACCOUNTS, OTHER_ORG_URL, PASSWORD, createFamily, expect, test, uid } from "./fixtures";

// Main: the grouped sidebar. Settings: the settings area's own menu (opened from Settings at
// the foot of the sidebar). Hidden: in neither.
const NAV: Record<string, { sees: string[]; settings: string[]; hidden: string[] }> = {
  owner: {
    sees: ["Clients", "Billing", "Payroll"],
    settings: ["Audit log", "Safeguarding", "Billing & plan"],
    hidden: [],
  },
  admin: {
    sees: ["Clients", "Billing"],
    settings: ["Team", "Audit log", "Privacy"],
    hidden: ["Safeguarding"],
  },
  branchManager: {
    sees: ["Clients", "Students", "Calendar", "Jobs"],
    settings: [],
    hidden: ["Audit log", "Billing & plan", "Import and export", "Privacy"],
  },
  coordinator: {
    sees: ["Clients", "Students", "Jobs", "Calendar", "Enquiries", "Inbox"],
    settings: [],
    hidden: [
      "Payroll",
      "Audit log",
      "Payments setup",
      "Billing & plan",
      "Safeguarding",
      "Recruitment",
      "Compliance",
      "Workflows",
    ],
  },
  finance: {
    sees: ["Billing", "Payroll", "Clients", "Workflows"],
    settings: ["Accounting"],
    hidden: [
      "Students",
      "Jobs",
      "Recruitment",
      "Calendar",
      "Lesson reports",
      "Unconfirmed lessons",
      "Inbox",
      "Broadcasts",
      "Website & branding",
      "Audit log",
      "Safeguarding",
    ],
  },
};

test.describe("staff roles see their own navigation", () => {
  for (const [role, { sees, settings, hidden }] of Object.entries(NAV)) {
    test(`${role} (${ACCOUNTS[role as keyof typeof ACCOUNTS]})`, async ({ pageAs }) => {
      const page = await pageAs(role as keyof typeof ACCOUNTS);
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      const nav = page.getByRole("navigation", { name: "Main" });
      // Long menus collapse to their group headings: open them all before checking links.
      const closed = nav.getByRole("button", { expanded: false });
      while ((await closed.count()) > 0) await closed.first().click();
      for (const name of sees) {
        await expect(nav.getByRole("link", { name, exact: true })).toBeVisible();
      }
      for (const name of hidden) {
        await expect(nav.getByRole("link", { name, exact: true })).toHaveCount(0);
      }
      const settingsLink = page.getByRole("link", { name: "Settings", exact: true });
      if (settings.length) await expect(settingsLink).toBeVisible();
      if ((await settingsLink.count()) === 0) return;
      await settingsLink.click();
      const area = page.getByRole("navigation", { name: "Settings" });
      await expect(area).toBeVisible();
      for (const name of settings) {
        await expect(area.getByRole("link", { name, exact: true })).toBeVisible();
      }
      for (const name of hidden) {
        await expect(area.getByRole("link", { name, exact: true })).toHaveCount(0);
      }
    });
  }
});

test("the sign-in form rejects a wrong password without saying which part was wrong", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(ACCOUNTS.coordinator);
  await page.getByLabel("Password").fill(`${PASSWORD}-wrong`);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
});

test("a coordinator signs in with the form and signs out again", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(ACCOUNTS.coordinator);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav).toBeVisible();
  // Sign out lives in the account menu (your initials) in the top bar.
  await page.getByRole("button", { name: /^Account menu for / }).click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
  await page.goto("/clients");
  await expect(page).toHaveURL(/\/login/);
});

test("portal roles signing in to the admin app are sent to the portal", async ({ pageAs }) => {
  const parent = await pageAs("parent");
  await parent.goto("/");
  await expect(parent).toHaveURL(/\/portal\/?$/);
  const tutor = await pageAs("tutor");
  await tutor.goto("/");
  await expect(tutor).toHaveURL(/\/portal\/tutor/);
});

test("the API refuses what a role may not do", async ({ apiAs }) => {
  const coordinator = await apiAs("coordinator");
  expect((await coordinator.raw("GET", "/api/v1/audit")).status()).toBe(403);
  expect((await coordinator.raw("GET", "/api/v1/clients")).status()).toBe(200);

  const finance = await apiAs("finance");
  expect((await finance.raw("GET", "/api/v1/jobs")).status()).toBe(403);
  const createClient = await finance.raw("POST", "/api/v1/clients/quick-add", {
    contact: { first_name: "Not", last_name: "Allowed" },
  });
  expect(createClient.status()).toBe(403);

  const tutor = await apiAs("tutor");
  expect((await tutor.raw("GET", "/api/v1/audit")).status()).toBe(403);

  const parent = await apiAs("parent");
  expect((await parent.raw("GET", "/api/v1/clients")).status()).toBe(403);
});

test.describe("tenant isolation", () => {
  test("another organisation's family never appears, even by id", async ({ apiAs }) => {
    const northside = await apiAs("otherOwner", OTHER_ORG_URL);
    const theirs = await createFamily(northside, { lastName: `North${uid()}` });

    const brightminds = await apiAs("owner");
    const search = await brightminds.get<{ results: { id: string }[] }>("/api/v1/clients", {
      q: theirs.name,
    });
    expect(search.results).toHaveLength(0);
    expect((await brightminds.raw("GET", `/api/v1/clients/${theirs.clientId}`)).status()).toBe(404);

    const ours = await brightminds.get<{ results: { display_name: string }[] }>("/api/v1/clients", {
      q: "Patel",
    });
    expect(ours.results.length).toBeGreaterThan(0);
    const theirSearch = await northside.get<{ results: unknown[] }>("/api/v1/clients", {
      q: "Patel",
    });
    expect(theirSearch.results).toHaveLength(0);
  });

  test("a member of one organisation gets nothing on another organisation's host", async ({
    apiAs,
  }) => {
    const outsider = await apiAs("coordinator", OTHER_ORG_URL);
    const response = await outsider.raw("GET", "/api/v1/clients");
    expect([401, 403, 404]).toContain(response.status());
  });

  test("the people search shows nothing from the other organisation", async ({ pageAs }) => {
    const page = await pageAs("coordinator");
    await page.goto("/clients");
    await page.getByRole("searchbox", { name: "Search", exact: true }).fill("Northside");
    await page.getByRole("button", { name: "Apply" }).click();
    await expect(page.getByText("Nothing to show.")).toBeVisible();
    await expect(page.getByText(/Northside/)).toHaveCount(0);
    await page.getByRole("searchbox", { name: "Search", exact: true }).fill("Patel");
    await page.getByRole("button", { name: "Apply" }).click();
    await expect(page.getByRole("link", { name: /Patel/ }).first()).toBeVisible();
  });
});
