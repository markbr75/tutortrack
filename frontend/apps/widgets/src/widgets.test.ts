import { afterEach, describe, expect, it, vi } from "vitest";

import "./index";

import { BRAND, mockFetch, settle } from "./test-helpers";

const TUTOR = {
  slug: "ada-l",
  display_name: "Ada L.",
  headline: "Maths and computing",
  photo_url: "",
  subjects: [{ subject: "Maths", level: "GCSE" }],
  online: true,
  in_person: false,
  location: "Leeds",
};

afterEach(() => {
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

function mount<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, string> = {}) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  document.body.append(el);
  return el;
}

const text = (el: Element) => el.shadowRoot?.textContent?.replace(/\s+/g, " ") ?? "";

describe("tt-tutor-directory", () => {
  it("lists, searches and opens a tutor profile with an enquiry link", async () => {
    const calls = mockFetch({
      "GET branding": BRAND,
      "GET tutors": { results: [TUTOR], next: null },
      "GET tutors/ada-l": {
        ...TUTOR,
        bio: "I love algebra.",
        qualifications: [],
        languages: [],
        years_experience: 5,
      },
    });
    const el = mount("tt-tutor-directory", { "enquire-url": "/contact" });
    await settle(el);
    expect(text(el)).toContain("Ada L.");
    expect(text(el)).toContain("Maths (GCSE)");
    expect(text(el)).toContain("Powered by TutorTrack");
    expect(el.style.getPropertyValue("--tt-brand-color")).toBe("#1d4ed8");
    // Labelled search controls.
    const root = el.shadowRoot!;
    expect(root.querySelector("label[for=q]")?.textContent).toBe("Search tutors");
    const input = root.querySelector<HTMLInputElement>("#q")!;
    input.value = "algebra";
    input.dispatchEvent(new Event("input"));
    root.querySelector("form")!.dispatchEvent(new Event("submit"));
    await settle(el);
    expect(calls.some((c) => c.url.startsWith("tutors?q=algebra"))).toBe(true);
    root.querySelector<HTMLButtonElement>("button[aria-label='View profile of Ada L.']")!.click();
    await settle(el);
    expect(text(el)).toContain("I love algebra.");
    expect(text(el)).toContain("5 years of experience");
    expect(root.querySelector<HTMLAnchorElement>("a.button")!.getAttribute("href")).toBe(
      "/contact?tutor=Ada%20L.",
    );
  });

  it("uses the widget's settings and hides powered-by when white-labelled", async () => {
    mockFetch({
      "GET widgets/w-1": {
        key: "w-1",
        kind: "tutor_directory",
        element: "tt-tutor-directory",
        options: { show_filters: false, page_size: 6 },
        theme: { "--tt-radius": "0px" },
        branding: { ...BRAND, show_powered_by: false },
      },
      "GET tutors": { results: [TUTOR], next: null },
    });
    const el = mount("tt-tutor-directory", { widget: "w-1" });
    await settle(el);
    expect(el.shadowRoot!.querySelector("form")).toBeNull();
    expect(text(el)).not.toContain("Powered by");
    expect(el.style.getPropertyValue("--tt-radius")).toBe("0px");
  });

  it("shows an error when the API is unreachable", async () => {
    mockFetch({});
    const el = mount("tt-tutor-directory");
    await settle(el);
    expect(el.shadowRoot!.querySelector("[role=alert]")).not.toBeNull();
  });
});

describe("tt-enquiry-form", () => {
  const FORM = {
    name: "Enquire",
    schema: {
      steps: [
        {
          title: "About you",
          fields: [
            { key: "email", label: "Email", type: "email", required: true },
            { key: "notes", label: "Anything else?", type: "textarea" },
          ],
        },
      ],
    },
    thank_you: "Thanks, we'll call you.",
    redirect_url: "",
    consent_text: "",
    turnstile_site_key: "",
  };

  it("submits answers and emits tt:enquiry_submitted", async () => {
    const calls = mockFetch({
      "GET branding": BRAND,
      "GET forms/enquire": FORM,
      "POST forms/enquire": { ok: true },
    });
    const events: unknown[] = [];
    window.addEventListener("tt:enquiry_submitted", (e) => events.push((e as CustomEvent).detail));
    const el = mount("tt-enquiry-form", { form: "enquire" });
    await settle(el);
    const root = el.shadowRoot!;
    const email = root.querySelector<HTMLInputElement>("#f-email")!;
    expect(root.querySelector("label[for=f-email]")?.textContent).toContain("Email");
    email.value = "sam@example.com";
    email.dispatchEvent(new Event("input"));
    root.querySelector("form")!.dispatchEvent(new Event("submit"));
    await settle(el);
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({
      data: { email: "sam@example.com" },
      website: "",
      captcha_token: "",
    });
    expect(text(el)).toContain("Thanks, we'll call you.");
    expect(events).toEqual([{ form: "enquire" }]);
  });

  it("shows field errors from the server", async () => {
    mockFetch({
      "GET branding": BRAND,
      "GET forms/enquire": FORM,
      "POST forms/enquire": () => [422, { errors: { email: ["Enter a valid email."] } }],
    });
    const el = mount("tt-enquiry-form", { form: "enquire" });
    await settle(el);
    el.shadowRoot!.querySelector("form")!.dispatchEvent(new Event("submit"));
    await settle(el);
    const email = el.shadowRoot!.querySelector("#f-email")!;
    expect(email.getAttribute("aria-invalid")).toBe("true");
    expect(email.getAttribute("aria-describedby")).toBe("f-email-error");
    expect(text(el)).toContain("Enter a valid email.");
  });
});

describe("other widgets", () => {
  it("tt-services shows prices formatted by the server", async () => {
    mockFetch({
      "GET branding": BRAND,
      "GET services": [
        {
          id: "s1",
          name: "GCSE Maths",
          description: "1:1",
          subject: "Maths",
          level: "GCSE",
          duration_minutes: 60,
          price: "£45.00",
          pricing_unit_label: "Per hour",
        },
      ],
    });
    const el = mount("tt-services");
    await settle(el);
    expect(text(el)).toContain("GCSE Maths");
    expect(text(el)).toContain("£45.00 per hour");
  });

  it("tt-reviews announces star ratings", async () => {
    mockFetch({
      "GET branding": BRAND,
      "GET reviews": [
        { id: "r", quote: "Great", author: "Jo", role: "Parent", rating: 5, stars: "★★★★★" },
      ],
    });
    const el = mount("tt-reviews");
    await settle(el);
    expect(text(el)).toContain("5 out of 5 stars");
    expect(el.shadowRoot!.querySelector(".stars")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("tt-login links to the right portal", async () => {
    mockFetch({ "GET branding": BRAND });
    const el = mount("tt-login", { portal: "tutor" });
    await settle(el);
    const link = el.shadowRoot!.querySelector("a")!;
    expect(link.getAttribute("href")).toBe("https://brightminds.tutortrack.app/portal/tutor");
    expect(link.textContent).toBe("Tutor login");
  });

  it("tt-job-openings links to the vacancy pages", async () => {
    mockFetch({
      "GET branding": BRAND,
      "GET job-openings": [
        { slug: "maths-tutor", title: "Maths tutor", location: "Leeds", closes_on: null },
      ],
    });
    const el = mount("tt-job-openings");
    await settle(el);
    expect(el.shadowRoot!.querySelector("a")!.getAttribute("href")).toBe(
      "https://brightminds.tutortrack.app/vacancies/maths-tutor",
    );
  });
});
