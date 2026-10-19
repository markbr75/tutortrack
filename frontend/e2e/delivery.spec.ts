/**
 * Lesson delivery (E09): complete a past lesson from the calendar with a register, and
 * confirm forgotten lessons in bulk from "Unconfirmed lessons". Test plan: TP-E09.
 */
import {
  createFamily,
  createJob,
  createLesson,
  createTutor,
  expect,
  londonToday,
  test,
  type Api,
} from "./fixtures";

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function pastLesson(api: Api, days = -1) {
  const family = await createFamily(api, { students: ["Remy"] });
  const tutor = await createTutor(api);
  const job = await createJob(api, { studentId: family.studentIds[0]!, tutorId: tutor.id });
  const lesson = await createLesson(api, { jobId: job.id, days, at: "10:00" });
  return { family, tutor, job, lesson };
}

test("a coordinator completes yesterday's lesson from the calendar with a register", async ({
  apiAs,
  pageAs,
}) => {
  const api = await apiAs("coordinator");
  const { family, tutor, lesson } = await pastLesson(api);

  const page = await pageAs("coordinator");
  await page.goto("/calendar");
  await page.getByRole("group", { name: "View" }).getByRole("button", { name: "Agenda" }).click();
  await page.getByLabel("Tutor", { exact: true }).selectOption({ label: tutor.name });
  // Yesterday is last week when today is a Monday.
  const [y, m, d] = londonToday().split("-").map(Number) as [number, number, number];
  if (new Date(Date.UTC(y, m - 1, d)).getUTCDay() === 1) {
    await page.getByRole("button", { name: "Previous" }).click();
  }
  await page.getByRole("button", { name: new RegExp(`10:00.*${escape(tutor.name)}`) }).click();

  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Mark completed" }).click();
  const student = `Remy ${family.name.replace(/^The | Family$/g, "")}`;
  await dialog.getByLabel(`Attendance for ${student}`).selectOption({ label: "Late" });
  await dialog.getByLabel(`Minutes late for ${student}`).fill("10");
  await dialog.getByRole("button", { name: "Complete lesson" }).click();
  await expect(dialog).toBeHidden();
  await expect(
    page.getByRole("button", { name: new RegExp(`${escape(tutor.name)} · Completed`) }),
  ).toBeVisible();

  const saved = await api.get<{ status: string }>(`/api/v1/lessons/${lesson.id}`);
  expect(saved.status).toBe("completed");
});

test("forgotten lessons are confirmed in bulk from Unconfirmed lessons", async ({
  apiAs,
  pageAs,
}) => {
  const api = await apiAs("coordinator");
  // Unconfirmed means ended more than 24 hours ago (delivery.unconfirmed_after_hours), so
  // yesterday's 10:00 lesson only qualifies after 11:00: take one from two days ago.
  const { job, lesson } = await pastLesson(api, -2);

  const page = await pageAs("coordinator");
  await page.goto("/unconfirmed");
  await expect(page.getByRole("heading", { name: "Unconfirmed lessons" })).toBeVisible();
  const checkbox = page.getByRole("checkbox", { name: `Select ${job.name}` });
  await checkbox.check();
  await page.getByRole("button", { name: "Mark completed" }).click();
  await expect(page.getByText("1 updated, 0 couldn't be changed.")).toBeVisible();
  await expect(checkbox).toHaveCount(0);

  const saved = await api.get<{ status: string }>(`/api/v1/lessons/${lesson.id}`);
  expect(saved.status).toBe("completed");
});

test("a tutor cannot see another tutor's lessons", async ({ apiAs }) => {
  const coordinator = await apiAs("coordinator");
  const { lesson } = await pastLesson(coordinator);
  const nia = await apiAs("tutor");
  const response = await nia.raw("GET", `/api/v1/lessons/${lesson.id}`);
  expect([403, 404]).toContain(response.status());
});
