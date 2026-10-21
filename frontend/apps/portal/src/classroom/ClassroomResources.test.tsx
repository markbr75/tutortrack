import { fireEvent, render, screen } from "@testing-library/react";

import { App } from "../App";
import { mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const start = new Date(Date.now() - 600_000).toISOString();
const end = new Date(Date.now() + 3000_000).toISOString();
const ROOM = {
  lesson_id: "l1", title: "GCSE Maths", start, end, role: "tutor", provider: "builtin",
  embeddable: true, join_url: "https://bm.daily.co/tt-room", opens_at: start, open: true,
  safeguarding_banner: "Tell a trusted adult if worried.", recording: false,
  consent_needed: [],
  resources: [{ id: "r1", title: "Past paper 1", kind: "link", media_type: "link",
                message: "Question 3 first", shared_at: start }],
}; // prettier-ignore
const TUTOR = {
  "GET /api/v1/me": { body: { membership: { role: "tutor" }, user: { email: "n@x.com" } } },
  "GET /api/v1/tutor/me": {
    body: { id: "t1", name: "Nia", email: "n@x.com", can_cancel: false,
            can_edit_lessons: false, can_see_pay: true },
  }, // prettier-ignore
};

describe("resources in the classroom (gap G5c, FR-21-8)", () => {
  it("opens a shared resource and lets the tutor share another into the room", async () => {
    window.history.pushState(null, "", "/portal/classroom/l1");
    const opened = vi.fn();
    vi.stubGlobal("open", opened);
    const calls = mockApi({
      ...TUTOR,
      "GET /api/v1/lessons/l1/classroom": { body: ROOM },
      "POST /api/v1/lessons/l1/classroom/resources/r1/open": {
        body: { url: "https://example.com/paper", expires_in: null, kind: "link" },
      },
      "GET /api/v1/learning/resources": {
        body: {
          results: [
            { id: "r1", title: "Past paper 1" },
            { id: "r2", title: "Fractions video" },
          ],
          next: null,
          previous: null,
        },
      },
      "POST /api/v1/learning/resources/r2/share": { status: 201, body: [] },
    });
    render(<App />);
    expect(await screen.findByText("Question 3 first")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Past paper 1" }));
    await vi.waitFor(() =>
      expect(opened).toHaveBeenCalledWith("https://example.com/paper", "_blank", "noopener"),
    );
    const picker = screen.getByLabelText("Resource");
    await screen.findByRole("option", { name: "Fractions video" });
    expect(screen.queryByRole("option", { name: "Past paper 1" })).toBeNull(); // already in
    fireEvent.change(picker, { target: { value: "r2" } });
    fireEvent.change(screen.getByLabelText("Message (optional)"), {
      target: { value: "Watch this" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Share into the room" }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/learning/resources/r2/share")?.body).toEqual({
        lessons: ["l1"],
        message: "Watch this",
      }),
    );
  });

  it("families can open resources but not share", async () => {
    window.history.pushState(null, "", "/portal/classroom/l1");
    mockApi({
      "GET /api/v1/portal/me": {
        body: {
          role: "client", organisation: { name: "Bright Minds", primary_colour: "" },
          clients: [{ id: "c1", name: "The Patels" }], students: [{ id: "s1", name: "Arjun" }],
          features: { reports: true }, welcome_text: "", help_url: "", terms_url: "",
        },
      }, // prettier-ignore
      "GET /api/v1/lessons/l1/classroom": { body: { ...ROOM, role: "family" } },
    });
    render(<App />);
    expect(await screen.findByRole("button", { name: "Open Past paper 1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Share into the room" })).toBeNull();
  });
});
