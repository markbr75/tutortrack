# TutorTrack guides

Three HTML guides for the people who use, run and integrate with TutorTrack. They have no
external dependencies, so they open straight from the repo (or `file://`) and can be served
as static files.

| Guide | Audience |
|---|---|
| [user-guide.html](user-guide.html) | Office staff, tutors, clients, students and affiliates using the admin app, the tutor app and the client portal day to day |
| [admin-guide.html](admin-guide.html) | Organisation owners and admins who set up and configure TutorTrack, plus platform operators who run the service |
| [api-guide.html](api-guide.html) | Developers who integrate through the public REST API, OAuth apps and webhooks |

## Where people read them

The admin app serves the guides at `/guides/` (for example
http://brightminds.localhost:5173/guides/user-guide.html locally) and copies them into its
build (`frontend/apps/admin/guides.plugin.ts`). It also publishes `/guides/routes.json`,
built from the `data-route` attributes, so the in-app Help panel can link to the section
about the page you are on. The Help panel's short articles are separate: Markdown files in
`backend/tutortrack/success/help/` (with "What's new" entries in `help/changelog/`). Keep
both current when a change affects what people see.

## Keeping them up to date

The guides are part of the definition of done (see `CLAUDE.md`, "Ticket workflow"). When a
change adds, removes or changes something a user, admin or integrator can see, update the
guide in the same pull request and bump its "Last updated" date.

`make docs-check` (part of `make check` and CI) fails when:

1. **A navigation item has no guide section.** Every item in the admin sidebar
   (`frontend/apps/admin/src/layout/AppShell.tsx`), the platform console
   (`frontend/apps/admin/src/platform/PlatformShell.tsx`), the client portal
   (`frontend/apps/portal/src/Shell.tsx`), the tutor app (`frontend/apps/portal/src/tutor/TutorShell.tsx`)
   and the affiliate portal (`frontend/apps/portal/src/affiliate/AffiliatePages.tsx`) must be
   documented by an element with `data-route="<app>:<path>"` in one of the guides, where
   `<app>` is `admin` or `portal`. Example: `<section id="calendar" data-route="admin:/calendar">`.
   One element can list several routes separated by spaces.
2. **The API reference is stale.** The endpoint and webhook reference in `api-guide.html`
   between the `BEGIN GENERATED` / `END GENERATED` markers is built from
   `frontend/packages/api-client/openapi.json` and the webhook event catalogue. Run
   `make docs` after `make api-client` to regenerate it. Never edit inside the markers.
3. **The README misses a backend app.** Every app in `backend/tutortrack/` must appear in
   the module table in the root `README.md`.

## Writing conventions

- Link the shared stylesheet: `<link rel="stylesheet" href="guide.css">`. Keep pages
  self-contained otherwise (no CDN scripts, fonts or images that can go stale).
- Page skeleton: `.site-header` (product name, guide title, links to the other guides),
  `.layout` with a `<nav class="toc">` and `<main id="content">`, then `footer.site-footer`.
  Put "Last updated: YYYY-MM-DD" in `main > header .meta`.
- Use the en-GB labels the app shows (from `frontend/packages/i18n/src/locales/en-GB*`) and
  mark them with `<span class="ui">Label</span>`. Show where to go as
  `<span class="path">Settings › Payments</span>`.
- Describe behaviour, not code. No screenshots: they go stale silently.
- Components: `.callout` (with `.tip` or `.warn`), `ol.steps`, `.cards` / `.card`,
  `.table-wrap > table`, `.badge`, `details.ref`.
- Mention the permission or plan a feature needs when it is not available to everyone.
- Accessibility (WCAG 2.2 AA): one `h1`, no skipped heading levels, descriptive link text,
  tables with `<th scope>`.
