# ADR 0040: Portal navigation and shell (tab bar, More sheet, rail)

- **Status:** Accepted
- **Date:** 2026-10-20
- **Scope:** frontend (`apps/portal`): the family, student, tutor and affiliate shells, their home
  screens and sign-in. Carries ADR 0039's visual system ("The Register") into the portal.

## Context

The portal is used mostly on phones and often briefly (product principle 4). Each role's
menu was one flat, wrapping row of links (17 for tutors, 14 for families) above the content,
with sign-out mixed in, and the tutor's Today and the affiliate's Overview opened on number
tiles. The portal is white-labelled: families see the tutoring business's brand, which can
be any colour.

## Decision

1. **Phones get a bottom tab bar; wider screens a rail.** One shared `PortalFrame` renders
   either the tab bar (below 768px) or a 240px rail, never both, so the page has one
   navigation landmark. Chosen by the owner over a menu drawer and a "home as the menu".
2. **Four everyday tabs per role, then More.** Each shell lists its items (still in
   `Shell.tsx`, `TutorShell.tsx` and `AffiliatePages.tsx`, so `manage.py guides --check` reads
   them) with a priority order; the first four that are switched on become tabs. Everything
   else opens in a More bottom sheet, grouped by job. A role with five items or fewer gets no
   More. Feature gating is unchanged.
3. **Sign out moves to an account menu** (the person's initials, top right).
4. **Quiet white-labelling** (owner's choice): the business's logo or name in ink; its colour
   only on primary buttons and as a soft tint behind the current tab or rail row, never as
   text, so contrast holds with any brand colour and in dark mode.
5. **Home screens become registers.** Family and student Home lead with the next lesson
   (date and time large) and the week as register rows; the tutor's Today is a register with
   marks, "Marked x of y" and the NOW rule, plus a "Waiting for you" list; the affiliate's
   figures are one ruled line. No number tiles.

## Consequences

- The user guide's tutor, family and affiliate introductions describe the tabs, More and
  the account menu.
- `frontend/DESIGN.md` records the portal frame and its components.
- The screens inside the portal (Lessons, Payments, Messages and so on) keep their layouts
  until a later stage; they already use the shared tokens, fields and buttons.
- Possible follow-ups noted in review: unread and to-do counts on tabs, an overdue note on
  the owed line.
