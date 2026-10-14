/**
 * Tutor portal (E16) and lesson reports (E09): Nia Adeyemi completes yesterday's lesson,
 * writes the report, staff approve and share it, and the parent reads it in the portal.
 * Test plan: TP-E16, TP-E09, TP-E15.
 */
import { PORTAL, createJob, createLesson, expect, findId, test, uid } from "./fixtures";

test("a tutor reports on a lesson, staff approve and share it, and the parent reads it", async ({
  apiAs,
  pageAs,
}) => {
  const coordinator = await apiAs("coordinator");
  const nia = await findId(coordinator, "/api/v1/tutors", "email", "nia.adeyemi@example.com", {
    q: "Nia",
  });
  const maya = await findId(coordinator, "/api/v1/students", "first_name", "Maya", { q: "Maya" });
  const job = await createJob(coordinator, {
    studentId: maya,
    tutorId: nia,
    service: "Piano lesson",
  });
  const lesson = await createLesson(coordinator, {
    jobId: job.id,
    days: -1,
    at: "11:00",
    minutes: 30,
  });
  const covered = `Scales in D major and sight-reading ${uid()}`;

  // The tutor completes the lesson with a register and writes the report.
  const tutor = await pageAs("tutor");
  await tutor.goto(`${PORTAL}tutor/lessons/${lesson.id}`);
  await tutor.getByLabel("Attendance for Maya Patel").selectOption({ label: "Present" });
  await tutor.getByRole("button", { name: "Complete and write report" }).click();
  await expect(tutor.getByRole("heading", { name: `Report: ${lesson.title}` })).toBeVisible();
  await tutor.getByLabel(/What we covered/).fill(covered);
  await tutor.getByLabel(/Notes for parent/).fill("Lovely progress this week.");
  await tutor.getByRole("button", { name: "Submit report" }).click();
  await expect(tutor.getByText("Report submitted. Thank you!")).toBeVisible();

  // Staff approve and share it.
  const reports = await coordinator.get<{ results: { id: string; status: string }[] }>(
    "/api/v1/lesson-reports",
    { lesson: lesson.id },
  );
  const report = reports.results[0]!;
  expect(report.status).toBe("submitted");
  const staff = await pageAs("coordinator");
  await staff.goto(`/reports/${report.id}`);
  await staff.getByRole("button", { name: "Approve" }).click();
  const share = staff.getByRole("button", { name: "Share with client" });
  await expect(share.or(staff.getByText(/^Shared /))).toBeVisible();
  if (await share.isVisible()) await share.click();
  await expect(staff.getByText(/^Shared /)).toBeVisible();

  // Priya reads it in the portal; the staff-only notes stay hidden.
  const parent = await pageAs("parent");
  await parent.goto(`${PORTAL}reports`);
  const card = parent.getByRole("article").filter({ hasText: covered });
  await expect(card).toBeVisible();
  await expect(card).toContainText("Lovely progress this week.");
  await expect(card).not.toContainText("Private notes");
});

test("a tutor's schedule lists only their own lessons", async ({ pageAs }) => {
  const page = await pageAs("tutor");
  await page.goto(`${PORTAL}tutor/schedule`);
  await expect(page.getByRole("heading", { name: "Lessons" })).toBeVisible();
  await expect(page.getByText(/GCSE Higher Maths – Arjun Patel/).first()).toBeVisible();
  // Other specs book "Remy" and "Quinn" with other tutors: never on Nia's list.
  await expect(page.getByText(/– (Remy|Quinn) /)).toHaveCount(0);
});
