interface Reply {
  status?: number;
  body: unknown;
}
type Route = Reply | ((body: unknown, url: URL) => Reply);

export interface RecordedCall {
  method: string;
  path: string;
  /** The query string, e.g. "?preview=true" ("" when there is none). */
  search: string;
  body: unknown;
}

/** Stubs fetch with per-route replies: `mockApi({"GET /api/v1/features": {body: {...}}})`.
 * Unmatched requests get a 404 problem. Returns the recorded calls (with parsed bodies). */
export function mockApi(routes: Record<string, Route>): RecordedCall[] {
  const calls: RecordedCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string, init?: RequestInit) => {
      // Direct uploads (G5a) call fetch(url, init) for the presigned PUT; the Help panel
      // fetches /guides/routes.json the same way.
      if (typeof input === "string") {
        const url = new URL(input, window.location.origin);
        calls.push({
          method: init?.method ?? "GET",
          path: url.pathname,
          search: url.search,
          body: undefined,
        });
        const route = routes[`${init?.method ?? "GET"} ${url.pathname}`];
        const reply = typeof route === "function" ? route(undefined, url) : route;
        return new Response(reply?.body === undefined ? null : JSON.stringify(reply.body), {
          status: reply ? (reply.status ?? 200) : 404,
        });
      }
      const request = input;
      const url = new URL(request.url);
      const path = url.pathname;
      const text = request.method === "GET" ? "" : await request.clone().text();
      const body: unknown = text ? JSON.parse(text) : undefined;
      calls.push({ method: request.method, path, search: url.search, body });
      const route = routes[`${request.method} ${path}`];
      const reply = typeof route === "function" ? route(body, url) : route;
      const status = reply ? (reply.status ?? 200) : 404;
      const payload = reply ? reply.body : { type: "about:blank", title: "Not found", status };
      return new Response(JSON.stringify(payload), {
        status,
        headers: {
          "Content-Type": status >= 400 ? "application/problem+json" : "application/json",
        },
      });
    }),
  );
  return calls;
}

/** A signed-in admin, as returned by `GET /api/v1/me`. */
export const ME = {
  user: { id: "u1", email: "sam@example.com", first_name: "Sam", has_mfa: false },
  organisation: { id: "o1", name: "Bright Minds", slug: "brightminds", status: "active" },
  membership: { id: "m1", role: "admin", branch_scope: "all" },
  permissions: { "team.view": "all", "org.settings.view": "all" },
  features: {},
  impersonator: null,
};
