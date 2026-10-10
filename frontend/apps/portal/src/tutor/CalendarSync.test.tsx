import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { JoinButton } from "../JoinButton";
import { mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const CONNECTION = {
  id: "c1",
  provider: "google",
  provider_name: "Google Calendar and Meet",
  level: "user",
  status: "active",
  user: { id: "u1", name: "Nia", email: "nia@example.com" },
  account_name: "nia@gmail.com",
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
};

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": {
      body: { membership: { role: "tutor" }, user: { email: "nia@example.com" } },
    },
    "GET /api/v1/tutor/me": {
      body: {
        id: "t1",
        name: "Nia Adeyemi",
        email: "nia@example.com",
        can_cancel: true,
        can_edit_lessons: false,
        can_see_pay: false,
      },
    },
    "GET /api/v1/me/meeting-preference": { body: { provider: "", use_personal_room: false } },
    ...extra,
  };
}

describe("tutor calendar and video", () => {
  it("finishes a Google connection and saves which calendars sync", async () => {
    window.history.pushState(null, "", "/portal/tutor/calendar?code=fake-google-1&state=s1");
    const calls = mockApi(
      routes({
        "POST /api/v1/integrations/oauth/complete": { status: 201, body: CONNECTION },
        "GET /api/v1/integrations/connections": { body: { results: [CONNECTION] } },
        "GET /api/v1/calendar-sync/connections/c1/settings": {
          body: {
            settings: {
              id: "s1",
              connection: "c1",
              read_calendar_ids: ["primary"],
              write_enabled: true,
              write_calendar_id: "cal2",
              two_way: false,
              title_format: "",
              updated_at: "2026-10-10T10:00:00Z",
            },
            calendars: [
              { id: "primary", name: "Personal", primary: true, writable: true },
              { id: "work", name: "Work", primary: false, writable: true },
              { id: "cal2", name: "TutorTrack", primary: false, writable: true },
            ],
            calendars_error: "",
            two_way_allowed: true,
          },
        },
        "PATCH /api/v1/calendar-sync/connections/c1/settings": (body) => ({
          body: {
            settings: { id: "s1", connection: "c1", ...(body as object) },
            calendars: [],
            calendars_error: "",
            two_way_allowed: true,
          },
        }),
      }),
    );
    render(<App />);
    expect(await screen.findByText("Connected.")).toBeInTheDocument();
    expect(calls.find((c) => c.path.endsWith("/oauth/complete"))?.body).toEqual({
      code: "fake-google-1",
      state: "s1",
    });
    fireEvent.click(await screen.findByLabelText("Work"));
    fireEvent.click(screen.getByLabelText("Two-way sync"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
        read_calendar_ids: ["primary", "work"],
        two_way: true,
        write_calendar_id: "cal2",
      }),
    );
  });

  it("connects iCloud with an app-specific password", async () => {
    window.history.pushState(null, "", "/portal/tutor/calendar");
    const calls = mockApi(
      routes({
        "GET /api/v1/integrations/connections": { body: { results: [] } },
        "POST /api/v1/integrations/connections": {
          status: 201,
          body: { ...CONNECTION, provider: "caldav" },
        },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect iCloud" }));
    fireEvent.change(screen.getByLabelText(/Username or email/), {
      target: { value: "nia@icloud.com" },
    });
    fireEvent.change(screen.getByLabelText(/App-specific password/), {
      target: { value: "abcd-efgh" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        provider: "caldav",
        level: "user",
        username: "nia@icloud.com",
        password: "abcd-efgh",
        api_key: "",
      }),
    );
  });
});

describe("join button", () => {
  const start = new Date(Date.now() + 60 * 60_000).toISOString();
  const end = new Date(Date.now() + 2 * 60 * 60_000).toISOString();

  it("is disabled until the join window opens", () => {
    render(
      <JoinButton
        url="https://rooms.example/r1"
        start={start}
        end={end}
        opensAt={new Date(Date.now() + 50 * 60_000).toISOString()}
      />,
    );
    expect(screen.getByRole("button", { name: /Join opens at/ })).toBeDisabled();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("links to the role-specific room once open", () => {
    render(
      <JoinButton
        url="https://rooms.example/r1?host=1"
        start={start}
        end={end}
        opensAt={new Date(Date.now() - 60_000).toISOString()}
      />,
    );
    expect(screen.getByRole("link", { name: "Join the lesson" })).toHaveAttribute(
      "href",
      "https://rooms.example/r1?host=1",
    );
  });
});
