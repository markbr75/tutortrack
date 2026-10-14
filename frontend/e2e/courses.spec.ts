/**
 * Group classes and courses (E20): enrol a Year 6 student in an 11+ class, see the fee
 * quote and the place taken, and fall back to the waiting list when the class is full.
 * Each test opens its own class so places never run out between runs. Test plan: TP-E20.
 */
import {
  createFamily,
  createTutor,
  expect,
  findId,
  mondayNextWeek,
  test,
  uid,
  type Api,
} from "./fixtures";

async function openClass(api: Api, capacity: number) {
  const course = await findId(api, "/api/v1/courses", "name", "Year 6 11+ Prep");
  const term = await findId(api, "/api/v1/terms", "name", "This term");
  const tutor = await createTutor(api);
  const created = await api.post<{ group_class: { id: string; name: string } }>("/api/v1/classes", {
    course,
    term,
    name: `Wednesday 11+ ${uid()}`,
    capacity,
    year_groups: ["Year 5", "Year 6"],
    teachers: [{ tutor: tutor.id, role: "lead" }],
    start_time: "17:00",
    duration_minutes: 60,
    rrule: "FREQ=WEEKLY;BYDAY=WE",
    start_date: mondayNextWeek(),
    status: "open",
    conflict_mode: "create",
  });
  return created.group_class;
}

test("a coordinator enrols a Year 6 student in a class", async ({ apiAs, pageAs }) => {
  const api = await apiAs("coordinator");
  const groupClass = await openClass(api, 4);
  const family = await createFamily(api, { students: ["Kit"], yearGroup: "Year 6" });
  const student = `Kit ${family.name.replace(/^The | Family$/g, "")}`;

  const page = await pageAs("coordinator");
  await page.goto(`/classes/${groupClass.id}`);
  await expect(page.getByRole("heading", { level: 1, name: groupClass.name })).toBeVisible();
  await expect(page.getByText("0 of 4 taken")).toBeVisible();

  await page.getByLabel("Student", { exact: true }).selectOption({ label: student });
  await expect(page.getByText(/^Fee: £/)).toBeVisible();
  await page.getByRole("button", { name: "Enrol", exact: true }).click();

  const row = page.getByRole("row").filter({ hasText: student });
  await expect(row).toBeVisible();
  await expect(row).toContainText(/Enrolled|Waiting for payment/);
  await expect(page.getByText("1 of 4 taken")).toBeVisible();
});

test("a full class offers the waiting list instead", async ({ apiAs, pageAs }) => {
  const api = await apiAs("coordinator");
  const groupClass = await openClass(api, 1);
  const first = await createFamily(api, { students: ["Ash"], yearGroup: "Year 6" });
  await api.post("/api/v1/enrolments", {
    group_class: groupClass.id,
    student: first.studentIds[0],
    trial: false,
    override_capacity: false,
    skip_eligibility: false,
  });
  const second = await createFamily(api, { students: ["Eden"], yearGroup: "Year 5" });
  const student = `Eden ${second.name.replace(/^The | Family$/g, "")}`;

  const page = await pageAs("coordinator");
  await page.goto(`/classes/${groupClass.id}`);
  await expect(page.getByText("1 of 1 taken")).toBeVisible();
  await page.getByLabel("Student", { exact: true }).selectOption({ label: student });
  await page.getByRole("button", { name: "Add to the waitlist" }).click();
  await expect(page.getByText(student).last()).toBeVisible();
  await expect(page.getByText("1 of 1 taken")).toBeVisible();
});
