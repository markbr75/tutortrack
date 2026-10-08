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
- [ ] **E24-T01** Brand kit and runtime theming across portals, emails and PDFs.
- [ ] **E24-T02** Custom domains: verification, on-demand TLS, routing, cookie/OAuth handling.
- [ ] **E24-T03** Widget runtime (Lit), loader script, theming, CORS/rate limits.
- [ ] **E24-T04** Tutor directory widget + public profile API + moderation.
- [ ] **E24-T05** Enquiry, booking, catalogue, reviews and login widgets.
- [ ] **E24-T06** WordPress plugin wrapper.
- [ ] **E24-T07** Website builder: themes, block editor, publish pipeline, SEO, sitemap.
- [ ] **E24-T08** Remove-branding entitlement and "powered by" handling.
