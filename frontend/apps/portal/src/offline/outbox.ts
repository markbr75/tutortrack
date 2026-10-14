/**
 * The tutor PWA's offline outbox (E16-T08): lesson completions and report saves made
 * without a signal wait here (IndexedDB) and are replayed by the page or, with Background
 * Sync, by the service worker after the page is closed.
 *
 * Replays are idempotent: every request carries an `Idempotency-Key` derived from the item
 * id, so a completion whose response was lost is answered from the server's stored
 * response instead of being recorded twice. Report saves send `If-Match` with the version
 * the tutor started from; a 412 (someone changed it) or any other refusal puts the item in
 * "review" for the tutor instead of overwriting.
 *
 * This module runs in the page and in the service worker: no `window` or `document`.
 */

export type OutboxKind = "lesson.complete" | "report.save";
export type OutboxState = "pending" | "review" | "auth";

export interface CompleteBody {
  attendance: { attendee: string; outcome: string; late_minutes: number | null }[];
  actual_start: null;
  actual_end: null;
  override_balance: boolean;
}

export interface ReportBody {
  answers: Record<string, unknown>;
  submit: boolean;
}

export interface OutboxItem {
  /** Also the base of the Idempotency-Key. */
  id: string;
  kind: OutboxKind;
  /** What the tutor sees in the pending list (the lesson title). */
  label: string;
  lessonId: string;
  reportId: string | null;
  body: CompleteBody | ReportBody;
  /** The report version the tutor edited (If-Match). */
  etag: string | null;
  /** CSRF token captured when queued, for replays from the service worker. */
  csrf: string | null;
  createdAt: string;
  attempts: number;
  state: OutboxState;
  /** The server's reason when the change needs review. */
  problem: string | null;
}

export type NewOutboxItem = Pick<
  OutboxItem,
  "kind" | "label" | "lessonId" | "reportId" | "body" | "etag" | "csrf"
>;

// --- storage --------------------------------------------------------------------------------

const DB_NAME = "tutortrack-offline";
const STORE = "outbox";
export const SYNC_TAG = "tutortrack-outbox";
const CHANNEL = "tutortrack-outbox";

interface Storage {
  all(): Promise<OutboxItem[]>;
  put(item: OutboxItem): Promise<void>;
  remove(id: string): Promise<void>;
  clear(): Promise<void>;
}

function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function idbStorage(factory: IDBFactory): Storage {
  let db: Promise<IDBDatabase> | null = null;
  const open = () => {
    db ??= new Promise((resolve, reject) => {
      const req = factory.open(DB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id" });
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return db;
  };
  const store = async (mode: IDBTransactionMode) =>
    (await open()).transaction(STORE, mode).objectStore(STORE);
  return {
    all: async () => request((await store("readonly")).getAll() as IDBRequest<OutboxItem[]>),
    put: async (item) => void (await request((await store("readwrite")).put(item))),
    remove: async (id) => void (await request((await store("readwrite")).delete(id))),
    clear: async () => void (await request((await store("readwrite")).clear())),
  };
}

function memoryStorage(): Storage {
  const items = new Map<string, OutboxItem>();
  return {
    all: async () => [...items.values()].map((i) => ({ ...i })),
    put: async (item) => void items.set(item.id, { ...item }),
    remove: async (id) => void items.delete(id),
    clear: async () => items.clear(),
  };
}

let storage: Storage = typeof indexedDB !== "undefined" ? idbStorage(indexedDB) : memoryStorage();

/** Tests: start from an empty in-memory outbox. */
export function resetMemoryStorage(): void {
  storage = memoryStorage();
}

// --- change notifications (page ⇄ service worker) --------------------------------------------

const listeners = new Set<() => void>();
const channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel(CHANNEL) : null;
if (channel) channel.onmessage = () => listeners.forEach((l) => l());

function changed(): void {
  listeners.forEach((l) => l());
  channel?.postMessage("changed");
}

export function onOutboxChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => void listeners.delete(listener);
}

// --- the queue ------------------------------------------------------------------------------

export async function listOutbox(): Promise<OutboxItem[]> {
  const items = await storage.all();
  return items.sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

export async function enqueue(
  item: NewOutboxItem,
  id: string = crypto.randomUUID(),
): Promise<OutboxItem> {
  if (item.kind === "report.save") {
    // Only the latest answers for a report matter: update the waiting save rather than
    // queueing a second one that would conflict with the first (same starting version).
    const waiting = (await storage.all()).find(
      (i) => i.kind === "report.save" && i.lessonId === item.lessonId && i.state !== "review",
    );
    if (waiting) {
      const merged: OutboxItem = {
        ...waiting,
        label: item.label || waiting.label,
        body: item.body,
        reportId: waiting.reportId ?? item.reportId,
        csrf: item.csrf ?? waiting.csrf,
      };
      await storage.put(merged);
      changed();
      return merged;
    }
  }
  const full: OutboxItem = {
    ...item,
    id,
    createdAt: new Date().toISOString(),
    attempts: 0,
    state: "pending",
    problem: null,
  };
  await storage.put(full);
  changed();
  return full;
}

export async function discard(id: string): Promise<void> {
  await storage.remove(id);
  changed();
}

/** "Try again" on an item that needed review (e.g. after fixing it online). */
export async function retryItem(id: string): Promise<void> {
  const item = (await storage.all()).find((i) => i.id === id);
  if (!item) return;
  await storage.put({ ...item, state: "pending", problem: null });
  changed();
}

/** Sign-out or another user on this device: nothing of theirs may stay behind. */
export async function clearOutbox(): Promise<void> {
  await storage.clear();
  changed();
}

// --- replay ---------------------------------------------------------------------------------

export interface FlushOptions {
  /** Absolute base URL (the organisation's host). */
  origin: string;
  /** The current CSRF token (the page reads the cookie; the worker uses the stored one). */
  csrf?: () => string | null | undefined;
  fetchImpl?: (request: Request) => Promise<Response>;
}

export interface FlushResult {
  synced: number;
  review: number;
  pending: number;
}

type Outcome =
  { kind: "done" } | { kind: "retry" } | { kind: "auth" } | { kind: "review"; problem: string };

interface Problem {
  type?: string;
  title?: string;
  detail?: unknown;
  errors?: Record<string, string[]>;
}

async function problemOf(response: Response): Promise<Problem> {
  try {
    return (await response.clone().json()) as Problem;
  } catch {
    return {};
  }
}

async function classify(response: Response): Promise<Outcome> {
  if (response.ok) return { kind: "done" };
  const problem = await problemOf(response);
  const type = problem.type ?? "";
  const detail = typeof problem.detail === "string" ? problem.detail : "";
  if (
    response.status === 401 ||
    type.endsWith("not-authenticated") ||
    type.endsWith("authentication-failed") ||
    detail.startsWith("CSRF Failed")
  ) {
    return { kind: "auth" };
  }
  if (
    response.status >= 500 ||
    [408, 425, 429].includes(response.status) ||
    type.endsWith("idempotency-request-in-progress")
  ) {
    return { kind: "retry" };
  }
  const fieldErrors = Object.values(problem.errors ?? {}).flat();
  return {
    kind: "review",
    problem: fieldErrors[0] ?? (detail || problem.title || response.statusText || "Error"),
  };
}

let running: Promise<FlushResult> | null = null;

/** Replay everything that's waiting, oldest first. Safe to call often and from both the
 * page and the worker: one run at a time per context, and idempotency keys make a request
 * sent by both harmless. */
export function flushOutbox(options: FlushOptions): Promise<FlushResult> {
  running ??= flush(options).finally(() => {
    running = null;
  });
  return running;
}

async function flush(options: FlushOptions): Promise<FlushResult> {
  // Resolve fetch per call (instrumentation and test stubs apply) and pass a Request.
  const doFetch = options.fetchImpl ?? ((request: Request) => fetch(request));
  const result: FlushResult = { synced: 0, review: 0, pending: 0 };
  const blockedLessons = new Set<string>();
  let offline = false;
  for (const item of await listOutbox()) {
    if (item.state === "review") {
      result.review += 1;
      continue;
    }
    if (offline || blockedLessons.has(item.lessonId)) {
      result.pending += 1;
      continue;
    }
    let outcome: Outcome;
    try {
      outcome = await replay(item, options, doFetch);
    } catch {
      outcome = { kind: "retry" };
      offline = true; // the network is down: try again when it's back
    }
    if (outcome.kind === "done") {
      await storage.remove(item.id);
      result.synced += 1;
    } else if (outcome.kind === "review") {
      await storage.put({ ...item, state: "review", problem: outcome.problem });
      result.review += 1;
    } else {
      const state = outcome.kind === "auth" ? "auth" : "pending";
      await storage.put({ ...item, state, attempts: item.attempts + 1 });
      blockedLessons.add(item.lessonId); // keep this lesson's later changes in order
      result.pending += 1;
    }
  }
  changed();
  return result;
}

async function replay(
  item: OutboxItem,
  options: FlushOptions,
  doFetch: (request: Request) => Promise<Response>,
): Promise<Outcome> {
  const csrf = options.csrf?.() ?? item.csrf;
  const send = (method: string, path: string, body: unknown, extra: Record<string, string>) => {
    const headers: Record<string, string> = { "Content-Type": "application/json", ...extra };
    if (csrf) headers["X-CSRFToken"] = csrf;
    return doFetch(
      new Request(`${options.origin}${path}`, {
        method,
        headers,
        credentials: "include",
        body: JSON.stringify(body),
      }),
    );
  };

  if (item.kind === "lesson.complete") {
    const response = await send("POST", `/api/v1/lessons/${item.lessonId}/complete`, item.body, {
      "Idempotency-Key": item.id,
    });
    return classify(response);
  }

  const body = item.body as ReportBody;
  let reportId = item.reportId;
  if (!reportId) {
    // A report started offline: open it (get-or-create on the server) first.
    const opened = await send(
      "POST",
      `/api/v1/lessons/${item.lessonId}/reports`,
      {},
      {
        "Idempotency-Key": `${item.id}:open`,
      },
    );
    const outcome = await classify(opened);
    if (outcome.kind !== "done") return outcome;
    reportId = ((await opened.json()) as { id: string }).id;
    await storage.put({ ...item, reportId });
  }
  const ifMatch: Record<string, string> = item.etag ? { "If-Match": item.etag } : {};
  const path = `/api/v1/lesson-reports/${reportId}`;
  const response = body.submit
    ? await send(
        "POST",
        `${path}/submit`,
        { answers: body.answers },
        {
          "Idempotency-Key": `${item.id}:submit`,
          ...ifMatch,
        },
      )
    : await send("PUT", path, { answers: body.answers }, ifMatch);
  if (response.status === 412 && !body.submit) {
    // A draft saved earlier whose response was lost also changes the version: if the
    // server already has exactly these answers, there is nothing to review.
    const current = await doFetch(
      new Request(`${options.origin}${path}`, { credentials: "include" }),
    );
    if (current.ok) {
      const saved = ((await current.json()) as { answers: Record<string, unknown> }).answers;
      if (sameAnswers(saved, body.answers)) return { kind: "done" };
    }
  }
  return classify(response);
}

function sameAnswers(a: Record<string, unknown>, b: Record<string, unknown>): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const key of keys) {
    if (JSON.stringify(a[key] ?? null) !== JSON.stringify(b[key] ?? null)) return false;
  }
  return true;
}
