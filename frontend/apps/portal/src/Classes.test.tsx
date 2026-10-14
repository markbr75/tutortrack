import { fireEvent, render, screen } from "@testing-library/react";

import { App } from "./App";
import { mockApi } from "./test-utils";

/* E20 in the client portal: classes, waitlist positions, re-enrolment and joining a class. */

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const ME = {
  role: "client",
  organisation: { name: "Bright Minds", primary_colour: "" },
  clients: [{ id: "c1", name: "The Patels" }],
  students: [
    { id: "s1", name: "Arjun Patel" },
    { id: "s2", name: "Maya Patel" },
  ],
  features: {
    cancellations: false,
    absence: false,
    invoices: false,
    reports: false,
    profile: false,
    booking: false,
    reschedule: false,
    classes: true,
  },
  welcome_text: "",
  help_url: "",
  terms_url: "",
};

const CLASS = {
  id: "g1", name: "Saturday 10am",
  course: { id: "co1", name: "Year 6 11+ Prep", description: "Reasoning and maths.", subject: "",
            level: "", image_url: "", prerequisites: "", delivery_mode: "in_person" },
  term: "Autumn", start_date: "2026-10-17", end_date: "2026-12-12", weekdays: [5],
  start_time: "10:00", duration_minutes: 60, location: "Centre", online: false,
  min_age: 9, max_age: 11, year_groups: ["Year 6"], pricing_model: "per_term",
  pricing_label: "Per term", price: "£120.00", price_amount: "120.00", currency: "GBP",
  places_left: 3, capacity: 8, full: false, waitlist: false,
}; // prettier-ignore

const COURSES = {
  enrolments: [
    { id: "e1", group_class: "g2", class_name: "Sunday 2pm", course_name: "Chess club",
      term: "Autumn", student: "s1", student_name: "Arjun Patel", status: "pending_payment",
      start_date: "2026-10-18", end_date: null, weekdays: [6], start_time: "14:00",
      pay_url: "https://brightminds.example/pay/tok", hold_expires_at: "2026-10-14T10:30:00Z" },
  ],
  waitlist: [
    { id: "w1", group_class: "g3", class_name: "Monday 5pm", course_name: "GCSE Maths",
      student_name: "Maya Patel", status: "waiting", position: 2, offer_expires_at: null },
  ],
  rollover_offers: [
    { id: "o1", student_name: "Arjun Patel", course_name: "Chess club", class_name: "Sunday 2pm",
      term: "Spring", status: "pending", deadline: "2026-12-01T12:00:00Z", mode: "confirm" },
  ],
}; // prettier-ignore

describe("portal classes", () => {
  it("shows the household's classes, waitlist and re-enrolment, and enrols a child", async () => {
    window.history.pushState(null, "", "/portal/classes");
    const calls = mockApi({
      "GET /api/v1/portal/me": { body: ME },
      "GET /api/v1/branding": { body: {} },
      "GET /api/v1/portal/courses": { body: COURSES },
      "GET /api/v1/portal/classes": {
        body: { classes: [CLASS], terms: "", payment: "none" },
      },
      "POST /api/v1/portal/rollover-offers/o1": {
        body: { ...COURSES.rollover_offers[0], status: "confirmed" },
      },
      "POST /api/v1/portal/enrol": {
        status: 201,
        body: { ...COURSES.enrolments[0], id: "e9", status: "enrolled", pay_url: "" },
      },
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Classes" })).toBeInTheDocument();
    expect(screen.getByText("Number 2 in the queue")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Pay to confirm" })).toHaveAttribute(
      "href",
      "https://brightminds.example/pay/tok",
    );
    fireEvent.click(screen.getByRole("button", { name: "Keep the place" }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/rollover-offers/o1"))?.body).toEqual({
        confirm: true,
      }),
    );
    expect(screen.getByText("3 places left", { exact: false })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Who is joining"), { target: { value: "s2" } });
    fireEvent.click(screen.getByRole("button", { name: "Enrol Maya Patel" }));
    expect(await screen.findByText("Maya Patel is enrolled.")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/v1/portal/enrol")?.body).toEqual({
      group_class: "g1",
      student: "s2",
      accept_terms: false,
      join_waitlist: false,
    });
  });
});
