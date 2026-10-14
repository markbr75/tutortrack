# E24 — Public Website, Widgets & White-labelling

| | |
|---|---|
| **Phase** | Agency (Phase 2) |
| **Depends on** | E05, E06, E08 (booking), E17 (forms), E20 (catalogue) |
| **Parity** | TutorBird website builder (drag-and-drop, templates, subdomain/custom domain, login widget for Wix/Squarespace/WordPress); TutorCruncher white-label, custom domain, Socket tutor directory |

## 1. Summary
Give every tenant a professional online presence and conversion tools: full white-label branding across apps, emails and documents; custom domains with automatic SSL; embeddable widgets (tutor directory, booking, enquiry, class catalogue, login, reviews) for existing sites; and a simple hosted website builder for those without a site.

## 2. Functional requirements

### FR-24-1 Branding
- Brand kit per org (overridable per branch): logo (light/dark), favicon, primary/secondary colours (contrast-checked for AA), font choice (from a curated Google Fonts list), email header/footer, invoice template styling, PWA app name/icon, social links.
- Applied to: admin app (subtle), portals (full), emails (E13), PDFs (E10/E12/E21), public pages, widgets.
- "Powered by TutorTrack" footer removable on plans with `white_label`.

### FR-24-2 Custom domains
- Tenant adds hostnames, e.g. `portal.brightminds.co.uk` (portals/app) and `www.brightminds.co.uk` (website). DNS instructions (CNAME to `custom.tutortrack.app`), verification via TXT/HTTP, automatic TLS certificates (Caddy on-demand TLS or AWS ACM + CloudFront multi-tenant / Cloudflare for SaaS), status monitoring and renewal.
- Auth cookies scoped per domain; SSO redirects and OAuth callbacks support custom domains.
- **AC:** after DNS verification, the portal is reachable at the custom domain with a valid certificate within 10 minutes, and emails link to the custom domain.

### FR-24-3 Embeddable widgets (Web Components)
One script tag (`<script src="https://cdn.tutortrack.app/widgets.js" data-org="slug">`) and elements:
- `<tt-tutor-directory>`: searchable/filterable public tutor profiles (subject, level, location, online), profile pages with bio, qualifications, ratings and an "enquire/book" CTA (Socket parity).
- `<tt-enquiry-form form="slug">` (E17 forms).
- `<tt-booking service="..." tutor="...">` (E08 self-booking incl. payment).
- `<tt-class-catalogue>` (E20).
- `<tt-reviews>` (E25 testimonials).
- `<tt-login>` button/portal link.
- Theming via CSS custom properties; Shadow DOM isolation; accessible; < 60KB gzipped per widget; analytics events (`tt:enquiry_submitted`) for GA4/Meta pixel hooks.
- WordPress plugin wrapper (shortcodes) and Wix/Squarespace instructions.

### FR-24-4 Website builder
- Hosted site with templates (3–5 tutoring-specific themes), pages (Home, About, Tutors, Subjects, Pricing, Classes, Contact, Blog/news), block-based editor (hero, text, image, tutor grid, subject list, pricing table, testimonials, FAQ, form, booking, CTA, map), mobile-responsive, SEO settings (titles, meta, OG, sitemap.xml, robots, schema.org `EducationalOrganization`/`LocalBusiness`), Google Analytics/Tag Manager ID, cookie consent banner (E29), custom domain or `slug.tutortrack.site`.
- Published pages served statically/cached via CDN; draft/preview/publish with versions.
- Tutor public profile pages generated from E05 tutor profiles (opt-in, approved fields only).

### FR-24-5 Public tutor profile moderation
- Tutors edit public bio/photo; changes require staff approval (setting); profanity/contact-detail filter (prevents agency bypass).

## 3. Data model
`BrandKit`, `OrganisationDomain(hostname, purpose: app|site, verification_token, verified_at, cert_status)`, `Site`, `SitePage(blocks JSONB, version, status)`, `SiteTheme`, `WidgetConfig`, `PublicProfile(tutor, fields, status, approved_by)`.

## 4. API
`/api/v1/branding`, `/domains` (+ verify), `/sites`, `/sites/pages` (+ publish), `/public/{org}/tutors`, `/public/{org}/tutors/{slug}`, `/public/{org}/branding`, widget config endpoints (CORS restricted to configured site origins + rate limits).

## 5. Delivery plan
- [x] **E24-T01** Brand kit and runtime theming across portals, emails and PDFs.
- [x] **E24-T02** Custom domains: verification, on-demand TLS, routing, cookie/OAuth handling.
- [x] **E24-T03** Widget runtime (Lit), loader script, theming, CORS/rate limits.
- [x] **E24-T04** Tutor directory widget + public profile API + moderation.
- [x] **E24-T05** Enquiry, booking, catalogue, reviews and login widgets.
- [x] **E24-T06** WordPress plugin wrapper.
- [x] **E24-T07** Website builder: themes, block editor, publish pipeline, SEO, sitemap.
- [x] **E24-T08** Remove-branding entitlement and "powered by" handling.
- [x] **E24-TW1** (added) `CustomDomainWorkflow` on Temporal: DNS verification with backoff, certificate issuance and polling, daily monitoring, removal.

## Implementation notes (as built 2026-10-10)

App `tutortrack.sites` (as `docs/02-architecture.md` names it). ADR 0019 records the main decisions.

**Branding (T01, T08).**
- `BrandKit` holds the organisation's kit (`branch` null) and optional per-branch overrides. Resolution order: platform defaults → `Organisation.logo`/`primary_colour` → organisation kit → branch kit.
- Colours are never rejected for contrast. `sites.brand` computes AA-safe variants: `on_primary` (white or near-black text on the brand colour) and `link_colour` (the brand colour darkened to 4.5:1 on white). Every surface uses them. The API returns a contrast report and the admin editor shows live warnings. Fonts come from a curated list of 13 Google Fonts.
- Other apps read the brand through a new `core.branding` hook, so they don't depend on `sites`:
  - comms email HTML: logo, accent bar, header and footer text, "Powered by".
  - billing invoice and statement PDFs, payments receipts and payroll statements: brand bar, logo inlined as a data URI, footer.
  - portal: full theming through `/public/branding` (tokens, font, favicon, logo, PWA manifest at `/public/manifest`).
  - admin app: subtle theming (button colour only).
- "Powered by TutorTrack" can be hidden only with the `white_label` entitlement. It comes back automatically if the plan loses it. It appears in emails, portals, widgets and the hosted website.
- Invoice "template styling" is the brand colour, logo and a document footer. There are no alternative invoice layouts.

**Custom domains (T02).**
- `OrganisationDomain` stays in tenancy, because tenant resolution reads it. New fields: `purpose` (app|site), `verification_token`, `verification_status`, `cert_expires_at`, `last_checked_at` and `status_detail`. All writes go through `tenancy.custom_domains`, which also publishes the `custom_domain.*` events.
- `CustomDomainWorkflow` (sites) verifies the domain (TXT `_tutortrack-challenge.<host>` or a CNAME to `CUSTOM_DOMAINS_CNAME_TARGET`). It checks with backoff from 1 minute to 6 hours, gives up after 72 hours, and `check_now` wakes it. It then polls the certificate every 30 seconds for 10 minutes (the AC), backs off, and gives up after 24 hours. After that it monitors daily and continues-as-new every 30 days. A failure parks the workflow for 30 days waiting for "check now". Removal releases the certificate.
- Deviation: "HTTP verification" is a CNAME check. Both prove traffic reaches us, and the CNAME check needs no plain-HTTP fetch, which the SSRF guard forbids.
- Providers follow the Protocol + fake pattern:
  - DNS: `DohResolver` (DNS over HTTPS, the production default) or `FakeDnsResolver` (development and tests; `CUSTOM_DOMAINS_FAKE_AUTO_VERIFY` accepts any domain locally).
  - TLS: `CloudflareForSaaS` (custom hostnames API), `CaddyOnDemand` (Caddy asks `GET /internal/tls/ask?domain=`, which allows only verified domains; status comes from a TLS probe of public addresses only) or `FakeCertificates`.
- `Organisation.base_url` returns the custom app domain once it is verified with an active certificate. Emails, invitations, handoffs and links therefore use it (AC).
- `sites.middleware.CustomDomainMiddleware` makes auth cookies host-only on custom domains, because a shared `SESSION_COOKIE_DOMAIN` can't be set from another domain. In strict mode (`CUSTOM_DOMAINS_STRICT_HOSTS`, for `ALLOWED_HOSTS=*`) it refuses unknown hosts.
- SSO and OAuth callbacks stay on the platform host (one registered redirect URI). The existing handoff then signs the user in on `org.base_url`, which is the custom domain. CSRF needs no trusted origins, because requests are same-origin on the custom host.
- The hosted website gets `<slug>.<SITE_BASE_DOMAIN>` (`tutortrack.site`). Site-purpose domains and that subdomain switch to the site URLconf (`SiteHostMiddleware`).
- Custom **email sending** domains (DKIM/SPF/DMARC) remain with E13 (its Phase 2). E24 owns only email branding. The DNS verification providers here can be reused for them.

**Widgets (T03, T05).**
- `frontend/apps/widgets` holds Lit custom elements with Shadow DOM, brand theming through CSS custom properties and en-GB strings that the host page can override. Each widget emits `tt:*` analytics events, forwarded to `gtag`, `dataLayer` and `fbq` (`tt:enquiry_submitted` → GA4 `generate_lead` / Meta `Lead`). The whole bundle is 15 kB gzipped.
- Elements: `tt-tutor-directory`, `tt-enquiry-form` (E17 forms: CAPTCHA via explicit Turnstile, honeypot, rate limit), `tt-services` (E06 services; prices only if the widget allows them), `tt-reviews`, `tt-login`, `tt-job-openings` (E18 vacancies), plus the existing `tt-cookie-consent` and `tt-powered-by`.
- `WidgetConfig` (`widget="w-..."`) stores options validated by a registry (`sites.widgets`), theme overrides limited to `--tt-*` properties, and allowed origins.
- CORS for `/api/v1/public/*` uses the `corsheaders` signal. It allows only origins listed on the organisation's active widgets, its verified custom domains and its hosted-site origin; private endpoints are never opened. Public reads are throttled (`public_widget`, 600/hour per IP).
- Deviation: public endpoints are tenant-resolved by host, like E17's public forms (`/api/v1/public/tutors` on `<slug>.tutortrack.app` or a custom domain), not `/public/{org}/...`. The loader's `data-org`/`data-api` pick the host.
- **Not built yet:** `<tt-booking>` (E08 self-booking, Phase 2) and `<tt-class-catalogue>` (E20) register through `sites.widgets.register()` and `sites.blocks.register()` when those epics land. `<tt-reviews>` shows staff-entered `Testimonial`s until E25 adds collected reviews.

**Directory and moderation (T04).**
- `PublicProfile` keeps a `draft` and the approved `published` text. Tutors edit at `/public-profiles/mine` in the portal (`sites.profile.edit:own` for the Tutor role). Edits wait for staff approval when `sites.profile_approval_required` is on (the default). Staff edits publish at once. Coordinators can moderate.
- `sites.moderation` blocks emails (including "at"/"dot" spellings), phone numbers, links and domains, social handles, messaging apps and profanity. `sites.profile_contact_filter` turns off the contact filter but not the profanity check.
- Public output is the display name (first name and last initial by default), headline, bio, approved subjects only, delivery modes, and optional sections (qualifications, languages, experience, town) that the tutor chooses. It never includes the surname, email, rates or address. Approval sets `TutorProfile.public_profile` through people services.
- Tutor ratings (E25) are not shown yet.

**WordPress (T06).** The plugin is in `frontend/apps/widgets/wordpress/tutortrack-widgets/`. It provides a `[tutortrack type=... widget=...]` shortcode and a settings page. Its `readme.txt` has the Wix, Squarespace and Webflow instructions.

**Website builder (T07).**
- `Site` (one per organisation), `SitePage` (draft `blocks`, `status`) and immutable `SitePageVersion` snapshots (publish, restore). Creating a site adds Home, About, Tutors and Contact pages. Contact includes the first published enquiry form.
- Themes are five code presets (classic, modern, playful, academic, minimal) layered over the brand kit. Deviation: they are presets, not `SiteTheme` rows.
- 11 block types are validated by serializers: hero, text, image, tutor grid, subject list, pricing table (E06 services), testimonials, FAQ, form, call to action and map (OpenStreetMap embed). All block text is auto-escaped. Links accept only https, mailto, tel and site paths. The booking block arrives with E08.
- Pages are server-rendered Django templates:
  - Skip link, landmarks, `aria-current`, focus styles.
  - SEO: title, description, canonical, OG tags, JSON-LD `EducationalOrganization`/`LocalBusiness`, `sitemap.xml` (pages and tutor profiles), `robots.txt` (`Disallow: /` while unpublished).
  - Tutor profile pages at `/tutors/<slug>`.
  - CDN caching: `Cache-Control`, a strong ETag/304 and a `Cache-Tag` carrying a revision that every publish or brand change bumps.
- GA4 and GTM load only after cookie consent (E29 banner). The loader is an inline script allowed by a CSP hash, not a nonce, so cached pages stay valid.
- The editor previews drafts through `GET /sites/pages/{id}/preview`, rendered in a sandboxed iframe.
- The block editor is a form-based ordered list with move up/down. There is no drag and drop.

**Admin and portal UI.** Admin "Website & branding" (`/website`) has tabs:
- Branding: kit editor with uploads, live contrast check and preview.
- Domains: DNS records, status and "check now".
- Widgets: builder with kind-specific settings, embed code, shortcode and a live sandboxed preview.
- Reviews.
- Website: settings, pages and block editor.
- Tutor profiles: the moderation queue.

The portal gets full runtime branding and a public-profile editor on the tutor profile page.

## Gap backlog (as built 2026-10-14)

Batch G6 of `docs/05-gap-backlog.md`; design in ADR 0034.


- **Blog and news (FR-24-4):** `BlogPost` (RLS) with title, address, summary, plain-text body
  (paragraphs, escaped), cover image, author, SEO title/description and draft/published (a
  future `published_at` schedules it). API `/api/v1/sites/posts` (+ `publish`, `unpublish`;
  `sites.site.manage` / `sites.site.publish`); event `blog_post.published`. The site serves
  `/blog` (10 per page), `/blog/<slug>` (`og:type=article`, `BlogPosting` JSON-LD, canonical)
  and `/blog/rss.xml` (RSS 2.0); pages link the feed, published posts join `sitemap.xml` and
  their cover images become public assets. New block `blog_list` ("Latest blog posts"); `blog`
  is a reserved page address. Admin: Website → Blog tab. Deviation: no versions for posts
  (publishing is a status) and no rich-text editor.

**Gap G3** ([ADR 0037](../adr/0037-gap-batch-g3-scheduling-billing-payments-payroll.md)):

- **Booking block (FR-24-4; E24:107):** the website builder's `booking` block (heading, intro, days) embeds the E08 `<tt-booking>` widget when online booking is on; see E08's gap notes.
