/**
 * Typed client for the TutorTrack API, generated from the backend OpenAPI schema
 * (`make api-client`). Never hand-write request/response types: regenerate instead.
 */
import createClient, { type Middleware } from "openapi-fetch";

import type { paths } from "./schema";

export type { components, paths } from "./schema";

/** RFC 7807 problem returned by every API error. */
export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: unknown;
  errors?: Record<string, string[]>;
  request_id?: string;
  [extension: string]: unknown;
}

export class ApiError extends Error {
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(typeof problem.detail === "string" ? problem.detail : problem.title);
    this.name = "ApiError";
    this.problem = problem;
  }

  get status(): number {
    return this.problem.status;
  }

  /** Short problem code, e.g. "validation-error" or "upgrade-required". */
  get code(): string {
    return this.problem.type.split("/").pop() ?? this.problem.type;
  }
}

export function readCookie(name: string): string | undefined {
  if (typeof document === "undefined") return undefined;
  return document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`))
    ?.split("=")[1];
}

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** Adds the Django CSRF token to unsafe requests (session auth). */
export const csrfMiddleware: Middleware = {
  onRequest({ request }) {
    if (UNSAFE_METHODS.has(request.method)) {
      const token = readCookie("csrftoken");
      if (token) request.headers.set("X-CSRFToken", decodeURIComponent(token));
    }
    return request;
  },
};

export function createApiClient(baseUrl?: string) {
  // Absolute URLs work everywhere (Node test runners reject relative Request URLs).
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const client = createClient<paths>({
    baseUrl: baseUrl ?? origin,
    credentials: "include",
    // Resolve fetch per call (not at creation) so instrumentation and test stubs apply.
    fetch: (request: Request) => globalThis.fetch(request),
  });
  client.use(csrfMiddleware);
  return client;
}

export type ApiClient = ReturnType<typeof createApiClient>;

/** Unwraps an openapi-fetch result, throwing ApiError for problem responses. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || !result.response.ok) {
    const body = result.error as Partial<Problem> | undefined;
    throw new ApiError({
      ...body,
      type: body?.type ?? "about:blank",
      title: body?.title ?? result.response.statusText,
      status: body?.status ?? result.response.status,
    });
  }
  return result.data as T;
}

/** A fresh key for POSTs that must be safe to retry (payments, invoices...). */
export function idempotencyKey(): string {
  return crypto.randomUUID();
}
