# ADR 0019: Branding, custom domains, widgets and hosted websites in a `sites` app

- **Status:** Accepted
- **Date:** 2026-10-10
- **Epic:** E24

## Context
E24 gives every tenant a branded presence: brand kits applied across portals, emails and PDFs; custom domains with automatic TLS; embeddable widgets; and a hosted website builder. The design had to meet these constraints:
- Tenant resolution reads `tenancy.OrganisationDomain` before a tenant is known, so custom domains must stay in that platform table. CLAUDE.md requires apps to write other apps' models only through their services.
- Email (comms) and PDF (billing, payments, payroll) rendering must show the brand without depending on a later app.
- Tenants pick their own colours, but every surface must stay WCAG 2.2 AA.
- Domain verification and certificate issuance are multi-step, timer-based processes (CLAUDE.md 4a). There are no real DNS or CA credentials in development.
- Widgets run on third-party sites. Public endpoints must be anonymous, tenant-resolved, rate-limited and CORS-limited, and must expose nothing the organisation didn't publish.
- Hosted pages must be crawlable, cacheable by a CDN and safe against injected markup.

## Decision
1. **One `sites` app** owns brand kits, widget configs, testimonials, public tutor profiles, sites, pages and page versions, plus the widget and block registries. Custom-domain *data* stays in tenancy: `tenancy.custom_domains` is the only writer and publishes the `custom_domain.*` events. `sites` owns the domain *process* (workflow, providers, API).
2. **`core.branding` provider hook**, like `core.entitlements`. comms, billing, payments and payroll call `branding.for_email()` or `branding.for_documents()`; `SitesConfig.ready` registers the real provider. Logos are inlined as data URIs, so WeasyPrint makes no network calls.
3. **Contrast is computed, never enforced.** Any colour can be saved. Every surface uses derived AA-safe colours: `on_primary` for text on the brand colour, and `link_colour` (the brand darkened to 4.5:1 on white) for text. The editor shows the ratios and warnings live.
4. **`CustomDomainWorkflow` on Temporal**:
   - Verify with backoff for 72 hours (TXT token or CNAME to our edge).
   - Then the certificate: poll every 30 s for 10 minutes, then back off, giving up after 24 hours.
   - Then daily monitoring, continuing-as-new every 30 days.
   - Signals: `check_now` and `remove`. Failures park the workflow for 30 days.
   - Providers follow the Protocol + fake pattern: DNS over HTTPS or fake DNS; Cloudflare for SaaS, Caddy on-demand TLS (`/internal/tls/ask` allows only verified hosts) or fake certificates.
5. **Custom domains reach the apps.**
   - `Organisation.base_url` prefers the live custom app domain, so every link and email follows it.
   - A middleware makes auth cookies host-only on foreign hosts.
   - SSO/OAuth callbacks stay on the platform host, and the existing handoff signs users in on the custom domain.
   - Website hosts (`<slug>.tutortrack.site` or site-purpose domains) get a per-request URLconf that serves pages at `/` and keeps the API.
6. **Public data is tenant-resolved by host, as in E17.** `/api/v1/public/{branding,manifest,tutors,services,reviews,widgets,assets}` take no authentication and use a scoped throttle.
   - CORS uses `corsheaders`' signal: only the organisation's widget origins, verified custom domains and hosted-site origin.
   - Assets are served only if referenced by the brand kit, a listed profile or a published page version.
7. **Widgets are one Lit bundle** with Shadow DOM, CSS-custom-property theming, analytics events and a kind registry (`sites.widgets`). Booking (E08) and course catalogue (E20) widgets register later.
8. **Hosted pages are server-rendered Django templates** from immutable `SitePageVersion` snapshots. Blocks are validated by a registry (`sites.blocks`) and auto-escaped, and links are restricted to safe schemes.
   - Inline analytics are allowed by a CSP *hash*, not a nonce, so CDN-cached HTML stays valid.
   - Analytics load only after cookie consent.
   - ETags and a revision cache tag support CDN purging.

## Consequences
- Other apps gain a one-line dependency on `core.branding` and a shared PDF include (`billing/_brand.html`). They never import `sites`.
- `OrganisationDomain` grew lifecycle fields. Any future domain feature, such as E13 custom sending domains, can reuse the DNS providers but must write through `tenancy.custom_domains`.
- An extra query per `base_url` access (the custom app domain lookup) is accepted for correctness of links.
- Production needs `CUSTOM_DOMAINS_DNS_RESOLVER=doh` (the default) plus Cloudflare credentials or a Caddy edge configured to ask `/internal/tls/ask`. Strict host checking is opt-in (`CUSTOM_DOMAINS_STRICT_HOSTS`, with `ALLOWED_HOSTS=*`).
- Themes are code presets rather than rows. New themes need a deploy, but every theme automatically stays on-brand and AA-safe.
