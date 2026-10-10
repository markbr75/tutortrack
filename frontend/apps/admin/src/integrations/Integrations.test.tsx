import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const PERMS = {
  ...ME.permissions,
  "integrations.personal": "all",
  "integrations.view": "all",
  "integrations.manage": "all",
  "org.settings.manage": "all",
};

const PROVIDERS = [
  {
    key: "google",
    name: "Google Calendar and Meet",
    capabilities: ["calendar", "video"],
    auth: "oauth2",
    levels: ["user"],
    credential_fields: [],
    simulated: true,
  },
  {
    key: "lessonspace",
    name: "Lessonspace",
    capabilities: ["video"],
    auth: "credentials",
    levels: ["organisation"],
    credential_fields: ["api_key"],
    simulated: true,
  },
];

const connection = (extra: object) => ({
  id: "c1",
  provider: "google",
  provider_name: "Google Calendar and Meet",
  level: "user",
  status: "active",
  user: { id: "u1", name: "Sam", email: "sam@example.com" },
  account_name: "sam@gmail.com",
  capabilities: ["calendar", "video"],
  scopes: [],
  expires_at: null,
  last_sync_at: null,
  last_checked_at: null,
  error: "",
  error_at: null,
  error_count: 0,
  connected_at: null,
  disconnected_at: null,
  created_at: "2026-10-10T10:00:00Z",
  ...extra,
});

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions: PERMS } },
    "GET /api/v1/organisation": { body: { status: "active" } },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/integrations/providers": { body: PROVIDERS },
    "GET /api/v1/me/meeting-preference": { body: { provider: "", use_personal_room: false } },
    "GET /api/v1/settings/integrations": {
      body: {
        area: "integrations",
        branch: null,
        overrides: [],
        schema: [],
        values: {
          "integrations.video_provider": "builtin",
          "integrations.auto_create_meetings": true,
          "integrations.join_window_minutes": 10,
          "integrations.calendar_two_way": true,
        },
      },
    },
    ...extra,
  };
}

describe("integrations settings", () => {
  it("shows connection health and errors and starts a Google connection", async () => {
    window.history.pushState(null, "", "/settings/integrations");
    const assign = vi.fn();
    vi.stubGlobal("location", {
      ...window.location,
      assign,
      search: "",
      pathname: "/settings/integrations",
    });
    const tutorCalendar = connection({
      id: "c2",
      user: { id: "u9", name: "Nia Adeyemi", email: "nia@example.com" },
      status: "needs_reconnect",
      error: "Access was revoked at the provider.",
    });
    const calls = mockApi(
      routes({
        "GET /api/v1/integrations/connections": (_body, url) => ({
          body: {
            results: url.searchParams.get("mine")
              ? [connection({})]
              : [connection({}), tutorCalendar],
          },
        }),
        "POST /api/v1/integrations/oauth/start": {
          body: { authorize_url: "https://accounts.example/auth?state=x" },
        },
      }),
    );
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Integrations" })).toBeInTheDocument();
    expect(await screen.findByText(/Access was revoked at the provider/)).toBeInTheDocument();
    expect(screen.getByText("Nia Adeyemi")).toBeInTheDocument();
    expect(screen.getByText(/simulated provider/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Connect Google Calendar and Meet" }));
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith("https://accounts.example/auth?state=x"),
    );
    expect(calls.find((c) => c.path.endsWith("/oauth/start"))?.body).toEqual({
      provider: "google",
      level: "user",
      next: "/settings/integrations",
    });
  });

  it("connects Lessonspace for the organisation and disconnects an account", async () => {
    window.history.pushState(null, "", "/settings/integrations");
    const calls = mockApi(
      routes({
        "GET /api/v1/integrations/connections": { body: { results: [connection({})] } },
        "POST /api/v1/integrations/connections": {
          status: 201,
          body: connection({
            id: "c3",
            provider: "lessonspace",
            level: "organisation",
            user: null,
          }),
        },
        "POST /api/v1/integrations/connections/c1/disconnect": {
          body: connection({ status: "disconnected" }),
        },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect Lessonspace" }));
    const form = screen.getByRole("form", { name: "Connect Lessonspace" });
    fireEvent.change(within(form).getByLabelText(/API key/), { target: { value: "ls-key" } });
    fireEvent.click(within(form).getByRole("button", { name: "Connect" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
        provider: "lessonspace",
        level: "organisation",
        api_key: "ls-key",
      }),
    );
    fireEvent.click(screen.getAllByRole("button", { name: "Disconnect" })[0]!);
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/api/v1/integrations/connections/c1/disconnect")).toBe(
        true,
      ),
    );
  });

  it("sets the organisation's default video provider", async () => {
    window.history.pushState(null, "", "/settings/integrations");
    const calls = mockApi(
      routes({
        "GET /api/v1/integrations/connections": { body: { results: [] } },
        "PATCH /api/v1/settings/integrations": (body) => ({
          body: {
            area: "integrations",
            branch: null,
            overrides: [],
            schema: [],
            ...(body as object),
          },
        }),
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Default video provider"), {
      target: { value: "zoom" },
    });
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
        values: { "integrations.video_provider": "zoom" },
      }),
    );
  });
});
