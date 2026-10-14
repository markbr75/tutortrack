import {
  enqueue,
  flushOutbox,
  listOutbox,
  resetMemoryStorage,
  retryItem,
  type NewOutboxItem,
} from "./outbox";
import { isOfflineApi, notificationTarget, parsePush } from "./routes";

const ORIGIN = "https://brightminds.tutortrack.app";

interface Sent {
  method: string;
  path: string;
  headers: Headers;
  body: unknown;
}

type Reply = { status: number; body?: unknown } | "network";

/** A fake server: replies per "METHOD /path" (a list is used in order). */
function server(replies: Record<string, Reply | Reply[]>) {
  const sent: Sent[] = [];
  const fetchImpl = vi.fn(async (request: Request) => {
    const url = new URL(request.url);
    const method = request.method;
    const text = method === "GET" ? "" : await request.text();
    sent.push({
      method,
      path: url.pathname,
      headers: request.headers,
      body: text ? JSON.parse(text) : undefined,
    });
    const route = replies[`${method} ${url.pathname}`];
    const reply = Array.isArray(route) ? route.shift() : route;
    if (!reply || reply === "network") throw new TypeError("Failed to fetch");
    return new Response(JSON.stringify(reply.body ?? {}), {
      status: reply.status,
      headers: { "Content-Type": "application/json" },
    });
  });
  return { sent, fetchImpl };
}

const completion: NewOutboxItem = {
  kind: "lesson.complete",
  label: "GCSE Maths",
  lessonId: "l1",
  reportId: null,
  body: { attendance: [], actual_start: null, actual_end: null, override_balance: false },
  etag: null,
  csrf: "csrf-at-queue-time",
};

function report(extra: Partial<NewOutboxItem> = {}): NewOutboxItem {
  return {
    kind: "report.save",
    label: "GCSE Maths",
    lessonId: "l1",
    reportId: "r1",
    body: { answers: { covered: "Fractions" }, submit: false },
    etag: 'W/"v1"',
    csrf: null,
    ...extra,
  };
}

beforeEach(() => resetMemoryStorage());

describe("offline outbox", () => {
  it("replays a completion once, with its idempotency key and CSRF token", async () => {
    const item = await enqueue(completion, "key-1");
    const { sent, fetchImpl } = server({ "POST /api/v1/lessons/l1/complete": { status: 200 } });
    const result = await flushOutbox({ origin: ORIGIN, fetchImpl, csrf: () => "fresh" });
    expect(result).toEqual({ synced: 1, review: 0, pending: 0 });
    expect(sent[0]!.headers.get("Idempotency-Key")).toBe(item.id);
    expect(sent[0]!.headers.get("X-CSRFToken")).toBe("fresh");
    expect(await listOutbox()).toEqual([]);
  });

  it("keeps changes while offline and retries with the same key", async () => {
    await enqueue(completion, "key-2");
    await enqueue(report({ reportId: null }));
    const first = server({ "POST /api/v1/lessons/l1/complete": "network" });
    const offline = await flushOutbox({ origin: ORIGIN, fetchImpl: first.fetchImpl });
    expect(offline).toEqual({ synced: 0, review: 0, pending: 2 });
    expect(first.sent).toHaveLength(1); // the report waits for its lesson's register
    const [waiting] = await listOutbox();
    expect(waiting!.attempts).toBe(1);
    expect(waiting!.csrf).toBe("csrf-at-queue-time");

    const back = server({
      "POST /api/v1/lessons/l1/complete": { status: 200 },
      "POST /api/v1/lessons/l1/reports": { status: 201, body: { id: "r9" } },
      "PUT /api/v1/lesson-reports/r9": { status: 200 },
    });
    const online = await flushOutbox({ origin: ORIGIN, fetchImpl: back.fetchImpl });
    expect(online.synced).toBe(2);
    expect(back.sent[0]!.headers.get("Idempotency-Key")).toBe("key-2");
    expect(back.sent[0]!.headers.get("X-CSRFToken")).toBe("csrf-at-queue-time");
    expect(back.sent.map((s) => `${s.method} ${s.path}`)).toEqual([
      "POST /api/v1/lessons/l1/complete",
      "POST /api/v1/lessons/l1/reports",
      "PUT /api/v1/lesson-reports/r9",
    ]);
  });

  it("puts refused changes up for review with the server's reason", async () => {
    await enqueue(completion);
    const { fetchImpl } = server({
      "POST /api/v1/lessons/l1/complete": {
        status: 422,
        body: { type: "x/business-rule", title: "Rule", detail: "Already completed." },
      },
    });
    const result = await flushOutbox({ origin: ORIGIN, fetchImpl });
    expect(result.review).toBe(1);
    const [item] = await listOutbox();
    expect(item).toMatchObject({ state: "review", problem: "Already completed." });
    await retryItem(item!.id);
    expect((await listOutbox())[0]).toMatchObject({ state: "pending", problem: null });
  });

  it("checks report saves against the version they started from", async () => {
    await enqueue(report({ body: { answers: { covered: "Fractions" }, submit: true } }));
    const { sent, fetchImpl } = server({
      "POST /api/v1/lesson-reports/r1/submit": {
        status: 412,
        body: { title: "Changed", detail: "The resource has changed since you fetched it." },
      },
    });
    const result = await flushOutbox({ origin: ORIGIN, fetchImpl });
    expect(sent[0]!.headers.get("If-Match")).toBe('W/"v1"');
    expect(result.review).toBe(1);
  });

  it("treats a draft the server already has as synced", async () => {
    await enqueue(report());
    const { fetchImpl } = server({
      "PUT /api/v1/lesson-reports/r1": { status: 412, body: { detail: "changed" } },
      "GET /api/v1/lesson-reports/r1": { status: 200, body: { answers: { covered: "Fractions" } } },
    });
    expect((await flushOutbox({ origin: ORIGIN, fetchImpl })).synced).toBe(1);
  });

  it("asks to sign in again instead of dropping changes", async () => {
    await enqueue(completion);
    const { fetchImpl } = server({
      "POST /api/v1/lessons/l1/complete": {
        status: 403,
        body: { type: "x/not-authenticated", detail: "Sign in." },
      },
    });
    await flushOutbox({ origin: ORIGIN, fetchImpl });
    expect((await listOutbox())[0]!.state).toBe("auth");
  });

  it("keeps only the latest answers for a report", async () => {
    await enqueue(report());
    await enqueue(report({ body: { answers: { covered: "Algebra" }, submit: true } }));
    const items = await listOutbox();
    expect(items).toHaveLength(1);
    expect(items[0]!.body).toEqual({ answers: { covered: "Algebra" }, submit: true });
    expect(items[0]!.etag).toBe('W/"v1"');
  });
});

describe("service worker routes", () => {
  it("caches tutor reads only", () => {
    expect(isOfflineApi("/api/v1/tutor/today")).toBe(true);
    expect(isOfflineApi("/api/v1/tutor/offline")).toBe(true);
    expect(isOfflineApi("/api/v1/lessons/0b7c1d2e-3f40-4a5b-8c6d-7e8f9a0b1c2d")).toBe(true);
    expect(isOfflineApi("/api/v1/portal/billing")).toBe(false);
    expect(isOfflineApi("/api/v1/invoices")).toBe(false);
    expect(isOfflineApi("/api/v1/lessons")).toBe(false);
  });

  it("only opens notification links on this site", () => {
    expect(notificationTarget("/portal/tutor/jobs")).toBe("/portal/tutor/jobs");
    expect(notificationTarget("https://evil.example.com")).toBe("/portal/");
    expect(notificationTarget("//evil.example.com")).toBe("/portal/");
    expect(parsePush({ title: "Lesson moved", url: "javascript:alert(1)" })).toMatchObject({
      title: "Lesson moved",
      url: "/portal/",
    });
  });
});
