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
  "sites.view": "all",
  "sites.branding.manage": "all",
  "sites.domain.manage": "all",
  "sites.widget.manage": "all",
  "sites.site.manage": "all",
  "sites.site.publish": "all",
  "sites.profile.moderate": "all",
};

const OPTIONS = {
  fonts: ["Inter", "Lato"],
  social_networks: ["facebook", "instagram"],
  white_label: false,
  custom_domain: true,
  cname_target: "custom.tutortrack.app",
  site_base_domain: "tutortrack.site",
  widgets_script_url: "https://cdn.tutortrack.app/widgets.js",
  site_url: "https://brightminds.tutortrack.site",
};

const KIT = {
  id: "k1",
  branch: null,
  branch_name: "",
  logo: null,
  logo_dark: null,
  favicon: null,
  app_icon: null,
  primary_colour: "#1d4ed8",
  secondary_colour: "#0f172a",
  font: "Inter",
  email_header: "",
  email_footer: "",
  document_footer: "",
  app_name: "",
  social_links: {},
  hide_powered_by: false,
  contrast: {},
  updated_at: "2026-10-10T10:00:00Z",
};

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions: PERMS } },
    "GET /api/v1/organisation": { body: { status: "active" } },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/branding/options": { body: OPTIONS },
    "GET /api/v1/brand-kits": { body: [KIT] },
    "GET /api/v1/branches": { body: { results: [{ id: "b1", name: "Leeds", code: "LDS" }] } },
    ...extra,
  };
}

function open(tab = "") {
  window.history.pushState(null, "", `/website${tab ? `?tab=${tab}` : ""}`);
}

describe("website and branding", () => {
  it("checks colour contrast live and saves the brand kit", async () => {
    open();
    const calls = mockApi(routes({ "POST /api/v1/brand-kits": { status: 201, body: KIT } }));
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Website & branding" })).toBeInTheDocument();
    const colour = await screen.findByLabelText("Main colour");
    expect(screen.getByText("Meets WCAG AA contrast.")).toBeInTheDocument();
    fireEvent.change(colour, { target: { value: "#7dd3fc" } });
    expect(await screen.findByText(/too light for text on white/)).toBeInTheDocument();
    // The live preview uses an AA-safe text colour on the button.
    const preview = screen.getByTestId("theme-preview");
    expect(within(preview).getByText("Book a lesson")).toHaveStyle({ color: "#111827" });
    // Hiding "powered by" needs the white-label plan.
    expect(screen.getByLabelText(/Hide "Powered by TutorTrack"/)).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
        primary_colour: "#7dd3fc",
        font: "Inter",
        branch: null,
      }),
    );
  });

  it("adds a custom domain and shows the DNS records", async () => {
    open("domains");
    const domain = {
      id: "d1",
      hostname: "portal.example.com",
      purpose: "app",
      verification_status: "pending",
      ssl_status: "pending",
      verified_at: null,
      cert_expires_at: null,
      last_checked_at: null,
      status_detail: "",
      url: "https://portal.example.com",
      created_at: "2026-10-10T10:00:00Z",
      dns_records: [
        {
          record_type: "CNAME",
          name: "portal.example.com",
          value: "custom.tutortrack.app",
          purpose: "routing",
        },
        {
          record_type: "TXT",
          name: "_tutortrack-challenge.portal.example.com",
          value: "tt-verify=abc",
          purpose: "verification",
        },
      ],
    };
    let added = false;
    const calls = mockApi(
      routes({
        "GET /api/v1/domains": () => ({ body: added ? [domain] : [] }),
        "POST /api/v1/domains": () => {
          added = true;
          return { status: 201, body: domain };
        },
        "POST /api/v1/domains/d1/verify": { body: domain },
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Domain"), {
      target: { value: "portal.example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add domain" }));
    expect(await screen.findByText("tt-verify=abc")).toBeInTheDocument();
    expect(screen.getByText("Waiting for DNS")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check now" }));
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/api/v1/domains/d1/verify")).toBe(true),
    );
    expect(calls.find((c) => c.path === "/api/v1/domains" && c.method === "POST")?.body).toEqual({
      hostname: "portal.example.com",
      purpose: "app",
    });
  });

  it("builds a widget and shows its embed code and shortcode", async () => {
    open("widgets");
    const widget = {
      id: "w1",
      key: "w-abc",
      kind: "reviews",
      name: "Reviews",
      options: { limit: 6 },
      theme: {},
      allowed_origins: ["https://www.example.com"],
      active: true,
      element: "tt-reviews",
      embed_code:
        '<script type="module" src="https://cdn.tutortrack.app/widgets.js" data-org="brightminds"></script>\n<tt-reviews widget="w-abc"></tt-reviews>',
      wordpress_shortcode: '[tutortrack widget="w-abc" type="reviews"]',
      updated_at: "2026-10-10T10:00:00Z",
    };
    let created = false;
    const calls = mockApi(
      routes({
        "GET /api/v1/widgets/kinds": {
          body: [
            {
              key: "tutor_directory",
              title: "Tutor directory",
              element: "tt-tutor-directory",
              description: "",
              available: true,
            },
            {
              key: "reviews",
              title: "Reviews",
              element: "tt-reviews",
              description: "Testimonials",
              available: true,
            },
            {
              key: "job_openings",
              title: "Tutor vacancies",
              element: "tt-job-openings",
              description: "",
              available: false,
            },
          ],
        },
        "GET /api/v1/widgets": () => ({ body: { results: created ? [widget] : [] } }),
        "POST /api/v1/widgets": () => {
          created = true;
          return { status: 201, body: widget };
        },
      }),
    );
    render(<App />);
    const kind = await screen.findByLabelText("Widget");
    expect(within(kind).queryByText("Tutor vacancies")).toBeNull(); // not on this plan
    fireEvent.change(kind, { target: { value: "reviews" } });
    fireEvent.change(screen.getByLabelText("Websites allowed to show it"), {
      target: { value: "https://www.example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create widget" }));
    expect(
      await screen.findByText('[tutortrack widget="w-abc" type="reviews"]'),
    ).toBeInTheDocument();
    expect(screen.getByText(/<tt-reviews widget="w-abc">/)).toBeInTheDocument();
    expect(screen.getByTitle("Preview of Reviews")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
      kind: "reviews",
      allowed_origins: ["https://www.example.com"],
    });
  });

  it("edits, previews and publishes a website page", async () => {
    open("site");
    const page = {
      id: "p1",
      site: "s1",
      path: "",
      title: "Home",
      nav_label: "",
      show_in_nav: true,
      position: 0,
      seo_title: "",
      meta_description: "",
      blocks: [{ id: "h", type: "hero", props: { heading: "Welcome" } }],
      status: "draft",
      version: 0,
      live_version_number: null,
      updated_at: "2026-10-10T10:00:00Z",
    };
    const calls = mockApi(
      routes({
        "GET /api/v1/sites": {
          body: [
            {
              id: "s1",
              name: "Bright Minds",
              theme: "classic",
              seo_title: "",
              meta_description: "",
              og_image: null,
              business_type: "EducationalOrganization",
              analytics_id: "",
              tag_manager_id: "",
              cookie_banner: true,
              published: false,
              published_at: null,
              url: "https://brightminds.tutortrack.site",
              updated_at: "2026-10-10T10:00:00Z",
            },
          ],
        },
        "GET /api/v1/sites/themes": {
          body: [{ key: "classic", title: "Classic", description: "Clean" }],
        },
        "GET /api/v1/sites/pages": { body: { results: [page] } },
        "GET /api/v1/sites/blocks": {
          body: [
            {
              key: "hero",
              title: "Hero",
              fields: [{ name: "heading", kind: "text", is_required: true, max_length: 150 }],
            },
            {
              key: "text",
              title: "Text",
              fields: [{ name: "body", kind: "textarea", is_required: true, max_length: 10000 }],
            },
          ],
        },
        "GET /api/v1/sites/pages/p1/versions": { body: [] },
        "PATCH /api/v1/sites/pages/p1": (body) => ({ body: { ...page, ...(body as object) } }),
        "GET /api/v1/sites/pages/p1/preview": { body: { html: "<h1>Hello there</h1>" } },
        "POST /api/v1/sites/pages/p1/publish": {
          body: { ...page, status: "published", live_version_number: 1 },
        },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Home" }));
    fireEvent.change(await screen.findByLabelText("Heading"), { target: { value: "Hello there" } });
    fireEvent.change(screen.getByLabelText("Block type"), { target: { value: "text" } });
    fireEvent.click(screen.getByRole("button", { name: "Add block" }));
    fireEvent.change(screen.getByLabelText("Text"), { target: { value: "We teach maths." } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByTitle("Preview of Home")).toHaveAttribute("sandbox", "");
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    expect(await screen.findByText("Published.")).toBeInTheDocument();
    const patch = calls.find((c) => c.method === "PATCH")?.body as { blocks: unknown[] };
    expect(patch.blocks).toEqual([
      { id: "h", type: "hero", props: { heading: "Hello there" } },
      expect.objectContaining({ type: "text", props: { body: "We teach maths." } }),
    ]);
    expect(calls.some((c) => c.path === "/api/v1/sites/pages/p1/publish")).toBe(true);
  });

  it("approves and rejects tutors' public profiles", async () => {
    open("profiles");
    const profile = {
      id: "pp1",
      tutor: "t1",
      tutor_name: "Ada Lovelace",
      slug: "ada-l",
      status: "pending",
      listed: false,
      draft: { display_name: "Ada L.", headline: "Maths", bio: "Ten years teaching.", show: [] },
      published: { display_name: "", headline: "", bio: "", show: [] },
      photo: null,
      draft_photo: null,
      submitted_at: "2026-10-10T10:00:00Z",
      approved_at: null,
      approved_by_name: "",
      rejection_reason: "",
      updated_at: "2026-10-10T10:00:00Z",
    };
    const calls = mockApi(
      routes({
        "GET /api/v1/public-profiles": { body: { results: [profile] } },
        "POST /api/v1/public-profiles/pp1/approve": { body: { ...profile, status: "approved" } },
        "POST /api/v1/public-profiles/pp1/reject": { body: { ...profile, status: "rejected" } },
      }),
    );
    render(<App />);
    expect(await screen.findByText("Ten years teaching.")).toBeInTheDocument();
    const reject = screen.getByRole("button", { name: "Reject" });
    expect(reject).toBeDisabled();
    fireEvent.change(screen.getByLabelText("What should they change?"), {
      target: { value: "Add your subjects" },
    });
    fireEvent.click(reject);
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/reject"))?.body).toEqual({
        reason: "Add your subjects",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Approve and publish" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/approve"))).toBe(true));
  });
});
