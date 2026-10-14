/**
 * Client billing and manual payments (E10, E11): charge → invoice → issue → record payment,
 * and a credit note that reduces what is owed. Money is shown in the org currency (GBP).
 * Test plan: TP-E10, TP-E11.
 */
import { createFamily, expect, londonToday, test, uid, type Api } from "./fixtures";

type Money = { amount: string; currency: string };
type Invoice = {
  id: string;
  number: string;
  status: string;
  total: Money;
  balance_due: Money;
  lines?: { description: string }[];
};

const gbp = (amount: string) =>
  new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" }).format(Number(amount));

async function latestInvoice(api: Api, clientId: string): Promise<Invoice> {
  const page = await api.get<{ results: Invoice[] }>("/api/v1/invoices", { client: clientId });
  expect(page.results.length).toBeGreaterThan(0);
  return page.results[0]!;
}

test("finance invoices an ad hoc charge, issues it and records the payment", async ({
  apiAs,
  pageAs,
}) => {
  const family = await createFamily(await apiAs("coordinator"));
  const finance = await apiAs("finance");
  const page = await pageAs("finance");
  await page.goto(`/clients/${family.clientId}`);

  const description = `Exam entry fee ${uid()}`;
  await page.getByRole("tab", { name: "Add a charge" }).click();
  await page.getByLabel("Description").fill(description);
  await page.getByLabel("Amount").fill("37.50");
  await page.getByRole("button", { name: "Add a charge" }).click();
  await expect(page.getByText("Charge added.")).toBeVisible();

  await page.getByRole("button", { name: "Invoice now" }).click();
  await expect
    .poll(async () => {
      const page = await finance.get<{ results: Invoice[] }>("/api/v1/invoices", {
        client: family.clientId,
      });
      return page.results[0]?.status;
    })
    .toBe("draft");
  const draft = await latestInvoice(finance, family.clientId);

  await page.goto(`/invoices/${draft.id}`);
  await expect(page.getByRole("heading", { name: /Draft invoice/ })).toBeVisible();
  await expect(page.getByRole("cell", { name: description, exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Issue invoice" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /Issued/ })).toBeVisible();

  const issued = await finance.get<Invoice>(`/api/v1/invoices/${draft.id}`);
  expect(issued.number).not.toBe("");
  // £37.50 net; tax depends on the default rate, so the gross comes from the invoice.
  expect(Number(issued.total.amount)).toBeGreaterThanOrEqual(37.5);
  await expect(page.getByText(gbp(issued.total.amount)).first()).toBeVisible();

  await page.goto(`/clients/${family.clientId}`);
  await page.getByRole("tab", { name: "Payments" }).click();
  const form = page.getByRole("form", { name: "Record payment" });
  await form.getByLabel("Amount").fill(issued.balance_due.amount);
  await form.getByLabel("How they paid").selectOption({ label: "Bank transfer" });
  await form.getByLabel("Received on").fill(londonToday());
  await form.getByLabel("Reference").fill(`BACS ${uid()}`);
  await form.getByRole("button", { name: "Record payment" }).click();
  await expect(page.getByText("Payment recorded.")).toBeVisible();

  await page.goto(`/invoices/${draft.id}`);
  await expect(page.getByRole("heading", { level: 1, name: /Paid/ })).toBeVisible();
  const paid = await finance.get<Invoice>(`/api/v1/invoices/${draft.id}`);
  expect(Number(paid.balance_due.amount)).toBe(0);
});

test("a credit note reduces what is owed on an issued invoice", async ({ apiAs, pageAs }) => {
  const family = await createFamily(await apiAs("coordinator"));
  const finance = await apiAs("finance");
  const description = `Workbook ${uid()}`;
  await finance.post("/api/v1/charges", {
    client: family.clientId,
    description,
    unit_price: { amount: "20.00", currency: "GBP" },
    quantity: "1",
    category: "",
  });
  await finance.post("/api/v1/invoices", { client: family.clientId, until: null });
  const draft = await latestInvoice(finance, family.clientId);
  const issued = await finance.post<Invoice>(`/api/v1/invoices/${draft.id}/issue`);
  const before = Number(issued.balance_due.amount);

  const page = await pageAs("finance");
  await page.goto(`/invoices/${draft.id}`);
  await page.getByRole("button", { name: "Credit note" }).click();
  await page.getByLabel(`Credit for ${description}`).fill("5.00");
  await page.getByLabel("Reason").fill("Damaged copy");
  await page
    .getByLabel("Use the credit to")
    .selectOption({ label: "Reduce what's owed on this invoice" });
  await page.getByRole("button", { name: "Issue credit note" }).click();
  await expect(page.getByRole("heading", { name: "Credit notes" })).toBeVisible();

  await expect
    .poll(async () =>
      Number((await finance.get<Invoice>(`/api/v1/invoices/${draft.id}`)).balance_due.amount),
    )
    .toBeLessThan(before);
  await expect(page.getByRole("heading", { level: 1, name: /Partly paid|Issued/ })).toBeVisible();
});

test("a coordinator can view invoices but cannot issue or credit them", async ({
  apiAs,
  pageAs,
}) => {
  const family = await createFamily(await apiAs("coordinator"));
  const finance = await apiAs("finance");
  await finance.post("/api/v1/charges", {
    client: family.clientId,
    description: "Mock exam",
    unit_price: { amount: "15.00", currency: "GBP" },
    quantity: "1",
    category: "",
  });
  await finance.post("/api/v1/invoices", { client: family.clientId, until: null });
  const draft = await latestInvoice(finance, family.clientId);

  const page = await pageAs("coordinator");
  await page.goto(`/invoices/${draft.id}`);
  await expect(page.getByRole("heading", { name: /Draft invoice/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Issue invoice" })).toHaveCount(0);
  const coordinator = await apiAs("coordinator");
  expect((await coordinator.raw("POST", `/api/v1/invoices/${draft.id}/issue`)).status()).toBe(403);
});
