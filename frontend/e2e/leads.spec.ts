/**
 * Leads and pipeline (E17): a family fills in the public enquiry form, the enquiry lands on
 * the board, and a coordinator converts it into a client with a job. Test plan: TP-E17.
 */
import { expect, serviceId, test, uid, type Api } from "./fixtures";

type Enquiry = { id: string; title: string; status: string; client: string | null };

async function createForm(api: Api) {
  const id = uid().toLowerCase();
  const form = await api.post<{ id: string; slug: string; name: string }>("/api/v1/forms", {
    type: "enquiry",
    name: `Tuition enquiry ${id}`,
    slug: `e2e-${id}`,
    published: true,
    schema: {
      steps: [
        {
          title: "About you",
          fields: [
            {
              key: "first_name",
              label: "Your first name",
              type: "text",
              required: true,
              maps_to: "contact.first_name",
            },
            {
              key: "last_name",
              label: "Your last name",
              type: "text",
              required: true,
              maps_to: "contact.last_name",
            },
            {
              key: "email",
              label: "Your email",
              type: "email",
              required: true,
              maps_to: "contact.email",
            },
            {
              key: "child",
              label: "Your child's first name",
              type: "text",
              maps_to: "student.first_name",
            },
            { key: "notes", label: "How can we help?", type: "textarea", maps_to: "enquiry.notes" },
          ],
        },
      ],
    },
  });
  return form;
}

test("an enquiry from the public form is converted into a client", async ({
  apiAs,
  page,
  pageAs,
}) => {
  const coordinator = await apiAs("coordinator");
  const form = await createForm(coordinator);
  const surname = `Lead${uid()}`;

  // A parent fills in the hosted form (no sign-in).
  await page.goto(`/f/${form.slug}`);
  await expect(page.getByRole("heading", { name: form.name })).toBeVisible();
  // The cookie banner (E29) asks first; necessary cookies only.
  await page
    .getByRole("region", { name: "Cookies" })
    .getByRole("button", { name: "Reject non-essential" })
    .click();
  await expect(page.getByRole("region", { name: "Cookies" })).toBeHidden();
  await page.getByLabel(/Your first name/).fill("Morgan");
  await page.getByLabel(/Your last name/).fill(surname);
  await page.getByLabel(/Your email/).fill(`morgan.${surname.toLowerCase()}@example.com`);
  await page.getByLabel(/Your child's first name/).fill("Billie");
  await page
    .getByLabel(/How can we help/)
    .fill("GCSE Maths help before the mocks, weekday evenings.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("status")).toHaveText("Thank you. We'll be in touch soon.");

  // It is on the pipeline board.
  const staff = await pageAs("coordinator");
  await staff.goto("/leads");
  const card = staff.getByRole("link", { name: new RegExp(surname) });
  await expect(card).toBeVisible();
  await card.click();
  await expect(staff.getByRole("heading", { level: 1, name: new RegExp(surname) })).toBeVisible();

  // Convert with a GCSE Maths job.
  await staff
    .getByRole("combobox", { name: /Service/ })
    .selectOption({ value: await serviceId(coordinator, "GCSE Maths 1:1") });
  await staff.getByRole("button", { name: "Convert to client" }).click();

  const enquiryId = staff.url().split("/leads/")[1]!;
  await expect
    .poll(async () => (await coordinator.get<Enquiry>(`/api/v1/enquiries/${enquiryId}`)).client)
    .toBeTruthy();
  const clients = await coordinator.get<{ results: { display_name: string }[] }>(
    "/api/v1/clients",
    {
      q: surname,
    },
  );
  expect(clients.results.map((c) => c.display_name).join()).toContain(surname);
});

test("the public form refuses a submission without the required email", async ({ apiAs, page }) => {
  const form = await createForm(await apiAs("coordinator"));
  await page.goto(`/f/${form.slug}`);
  await page.getByRole("button", { name: "Reject non-essential" }).click();
  await page.getByLabel(/Your first name/).fill("Sam");
  await page.getByLabel(/Your last name/).fill("Nomail");
  await page.getByRole("button", { name: "Send" }).click();
  // The browser's required-field check (or the API) stops it; no thank-you message.
  await expect(page.getByRole("status")).toHaveCount(0);
});

test("finance cannot see the enquiry pipeline", async ({ apiAs }) => {
  const finance = await apiAs("finance");
  expect((await finance.raw("GET", "/api/v1/enquiries/board")).status()).toBe(403);
});
