/**
 * Jobs and scheduling (E07, E08): set up a weekly job for a student with a tutor, see the
 * lesson series on the calendar, and find a tutor for a job that has none.
 * Test plan: TP-E07, TP-E08.
 */
import { createFamily, createTutor, expect, mondayNextWeek, serviceId, test } from "./fixtures";

test("a coordinator sets up weekly lessons and sees them on the calendar", async ({
  apiAs,
  pageAs,
}) => {
  const api = await apiAs("coordinator");
  const family = await createFamily(api, { students: ["Quinn"] });
  const tutor = await createTutor(api);
  const start = mondayNextWeek();

  const page = await pageAs("coordinator");
  await page.goto(`/students/${family.studentIds[0]}`);
  await page.getByRole("button", { name: "Set up lessons" }).click();
  const form = page.getByRole("form", { name: "Set up lessons" });
  await form.getByLabel("Service").selectOption({ label: "GCSE Maths 1:1" });
  await form.getByLabel("Tutor").selectOption({ label: tutor.name });
  await form.getByLabel("Day").selectOption({ label: "Wednesday" });
  await form.getByLabel("Time").fill("17:00");
  await form.getByLabel("Starts").fill(start);
  await form.getByRole("button", { name: "Create job" }).click();

  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]+$/);
  await expect(page.getByText(/· Active ·/)).toBeVisible();
  await expect(page.getByText("Wednesday 17:00")).toBeVisible();
  await expect(page.getByText(tutor.name).first()).toBeVisible();

  // The weekly series is on the calendar from next week, at 17:00 London time.
  await page.goto("/calendar");
  await page.getByRole("group", { name: "View" }).getByRole("button", { name: "Agenda" }).click();
  await page.getByLabel("Tutor", { exact: true }).selectOption({ label: tutor.name });
  await page.getByRole("button", { name: "Next" }).click();
  const lesson = page.getByRole("button", { name: new RegExp(`17:00.*${tutor.name}`) });
  await expect(lesson).toHaveCount(1);
  await expect(page.getByRole("heading", { name: /^Wednesday/ })).toBeVisible();
});

test("a job without a tutor is seeking one until a tutor is added", async ({ apiAs, pageAs }) => {
  const api = await apiAs("coordinator");
  const family = await createFamily(api, { students: ["Harper"] });
  const tutor = await createTutor(api);
  const job = await api.post<{ id: string; status: string }>("/api/v1/jobs/quick-setup", {
    student: family.studentIds[0],
    service: await serviceId(api, "GCSE Maths 1:1"),
  });
  expect(job.status).toBe("seeking_tutor");

  const page = await pageAs("coordinator");
  await page.goto(`/jobs/${job.id}`);
  await expect(page.getByText(/· Seeking tutor ·/)).toBeVisible();
  await page.getByLabel("Add a tutor").selectOption({ label: tutor.name });
  await page.getByRole("button", { name: "Assign" }).click();
  await expect(page.getByText(/· Active ·/)).toBeVisible();
  await expect(page.getByText(tutor.name).first()).toBeVisible();
});
