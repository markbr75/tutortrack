/**
 * Automated WCAG 2.2 AA checks (axe-core) on the key screens. axe finds roughly a third of
 * issues; the manual checklist in docs/test-plan/accessibility.md covers the rest
 * (keyboard, screen readers, reflow, reduced motion...). Test plan: TP-A11Y.
 */
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

import { PORTAL, expect, test, uid, type Role } from "./fixtures";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function scan(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const summary = results.violations.map(
    (v) =>
      `${v.id} (${v.impact}): ${v.help} — ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
  );
  expect(summary, summary.join("\n")).toEqual([]);
}

const SCREENS: { name: string; role: Role; path: string; ready: string | RegExp }[] = [
  { name: "home dashboard", role: "owner", path: "/", ready: /^Good (morning|afternoon|evening)/ },
  { name: "clients list", role: "coordinator", path: "/clients", ready: "Clients" },
  { name: "calendar", role: "coordinator", path: "/calendar", ready: "Calendar" },
  { name: "billing", role: "finance", path: "/billing", ready: "Billing" },
  { name: "catalogue", role: "admin", path: "/catalogue", ready: "Catalogue and pricing" },
  { name: "enquiries board", role: "coordinator", path: "/leads", ready: /Enquiries|Pipeline/ },
  { name: "inbox", role: "coordinator", path: "/inbox", ready: "Inbox" },
  { name: "parent portal home", role: "parent", path: PORTAL, ready: /./ },
  { name: "tutor portal today", role: "tutor", path: `${PORTAL}tutor`, ready: /./ },
];

test("sign-in page", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
  await scan(page);
});

for (const screen of SCREENS) {
  test(screen.name, async ({ pageAs }) => {
    const page = await pageAs(screen.role);
    await page.goto(screen.path);
    await expect(page.getByRole("heading", { level: 1, name: screen.ready }).first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await scan(page);
  });
}

test("public enquiry form", async ({ apiAs, page }) => {
  const api = await apiAs("coordinator");
  const slug = `a11y-${uid().toLowerCase()}`;
  await api.post("/api/v1/forms", {
    type: "enquiry",
    name: "Accessibility check form",
    slug,
    published: true,
    schema: {
      steps: [
        {
          title: "About you",
          fields: [
            {
              key: "first_name",
              label: "First name",
              type: "text",
              required: true,
              maps_to: "contact.first_name",
            },
            {
              key: "email",
              label: "Email",
              type: "email",
              required: true,
              maps_to: "contact.email",
            },
          ],
        },
      ],
    },
  });
  await page.goto(`/f/${slug}`);
  await expect(page.getByRole("heading", { name: "Accessibility check form" })).toBeVisible();
  await scan(page);
});
