import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "./App";
import { mockApi } from "./test-utils";

/* E08-T13/T14 in the client portal: self-booking and asking to move a lesson. */

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const soon = new Date(Date.now() + 3 * 86_400_000).toISOString();
const later = new Date(Date.now() + 3 * 86_400_000 + 3600_000).toISOString();

const ME = {
  role: "client",
  organisation: { name: "Bright Minds", primary_colour: "" },
  clients: [{ id: "c1", name: "The Patels" }],
  students: [{ id: "s1", name: "Arjun Patel" }],
  features: {
    cancellations: false,
    absence: false,
    invoices: false,
    reports: false,
    profile: false,
    booking: true,
    reschedule: true,
  },
  welcome_text: "",
  help_url: "",
  terms_url: "",
};

const HOLD = {
  id: "h1",
  service: "sv1",
  service_name: "Maths 1:1",
  tutor: "t1",
  tutor_name: "Nia A.",
  start: soon,
  end: later,
  timezone: "Europe/London",
  student_name: "Arjun Patel",
  status: "held",
  expires_at: soon,
  quote: {
    currency: "GBP",
    amount: { amount: "30.00", currency: "GBP" },
    undiscounted_amount: { amount: "40.00", currency: "GBP" },
    tax_amount: { amount: "0.00", currency: "GBP" },
    trace: ["service rate £40.00/h", "Trial price £30.00"],
    discounts: [{ name: "Trial", amount: { amount: "-10.00", currency: "GBP" } }],
  },
};

describe("portal booking", () => {
  it("books a free time and pays", async () => {
    window.history.pushState(null, "", "/portal/book");
    const calls = mockApi({
      "GET /api/v1/portal/me": { body: ME },
      "GET /api/v1/portal/reschedule-requests": { body: [] },
      "GET /api/v1/portal/booking/services": {
        body: [
          {
            id: "sv1",
            name: "Maths 1:1",
            description: "",
            duration_minutes: 60,
            delivery_mode: "in_person",
            price: { amount: "40.00", currency: "GBP" },
            tutors: [{ id: "t1", name: "Nia A." }],
          },
        ],
      },
      "GET /api/v1/portal/booking/slots": {
        body: [{ tutor: "t1", tutor_name: "Nia A.", start: soon, end: later }],
      },
      "POST /api/v1/portal/booking/holds": { status: 201, body: HOLD },
      "POST /api/v1/portal/booking/holds/h1/submit": {
        body: {
          booking: { ...HOLD, status: "awaiting_payment" },
          pay_url: "https://bm.tutortrack.app/pay/abc",
        },
      },
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Lesson"), { target: { value: "sv1" } });
    fireEvent.click(await screen.findByRole("button", { name: /Nia A\./ }));
    expect(await screen.findByText("Price: £30.00 (Trial price £30.00)")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
      service: "sv1",
      tutor: "t1",
      start: soon,
      student: "s1",
    });
    fireEvent.click(screen.getByRole("button", { name: "Book" }));
    expect(await screen.findByRole("link", { name: "Pay now" })).toHaveAttribute(
      "href",
      "https://bm.tutortrack.app/pay/abc",
    );
    expect(screen.getByText("Please pay to confirm your booking.")).toBeInTheDocument();
  });

  it("asks to move a lesson from the schedule", async () => {
    window.history.pushState(null, "", "/portal/schedule");
    const calls = mockApi({
      "GET /api/v1/portal/me": { body: ME },
      "GET /api/v1/portal/schedule": {
        body: [
          {
            id: "l1",
            title: "Maths",
            start: soon,
            end: later,
            timezone: "Europe/London",
            status: "planned",
            online: false,
            meeting_url: "",
            location: "",
            notes_for_client: "",
            tutors: [{ name: "Nia Adeyemi", email: "", phone: "" }],
            students: [{ id: "s1", name: "Arjun Patel", outcome: "" }],
          },
        ],
      },
      "POST /api/v1/portal/lessons/l1/reschedule": { status: 201, body: { id: "rr1" } },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Ask to move" }));
    fireEvent.change(screen.getByLabelText("New time"), { target: { value: "2026-11-20T17:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));
    await waitFor(() => {
      const body = calls.find((c) => c.method === "POST")?.body as {
        options: { start: string; end: string }[];
      };
      const option = body.options[0]!;
      expect(new Date(option.end).getTime() - new Date(option.start).getTime()).toBe(3600_000);
    });
    expect(await screen.findByText("Request sent.")).toBeInTheDocument();
  });
});
