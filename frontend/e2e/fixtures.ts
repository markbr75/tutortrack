/**
 * Shared Playwright fixtures for the TutorTrack journeys (docs/test-plan/README.md).
 *
 * - Accounts come from `seed_demo` (backend/tutortrack/identity/seeds.py): one per role, all
 *   with the shared seed password.
 * - `pageAs(role)` opens a signed-in browser page; `apiAs(role)` gives a signed-in API client
 *   for arranging data. Sessions are cached per worker (the login endpoint is rate limited),
 *   so never sign out of a cached session: use `freshPageAs` for sign-out tests.
 * - Every spec creates the records it changes, named with `uid()`, so specs run in any order.
 */
import {
  test as base,
  expect,
  request as playwrightRequest,
  type APIRequestContext,
  type APIResponse,
  type Browser,
  type BrowserContext,
  type Page,
} from "@playwright/test";

export { expect };

export const PASSWORD = process.env.SEED_ADMIN_PASSWORD ?? "tutortrack";
export const ADMIN_URL = process.env.E2E_BASE_URL ?? "http://brightminds.localhost:5173";
/** The second seeded organisation, used for tenant-isolation checks. */
export const OTHER_ORG_URL = process.env.E2E_OTHER_ORG_URL ?? "http://northside.localhost:5173";
/** The portal is served at /portal/ on the organisation's host (proxied locally). */
export const PORTAL = "/portal/";

export const ACCOUNTS = {
  owner: "admin@tutortrack.localhost",
  admin: "office@tutortrack.localhost",
  branchManager: "manager@tutortrack.localhost",
  coordinator: "coordinator@tutortrack.localhost",
  finance: "finance@tutortrack.localhost",
  tutor: "tutor@tutortrack.localhost",
  parent: "parent@tutortrack.localhost",
  student: "student@tutortrack.localhost",
  affiliate: "affiliate@tutortrack.localhost",
  platform: "platform@tutortrack.localhost",
  otherOwner: "owner@northside.localhost",
} as const;
export type Role = keyof typeof ACCOUNTS;

type StorageState = Awaited<ReturnType<APIRequestContext["storageState"]>>;

/** A short unique suffix for record names, so parallel and repeated runs never collide. */
export function uid(): string {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`.toUpperCase();
}

const sessions = new Map<string, StorageState>();

async function signIn(email: string, baseURL: string): Promise<StorageState> {
  const key = `${baseURL}|${email}`;
  const cached = sessions.get(key);
  if (cached) return cached;
  const context = await playwrightRequest.newContext({ baseURL });
  try {
    const response = await context.post("/api/v1/auth/login", {
      data: { email, password: PASSWORD, remember: false },
    });
    expect(response.ok(), `sign in as ${email}: ${await response.text()}`).toBeTruthy();
    await context.get("/api/v1/me"); // sets the CSRF cookie
    const state = await context.storageState();
    sessions.set(key, state);
    return state;
  } finally {
    await context.dispose();
  }
}

function csrfToken(state: StorageState): string {
  return state.cookies.find((cookie) => cookie.name === "csrftoken")?.value ?? "";
}

/** A thin JSON client that fails the test with the problem detail on any error. */
export class Api {
  constructor(
    readonly request: APIRequestContext,
    readonly csrf: string,
  ) {}

  private async json<T>(response: APIResponse, what: string): Promise<T> {
    expect(response.ok(), `${what} -> ${response.status()}: ${await response.text()}`).toBeTruthy();
    return (response.status() === 204 ? undefined : await response.json()) as T;
  }

  async get<T = unknown>(path: string, params?: Record<string, string | number | boolean>) {
    return this.json<T>(await this.request.get(path, { params }), `GET ${path}`);
  }

  async post<T = unknown>(path: string, data: unknown = {}, headers: Record<string, string> = {}) {
    const response = await this.request.post(path, {
      data,
      headers: { "X-CSRFToken": this.csrf, ...headers },
    });
    return this.json<T>(response, `POST ${path}`);
  }

  async patch<T = unknown>(path: string, data: unknown) {
    const response = await this.request.patch(path, {
      data,
      headers: { "X-CSRFToken": this.csrf },
    });
    return this.json<T>(response, `PATCH ${path}`);
  }

  async put<T = unknown>(path: string, data: unknown) {
    const response = await this.request.put(path, {
      data,
      headers: { "X-CSRFToken": this.csrf },
    });
    return this.json<T>(response, `PUT ${path}`);
  }

  /** The raw response, for asserting refusals (403/404). */
  async raw(method: "GET" | "POST" | "PATCH" | "DELETE", path: string, data?: unknown) {
    return this.request.fetch(path, {
      method,
      data,
      headers: method === "GET" ? {} : { "X-CSRFToken": this.csrf },
    });
  }
}

/** Results of list endpoints (cursor pagination: `{results, next, previous}`). */
export type Page_<T> = { results: T[]; next: string | null; previous: string | null };

type Fixtures = {
  /** A browser page signed in as `role` (on the brightminds host unless `baseURL` given). */
  pageAs: (role: Role, baseURL?: string) => Promise<Page>;
  /** Like `pageAs` but with a brand-new session (safe to sign out of). */
  freshPageAs: (role: Role, baseURL?: string) => Promise<Page>;
  /** An API client signed in as `role`. */
  apiAs: (role: Role, baseURL?: string) => Promise<Api>;
};

async function newPage(
  browser: Browser,
  contexts: BrowserContext[],
  state: StorageState,
  baseURL: string,
) {
  const context = await browser.newContext({
    baseURL,
    storageState: state,
    locale: "en-GB",
    timezoneId: "Europe/London",
    serviceWorkers: "block",
  });
  contexts.push(context);
  return context.newPage();
}

export const test = base.extend<Fixtures>({
  pageAs: async ({ browser }, use) => {
    const contexts: BrowserContext[] = [];
    await use(async (role, baseURL = ADMIN_URL) =>
      newPage(browser, contexts, await signIn(ACCOUNTS[role], baseURL), baseURL),
    );
    await Promise.all(contexts.map((context) => context.close()));
  },
  freshPageAs: async ({ browser }, use) => {
    const contexts: BrowserContext[] = [];
    await use(async (role, baseURL = ADMIN_URL) => {
      const context = await playwrightRequest.newContext({ baseURL });
      const response = await context.post("/api/v1/auth/login", {
        data: { email: ACCOUNTS[role], password: PASSWORD, remember: false },
      });
      expect(response.ok()).toBeTruthy();
      const state = await context.storageState();
      await context.dispose();
      return newPage(browser, contexts, state, baseURL);
    });
    await Promise.all(contexts.map((context) => context.close()));
  },
  apiAs: async ({}, use) => {
    const contexts: APIRequestContext[] = [];
    await use(async (role, baseURL = ADMIN_URL) => {
      const state = await signIn(ACCOUNTS[role], baseURL);
      const context = await playwrightRequest.newContext({ baseURL, storageState: state });
      contexts.push(context);
      return new Api(context, csrfToken(state));
    });
    await Promise.all(contexts.map((context) => context.dispose()));
  },
});

// --- data helpers (API) ---------------------------------------------------------------------

export type Family = { clientId: string; contactId: string; studentIds: string[]; name: string };

/** A new family (one parent, one or more students) created through the quick-add API. */
export async function createFamily(
  api: Api,
  options: { lastName?: string; students?: string[]; email?: string; yearGroup?: string } = {},
): Promise<Family> {
  const lastName = options.lastName ?? `E2e${uid()}`;
  const students = options.students ?? ["Robin"];
  const created = await api.post<{
    id: string;
    display_name: string;
    contacts: { id: string }[];
    students: { id: string }[];
  }>("/api/v1/clients/quick-add", {
    contact: {
      first_name: "Pat",
      last_name: lastName,
      email: options.email ?? `pat.${lastName.toLowerCase()}@example.com`,
    },
    students: students.map((first) => ({
      first_name: first,
      last_name: lastName,
      year_group: options.yearGroup ?? "Year 9",
      subjects: [{ subject: "Maths", level: "GCSE" }],
    })),
  });
  return {
    clientId: created.id,
    contactId: created.contacts[0]!.id,
    studentIds: created.students.map((s) => s.id),
    name: created.display_name,
  };
}

/** The id of the first record whose `field` equals `value` in a list endpoint. */
export async function findId(
  api: Api,
  path: string,
  field: string,
  value: string,
  params: Record<string, string> = {},
): Promise<string> {
  const page = await api.get<Page_<Record<string, unknown>> | Record<string, unknown>[]>(path, {
    page_size: 200,
    ...params,
  });
  const rows = Array.isArray(page) ? page : page.results;
  const row = rows.find((r) => r[field] === value);
  expect(row, `${path}: no row with ${field}=${value}`).toBeTruthy();
  return String(row!.id);
}

/** Today's date in the organisation's time zone (Europe/London) as YYYY-MM-DD. */
export function londonToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/London" }).format(new Date());
}

/** `iso` (YYYY-MM-DD) moved by `days`. */
export function addDays(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/** Monday of next week (London), so a weekly slot never lands in the past or today. */
export function mondayNextWeek(): string {
  const today = londonToday();
  const [y, m, d] = today.split("-").map(Number) as [number, number, number];
  const weekday = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7; // Monday = 0
  return addDays(today, 7 - weekday);
}

/** `HH:MM` on `iso` in Europe/London as an ISO timestamp with the right UTC offset. */
export function londonTime(iso: string, hhmm: string): string {
  const [y, m, d] = iso.split("-").map(Number) as [number, number, number];
  const name = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/London",
    timeZoneName: "longOffset",
  })
    .formatToParts(new Date(Date.UTC(y, m - 1, d, 12)))
    .find((part) => part.type === "timeZoneName")?.value;
  const offset = name && name !== "GMT" ? name.replace("GMT", "") : "+00:00";
  return `${iso}T${hhmm}:00${offset}`;
}

/** A new active tutor (fresh each time, so their diary never clashes between runs). */
export async function createTutor(api: Api, subjects = [{ subject: "Maths", level: "GCSE" }]) {
  const last = `Tutor${uid()}`;
  const tutor = await api.post<{ id: string }>("/api/v1/tutors", {
    first_name: "Alex",
    last_name: last,
    email: `alex.${last.toLowerCase()}@example.com`,
  });
  await api.post(`/api/v1/tutors/${tutor.id}/status`, { status: "active" });
  await api.put(`/api/v1/tutors/${tutor.id}/subjects`, subjects);
  return { id: tutor.id, name: `Alex ${last}` };
}

/** The id of a catalogue service by name (seeded: "GCSE Maths 1:1", "Piano lesson"...). */
export async function serviceId(api: Api, name: string): Promise<string> {
  return findId(api, "/api/v1/catalogue/services", "name", name);
}

/** A job for one student with an assigned tutor (no weekly schedule). */
export async function createJob(
  api: Api,
  options: { studentId: string; tutorId: string; service?: string },
) {
  return api.post<{ id: string; name: string }>("/api/v1/jobs/quick-setup", {
    student: options.studentId,
    service: await serviceId(api, options.service ?? "GCSE Maths 1:1"),
    tutor: options.tutorId,
  });
}

/** A single lesson on a job at a fixed London time, `days` from today (-1 = yesterday). */
export async function createLesson(
  api: Api,
  options: { jobId: string; days: number; at?: string; minutes?: number },
) {
  const start = londonTime(addDays(londonToday(), options.days), options.at ?? "10:00");
  const end = new Date(new Date(start).getTime() + (options.minutes ?? 60) * 60_000);
  const created = await api.post<{
    lesson: { id: string; start: string; status: string; title: string };
  }>("/api/v1/lessons", {
    job: options.jobId,
    start,
    end: end.toISOString(),
    timezone: "Europe/London",
    override_conflicts: true,
  });
  return created.lesson;
}
