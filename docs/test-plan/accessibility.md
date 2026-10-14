# Accessibility (WCAG 2.2 AA)

Every TutorTrack screen must meet WCAG 2.2 AA (CLAUDE.md rule 13). `e2e/accessibility.spec.ts` scans the main screens with axe (`@axe-core/playwright`, WCAG 2.0/2.1/2.2 A and AA rules) on every CI run. Automated scans find only about a third of problems, so run the manual checks below before each release on the screens that changed, and on all P1 screens at least once a quarter.

## How to test

| Check | How | WCAG 2.2 |
|---|---|---|
| Keyboard only | Unplug the mouse. Reach and use every control with Tab, Shift+Tab, Enter, Space, arrow keys and Esc. No keyboard traps; dialogs return focus to the control that opened them. | 2.1.1, 2.1.2, 2.4.3 |
| Visible focus, not obscured | The focus ring is always visible and not hidden behind sticky headers, banners, the cookie banner or the help panel. | 2.4.7, 2.4.11 |
| Screen reader | NVDA + Firefox or Chrome (Windows), VoiceOver + Safari (macOS and iOS), TalkBack (Android) for the portal. Check headings, landmarks (`main`, `nav "Main"`), names of buttons and links, form labels and errors, tables and live updates (toasts, "Saved", sync status). | 1.3.1, 4.1.2, 4.1.3 |
| Automated scan | axe DevTools or Lighthouse on the screen in each state (empty, filled, error, dialog open). | many |
| Contrast | A contrast checker (for example the WebAIM checker or the DevTools picker): text 4.5:1 (large text 3:1); controls, focus rings and chart lines 3:1. Check the brand colours too (the brand kit warns, TP-E24-001). | 1.4.3, 1.4.11 |
| Reduced motion | Turn on "reduce motion" in the operating system. Tours, toasts, drag previews and charts don't animate, or only fade. | 2.3.3 (AAA, product rule) |
| Zoom and reflow | Browser zoom 200% and 400% (or a 320 CSS px wide window): no loss of content or function and no sideways scrolling, except for data tables and the calendar grid, which may scroll in their own box. Text spacing bookmarklet: nothing is cut off. | 1.4.4, 1.4.10, 1.4.12 |
| Mobile | A 360 px wide phone in portrait and landscape. The portal is the priority. | 1.3.4, 1.4.10 |
| Target size | Click and tap targets are at least 24×24 CSS px, or have enough space around them (calendar items, icon buttons, table actions, pagination). | 2.5.8 |
| Dragging alternatives | Everything you can drag has a single-pointer alternative: calendar lesson move (quick view "Reschedule"), lead board ("Move to" select), dashboard widget layout (move buttons), page builder blocks (up/down buttons). | 2.5.7 |
| Consistent help | Help (the help panel, support chat) is in the same place on every admin screen; portal help and terms links are in the same place on every portal screen. | 3.2.6 |
| Redundant entry | Multi-step forms don't ask again for what was already entered (enquiry, enrolment, proposal acceptance, onboarding wizard, import mapping). | 3.3.7 |
| Accessible authentication | Sign-in has no cognitive test: password managers and paste work; passkeys and the emailed link are offered; 2FA codes can be pasted; Turnstile has no puzzle. | 3.3.8 |
| Errors | Errors are announced, shown next to the field in text (not colour only) and say how to fix it. | 3.3.1, 3.3.3 |
| Language and time | `lang` is set (en-GB / en-US); dates, times and money are formatted for the locale; time limits (holds, signed links) can be extended or are long enough. | 3.1.1, 2.2.1 |

Record results in the tables below. Write the WCAG criterion number when something fails.

## Admin app

| ID | Screen | Checks | Priority | Automated? | Result |
|---|---|---|---|---|---|
| TP-A11Y-001 | Sign-in `/login` (including the 2FA step, passkey and magic link) | Labels; error announced; autocomplete attributes; accessible authentication; focus moves to the 2FA field | P1 | e2e: `e2e/accessibility.spec.ts` | |
| TP-A11Y-002 | Signup `/signup` and onboarding wizard `/onboarding` | Step progress announced; errors per field; cookie banner keyboard-operable; no redundant entry | P1 | No | |
| TP-A11Y-003 | Home dashboard `/` | Headings; charts have text alternatives or data tables; widget layout editable without dragging; setup checklist is a list with states | P1 | e2e: `e2e/accessibility.spec.ts` | |
| TP-A11Y-004 | Main navigation, ⌘K search and Ctrl+J command bar | Landmark named "Main"; current page marked; search is a combobox with announced results; dialogs trap and return focus | P1 | e2e: `e2e/accessibility.spec.ts` (nav) | |
| TP-A11Y-005 | Clients list `/clients` and other lists | Table caption and headers; filters labelled; "Load more" announced; empty state text | P1 | e2e: `e2e/accessibility.spec.ts` | |
| TP-A11Y-006 | Add a family `/clients/new` | Fieldsets with legends; "Add another student" moves focus; errors next to fields | P1 | No | |
| TP-A11Y-007 | Client, student and tutor pages `/clients/<id>`, `/students/<id>`, `/tutors/<id>` | Heading order; notes form labelled; status change announced; timeline readable | P1 | No | |
| TP-A11Y-008 | People map `/people/map` | List view gives the same information; map controls keyboard-operable (TP-E05-050) | P2 | No | |
| TP-A11Y-009 | Catalogue `/catalogue` (Services, Price check, Pay tiers, Discounts) | Tabs follow the tab pattern; grid editor keyboard-usable; price check result in a live region | P1 | e2e: `e2e/accessibility.spec.ts` | |
| TP-A11Y-010 | Jobs `/jobs` (list and board), `/jobs/<id>`, "Set up lessons" | Board has a non-drag "Move to"; form named; status change announced | P1 | No | |
| TP-A11Y-011 | Calendar `/calendar` (week, month, agenda, rooms; quick view; New lesson) | Each lesson has a name with title, time and status; reschedule without dragging; view buttons use `aria-pressed`; 24 px targets; reflow at 400% (grid may scroll) | P1 | e2e: `e2e/accessibility.spec.ts` | |
| TP-A11Y-012 | Availability `/availability`, Requests `/requests`, Online booking `/settings/booking` | Time inputs labelled; weekly grid usable by keyboard | P2 | No | |
| TP-A11Y-013 | Lesson reports `/reports`, `/reports/<id>`, Unconfirmed `/unconfirmed`, Lesson policies `/lesson-policies` | Bulk select announced; report fields labelled; approval actions named | P1 | No | |
| TP-A11Y-014 | Billing `/billing` (all tabs), invoice `/invoices/<id>` | Money read correctly (currency, not "pound sign"); tables with headers; dialogs for credit note, void and write-off trap focus | P1 | e2e: `e2e/accessibility.spec.ts` (`/billing`) | |
| TP-A11Y-015 | Payments setup `/settings/payments`; bank reconciliation (Billing → Bank) | Provider status in text; match suggestions keyboard-selectable | P2 | No | |
| TP-A11Y-016 | Payroll `/payroll`, `/payroll/runs/<id>`, expenses | Warnings in text; approve buttons named with the run; masked bank details announced as masked | P1 | No | |
| TP-A11Y-017 | Inbox `/inbox` | Conversation list and thread readable; new messages announced politely; AI buttons named; internal note clearly marked | P1 | e2e: `e2e/accessibility.spec.ts` | |
| TP-A11Y-018 | Broadcasts `/broadcasts`, templates `/settings/notifications`, Messaging `/settings/messaging`, notification bell | Template editor labelled; preview available as text; bell count announced | P2 | No | |
| TP-A11Y-019 | Automations `/automations`, `/automations/<id>` | Rule builder usable by keyboard; run history table | P2 | No | |
| TP-A11Y-020 | Enquiries `/leads` (board), `/leads/<id>`, forms `/leads/forms` | "Move to" select on every card (TP-E17-020); form builder keyboard-usable | P1 | e2e: `e2e/accessibility.spec.ts` (`/leads`) | |
| TP-A11Y-021 | Recruitment `/recruitment`, `/recruitment/<id>`, Compliance `/compliance` | Matrix table has row and column headers; status not colour only | P2 | No | |
| TP-A11Y-022 | Matching `/jobs/<id>/match`, `/matching` | Score breakdown in text; heatmap has a text alternative; shortlist actions named | P2 | No | |
| TP-A11Y-023 | Courses `/courses`, class `/classes/<id>`, register `/class-sessions/<id>/register` | "Mark all present"; each student's attendance labelled | P1 | No | |
| TP-A11Y-024 | Learning `/learning`, `/learning/students/<id>` | Coverage heatmap has a text alternative; grades readable | P2 | No | |
| TP-A11Y-025 | Reviews and referrals `/growth` | Star ratings read as numbers; moderation actions named | P2 | No | |
| TP-A11Y-026 | Reports `/analytics`, `/analytics/<key>`, builder `/analytics/builder` | Charts with data tables; builder usable without dragging; export buttons named | P2 | No | |
| TP-A11Y-027 | Integrations `/settings/integrations`, Accounting `/settings/accounting`, Developer `/developer`, Marketplace `/settings/marketplace` | Connection status in text; secrets shown once with a copy button that announces "Copied" | P2 | No | |
| TP-A11Y-028 | Website and branding `/website` (Branding, Domains, Widgets, Website, Tutor profiles) | Live contrast warning announced; page builder blocks reorder with buttons; DNS records copyable | P2 | No | |
| TP-A11Y-029 | Import and export `/data`, `/data/imports/<id>`, `/data/export` | Column mapping selects labelled; validation errors listed with row numbers | P2 | No | |
| TP-A11Y-030 | Privacy `/privacy`, `/privacy/requests/<id>`, Safeguarding `/safeguarding`, `/safeguarding/<id>` | Deadlines in text; redaction controls keyboard-usable | P1 | No | |
| TP-A11Y-031 | Team `/team`, Roles `/team/roles`, Account `/account`, Settings `/settings`, Audit `/audit` | Permission matrix has headers; 2FA setup gives a text secret as well as the QR code; process timeline readable | P1 | No | |
| TP-A11Y-032 | Billing & plan `/settings/plan`, upgrade dialog, trial and past-due banners | Banners are announced once, not on every navigation; plan cards compare in text | P2 | No | |
| TP-A11Y-033 | Copilot `/copilot`, AI settings `/settings/ai` | Answers announced; citations are links with names | P2 | No | |
| TP-A11Y-034 | Help panel, product tour, NPS prompt, support chat | Panel is a dialog or complementary landmark; tour can be skipped by keyboard and respects reduced motion; NPS scale labelled | P2 | No | |
| TP-A11Y-035 | Error pages: "Page not found", API error with retry | Heading, explanation, a way back; retry button focused or reachable | P3 | No | |

## Portal (families, students, tutors, affiliates)

| ID | Screen | Checks | Priority | Automated? | Result |
|---|---|---|---|---|---|
| TP-A11Y-040 | Parent home `/portal/` | Landmarks; lesson cards readable; join button named and 24 px; works at 360 px | P1 | e2e: `e2e/accessibility.spec.ts` | |
| TP-A11Y-041 | Schedule `/portal/schedule`, cancel dialog, add to calendar | Policy preview read before confirm; dialog traps focus | P1 | No | |
| TP-A11Y-042 | Billing `/portal/billing` and paying | Amounts read correctly; pay buttons name the invoice; provider redirect announced | P1 | No | |
| TP-A11Y-043 | Reports `/portal/reports`, Learning `/portal/learning`, homework `/portal/learning/homework/<id>` | Hand-in form labelled; file upload button named; quiz answers keyboard-usable | P1 | No | |
| TP-A11Y-044 | Profile `/portal/profile`, Privacy `/portal/privacy`, Messages `/portal/messages` | Consents are checkboxes with labels; message thread readable | P1 | No | |
| TP-A11Y-045 | Booking `/portal/book`, Classes `/portal/classes`, Referrals `/portal/referrals` | Slots are buttons with full date and time; hold timer announced and long enough | P2 | No | |
| TP-A11Y-046 | Tutor Today `/portal/tutor` and schedule | Next lesson first; sync and offline status in a live region (TP-E16-045) | P1 | e2e: `e2e/accessibility.spec.ts` | |
| TP-A11Y-047 | Tutor lesson `/portal/tutor/lessons/<id>` and report `/portal/tutor/lessons/<id>/report` | Register and report usable one-handed on a phone; autosave announced; AI draft clearly marked | P1 | No | |
| TP-A11Y-048 | Tutor availability, earnings, expenses (camera receipt), notifications, onboarding and compliance | Weekly grid by keyboard; camera input has a file fallback; push toggle named | P2 | No | |
| TP-A11Y-049 | Affiliate `/portal/affiliate` (clients, statements, payout) | Tables with headers; bank form labelled | P2 | No | |
| TP-A11Y-050 | Portal sign-in (magic link) and install prompt | "Check your email" announced; install guidance readable | P2 | No | |

## Public pages (signed links, forms, hosted site, widgets)

| ID | Screen | Checks | Priority | Automated? | Result |
|---|---|---|---|---|---|
| TP-A11Y-060 | Enquiry form `/f/<slug>` | Labels; required fields marked in text; conditional fields announced; errors next to fields; honeypot hidden from screen readers | P1 | e2e: `e2e/accessibility.spec.ts` | |
| TP-A11Y-061 | Pay pages `/pay/<token>`, `/pay/setup/<token>` | Invoice summary readable; no card fields in our DOM; expired-link message | P1 | No | |
| TP-A11Y-062 | Proposal `/proposals/<token>`, offer `/offers/<token>`, shortlist `/shortlists/<token>` | Tutor cards readable; accept and decline buttons named; no redundant entry | P1 | No | |
| TP-A11Y-063 | Feedback `/feedback/<token>`, review `/review/<token>`, re-enrolment `/re-enrol/<token>` | Rating scales are radio groups with labels; "already answered" state | P2 | No | |
| TP-A11Y-064 | Vacancies `/vacancies`, `/vacancies/<slug>`, interview `/interviews/<token>`, reference `/references/<token>` | Application form labels; file upload; slot picker by keyboard | P2 | No | |
| TP-A11Y-065 | Hosted website http://brightminds.site.localhost:8010/ and cookie banner | Skip link; heading order; brand colours pass contrast; cookie banner first in focus order and keyboard-operable | P1 | No | |
| TP-A11Y-066 | Widgets on :5175 (tutor directory, enquiry form, reviews, booking, class catalogue) | Each widget has a heading or name; works inside a host page's focus order; respects the host's reduced motion (TP-E24-033) | P2 | No | |
| TP-A11Y-067 | Public class catalogue and online enrolment | Eligibility errors before details are entered; place hold time announced | P2 | No | |

## Platform console

| ID | Screen | Checks | Priority | Automated? | Result |
|---|---|---|---|---|---|
| TP-A11Y-070 | `/platform` (organisations), `/platform/tenants/<id>` | Table headers; destructive actions confirm with a named dialog | P2 | No | |
| TP-A11Y-071 | `/platform/health`, `/platform/metrics`, `/platform/operations`, `/platform/flags` | Charts with data tables; figures readable as text | P3 | No | |
| TP-A11Y-072 | `/platform/support`, `/platform/support/<id>` | Thread readable; reply box labelled | P3 | No | |

The Temporal UI (http://localhost:8233) is a third-party operator tool and outside the WCAG scope.
