# ADR 0039: Visual design system ("The Register") and grouped admin navigation

- **Status:** Accepted
- **Date:** 2026-10-19
- **Scope:** frontend (`packages/ui` tokens, `apps/admin` shell); later stages carry it to
  Home, the list screens, the calendar and the portal. Builds on E24 FR-24-1 (tenant brand
  colour in the admin app) and the WCAG 2.2 AA requirement in `docs/02-architecture.md`.

## Context

The owner's feedback: "the menus are all over the place, not grouped together, and it does
not look like a professional site". The admin sidebar was one flat list of 51 links (search,
AI, notifications and help mixed in), it overflowed sideways on phones, and the design tokens
were a single brand blue on greys with no type scale and a font that was never loaded. The
product vision positions TutorTrack against incumbents with "dated UX"; the owner ruled out
"cold enterprise software" and "a generic template look".

## Decision

1. **A visual world, not a theme tweak.** Chosen with the owner from three sketched
   directions: *The Register*, from the teacher's register and mark book, because marking a
   lesson is what bills it and pays for it. Bookcloth-green navigation shell, register-stock
   ground, blue-black ink, register-blue rules, one red "margin rule" accent reserved for
   *now* and *needs marking*. Recorded in `frontend/PRODUCT.md`, the surface brief under
   `frontend/apps/admin/.impeccable/surfaces/` and, once the first stage is reviewed,
   `frontend/DESIGN.md`.
2. **Tokens stay semantic and tenant-overridable.** Existing token names keep their meaning
   (`background`, `foreground`, `muted`, `border`, `brand`), so every screen picks up the new
   palette; new ones add `surface`, `rule`, `field` (form borders at 3:1), `shell-*`,
   `margin` and `warning`, all with dark-scheme values. Values stay HSL triplets so
   `applyBrandTheme` still writes the tenant colour into `--tt-brand`.
3. **Typeface: Source Sans 3, self-hosted** (`@fontsource-variable/source-sans-3`). Atkinson
   Hyperlegible Next was tried first; its slashed zero ("2Ø Oct 2Ø26", "£4Ø.ØØ") read badly on
   dates and invoices that parents see, and it has no plain-zero alternate. Self-hosting
   avoids sending visitors' IP addresses to Google Fonts. Five sizes carry the hierarchy.
4. **Navigation grouped by job, in the user guide's order:** People, Scheduling, Lessons and
   learning, Money, Sales and recruitment, Communication, Insight. Configuration moves to one
   **Settings** entry that opens a settings area with its own sub-menu in the admin guide's
   order (Organisation, Teaching and money, Communication, Data and website, Trust and
   safety). The same 51 routes as before; permission gating unchanged; `manage.py guides
   --check` still reads every route from `AppShell.tsx`.
5. **A top bar for tools:** search (⌘K) as a field, Ask AI (⌘J), Help, notifications (bell
   with a count) and an account menu (Account, Sign out). On phones the sidebar opens as a
   drawer from a menu button, mounted only while open.
6. **Icons from lucide-react** (one stroke style, MIT), admin app only for now.

## Consequences

- Every page changes appearance at once through the tokens; components that hard-code
  colours or sizes are found and fixed in the following stages.
- Two labels that appeared twice in the old menu are renamed in the settings sub-menu:
  "Integrations directory" (the marketplace) and "Notifications and templates".
- The user and admin guides describe the new layout (sidebar groups, settings area, top bar,
  account menu).
- The portal keeps its own shell until its stage; it already uses the new tokens and font.
