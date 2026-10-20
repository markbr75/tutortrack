/**
 * Client portal (E15) and online payment (E11): Priya Patel signs in, sees her children's
 * lessons, and pays an issued invoice through the fake PayPal provider (no network).
 * Test plan: TP-E15, TP-E11.
 */
import { PORTAL, expect, findId, test, uid, type Api } from "./fixtures";

type Money = { amount: string; currency: string };
type Invoice = { id: string; number: string; status: string; balance_due: Money };

/** Connects the fake PayPal account once (connect → provider "redirect" → complete). */
async function ensurePayPal(owner: Api) {
  const accounts = await owner.get<
    { provider: string; status: string }[] | { results: { provider: string; status: string }[] }
  >("/api/v1/payments/providers");
  const rows = Array.isArray(accounts) ? accounts : accounts.results;
  if (rows.some((a) => a.provider === "paypal" && a.status === "active")) return;
  const started = await owner.post<{ url: string }>("/api/v1/payments/providers/paypal/connect", {
    email: "",
  });
  const back = new URL(started.url);
  await owner.post("/api/v1/payments/providers/paypal/complete", {
    state: back.searchParams.get("state") ?? "",
    code: back.searchParams.get("code") ?? back.searchParams.get("merchantIdInPayPal") ?? "",
  });
}

/** An issued invoice for the Patel family with one unique line. */
async function patelInvoice(finance: Api, amount: string): Promise<Invoice> {
  const clientId = await findId(finance, "/api/v1/clients", "display_name", "The Patel Family", {
    q: "Patel",
  });
  await finance.post("/api/v1/charges", {
    client: clientId,
    description: `Revision workshop ${uid()}`,
    unit_price: { amount, currency: "GBP" },
    quantity: "1",
    category: "",
  });
  const draft = await finance.post<Invoice | Invoice[]>("/api/v1/invoices", {
    client: clientId,
    until: null,
  });
  const id = Array.isArray(draft) ? draft[0]!.id : draft.id;
  return finance.post<Invoice>(`/api/v1/invoices/${id}/issue`);
}

test("a parent sees their children's lessons in the portal", async ({ pageAs }) => {
  const page = await pageAs("parent");
  await page.goto(PORTAL);
  await expect(page.getByRole("navigation").first()).toBeVisible();
  await page.getByRole("link", { name: "Lessons", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Lessons", exact: true })).toBeVisible();
  // Arjun's weekly GCSE Maths with Nia Adeyemi is seeded.
  await expect(page.getByRole("heading", { name: /Arjun Patel/ }).first()).toBeVisible();
  await expect(page.getByText(/Okafor|Grace Hughes/)).toHaveCount(0);
});

test("a parent pays an issued invoice with PayPal from the portal", async ({ apiAs, pageAs }) => {
  await ensurePayPal(await apiAs("owner"));
  const finance = await apiAs("finance");
  const invoice = await patelInvoice(finance, "24.00");
  expect(invoice.status).toBe("issued");

  const page = await pageAs("parent");
  await page.goto(`${PORTAL}billing`);
  const row = page.getByRole("listitem").filter({ hasText: invoice.number });
  await expect(row).toBeVisible();
  await row.getByRole("link", { name: /^Pay / }).click();

  await expect(page.getByRole("heading", { name: `Invoice ${invoice.number}` })).toBeVisible();
  const paypal = page.getByRole("radio", { name: "PayPal" });
  if (await paypal.count()) await paypal.check();
  await page.getByRole("button", { name: /^Pay / }).click();
  // The fake provider sends the payer straight back with the order id.
  await expect(page.getByText("Thank you – your payment has been received.")).toBeVisible({
    timeout: 20_000,
  });

  await expect
    .poll(async () => (await finance.get<Invoice>(`/api/v1/invoices/${invoice.id}`)).status)
    .toBe("paid");
});

test("the portal shows only the parent's own household", async ({ apiAs }) => {
  const parent = await apiAs("parent");
  const billing = await parent.get<{ accounts?: { client_name?: string }[] }>(
    "/api/v1/portal/billing",
  );
  const text = JSON.stringify(billing);
  expect(text).toContain("Patel");
  expect(text).not.toContain("Okafor");
  expect(text).not.toContain("Northside");
});
