---
name: TutorTrack
description: The Register — a bookcloth-bound class register for running a tutoring business; ruled stock, blue-black ink, one red margin rule.
colors:
  brand: "hsl(219 59% 40%)"
  brand-foreground: "hsl(0 0% 100%)"
  link: "hsl(219 59% 40%)"
  background: "hsl(60 23% 97%)"
  surface: "hsl(0 0% 100%)"
  foreground: "hsl(218 31% 15%)"
  muted: "hsl(210 42% 95%)"
  muted-foreground: "hsl(222 18% 41%)"
  border: "hsl(212 48% 84%)"
  rule: "hsl(212 51% 93%)"
  field: "hsl(216 17% 56%)"
  shell: "hsl(162 35% 18%)"
  shell-accent: "hsl(162 32% 24%)"
  shell-foreground: "hsl(142 20% 92%)"
  shell-muted: "hsl(156 17% 71%)"
  shell-rule: "hsl(160 20% 30%)"
  margin: "hsl(4 63% 48%)"
  margin-foreground: "hsl(0 0% 100%)"
  danger: "hsl(4 76% 40%)"
  danger-foreground: "hsl(0 0% 100%)"
  success: "hsl(150 59% 30%)"
  warning: "hsl(34 87% 32%)"
typography:
  headline:
    fontFamily: "Source Sans 3 Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.625rem"
    fontWeight: 600
    lineHeight: 1.25
  figure:
    fontFamily: "Source Sans 3 Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.4
    fontFeature: '"tnum" 1'
  title:
    fontFamily: "Source Sans 3 Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.5
  body:
    fontFamily: "Source Sans 3 Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.4286
  caption:
    fontFamily: "Source Sans 3 Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.3333
  label:
    fontFamily: "Source Sans 3 Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.3333
    letterSpacing: "0.05em"
rounded:
  md: "8px"
  xl: "12px"
  full: "9999px"
spacing:
  rail-x: "12px"
  row-y: "10px"
  panel-head-y: "14px"
  panel-x: "20px"
  section-gap: "24px"
  page-x-phone: "16px"
  page-x-desktop: "32px"
  grid-cell-x: "16px"
  filter-gap: "8px"
components:
  button-primary:
    backgroundColor: "{colors.brand}"
    textColor: "{colors.brand-foreground}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  button-secondary-hover:
    backgroundColor: "{colors.muted}"
  button-ghost-hover:
    backgroundColor: "{colors.muted}"
  button-danger:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.danger-foreground}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  button-sm:
    padding: "0 12px"
    height: "32px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "40px"
  input-sm:
    height: "36px"
  rail:
    backgroundColor: "{colors.shell}"
    textColor: "{colors.shell-foreground}"
    padding: "16px 12px"
    width: "248px"
  nav-item:
    textColor: "{colors.shell-foreground}"
    rounded: "{rounded.md}"
    padding: "4px 10px"
  nav-item-hover:
    backgroundColor: "{colors.shell-accent}"
  nav-item-active:
    backgroundColor: "{colors.shell-accent}"
    textColor: "{colors.shell-foreground}"
  nav-group-heading:
    textColor: "{colors.shell-muted}"
    typography: "{typography.label}"
    padding: "4px 10px"
  count-pill:
    backgroundColor: "{colors.margin}"
    textColor: "{colors.margin-foreground}"
    rounded: "{rounded.full}"
    padding: "0 6px"
  tab:
    textColor: "{colors.muted-foreground}"
    typography: "{typography.body}"
    padding: "8px 12px"
  tab-active:
    textColor: "{colors.foreground}"
  top-bar:
    backgroundColor: "{colors.background}"
    height: "56px"
  page-header:
    textColor: "{colors.foreground}"
    typography: "{typography.headline}"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.xl}"
  panel-header:
    typography: "{typography.title}"
    padding: "14px 20px"
  register-row:
    textColor: "{colors.foreground}"
    typography: "{typography.body}"
    padding: "10px 20px"
  data-grid:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.xl}"
  data-grid-heading:
    textColor: "{colors.muted-foreground}"
    padding: "10px 16px"
  data-grid-row:
    textColor: "{colors.foreground}"
    typography: "{typography.body}"
    padding: "10px 16px"
  data-grid-row-hover:
    backgroundColor: "{colors.muted}"
  alert-info:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: "12px 16px"
  money-figure:
    textColor: "{colors.foreground}"
    typography: "{typography.figure}"
    padding: "16px 20px"
  panel-body:
    padding: "16px 20px"
  panel-footer:
    typography: "{typography.body}"
    padding: "12px 20px"
  totals-due-row:
    textColor: "{colors.foreground}"
    typography: "{typography.title}"
    padding: "12px 20px"
  back-link:
    textColor: "{colors.link}"
    typography: "{typography.body}"
  disclosure-summary:
    textColor: "{colors.link}"
    typography: "{typography.body}"
  unit-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "40px"
    width: "96px"
  portal-header:
    backgroundColor: "{colors.surface}"
    height: "56px"
  tab-bar:
    backgroundColor: "{colors.surface}"
    height: "64px"
  tab-bar-item:
    textColor: "{colors.muted-foreground}"
    typography: "{typography.caption}"
    height: "64px"
  tab-bar-item-active:
    textColor: "{colors.foreground}"
  tab-bar-pill:
    rounded: "{rounded.full}"
    width: "56px"
    height: "28px"
  more-sheet:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.xl}"
  more-sheet-row:
    textColor: "{colors.foreground}"
    typography: "{typography.body}"
    padding: "0 20px"
    height: "48px"
  portal-rail:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    padding: "16px 12px"
    width: "240px"
  portal-nav-item:
    textColor: "{colors.foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "8px 12px"
  portal-nav-item-hover:
    backgroundColor: "{colors.muted}"
  account-menu:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: "4px"
    width: "240px"
  lesson-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.xl}"
    padding: "16px"
  lesson-card-time:
    textColor: "{colors.foreground}"
    typography: "{typography.figure}"
  owed-line:
    textColor: "{colors.foreground}"
    typography: "{typography.title}"
    padding: "12px 0"
  copy-link-value:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "8px 12px"
---

# Design System: TutorTrack

## Overview

**Creative North Star: "The Register"**

TutorTrack's admin app is drawn from the teacher's register and mark book, because marking a lesson is what bills it and pays for it. The navigation is the bookcloth cover: a deep green rail with the organisation's name at the top and modules grouped by job. The work area is the register's stock: a near-white ground ruled in pale blue, written in blue-black ink. One red margin rule is the only loud colour, and it means one thing: now, or something that still needs marking or is overdue. Lesson state is shown with authored register marks (a tick, a ring, a struck ring, a dashed ring), never with generic status badges.

The system is dense and desk-oriented: one family in five sizes, 14px body text, tabular figures wherever numbers are compared, and 1px rules instead of shadows or tinted cards. Depth comes from rules and the shell/stock contrast, not elevation. The tenant's brand colour reaches primary-button fills, the caret, text selection and, in the portal, a soft tint behind the current navigation item only; the ink (including the focus ring), the rules, the shell and the margin red stay constant so contrast holds in both colour schemes and under any tenant colour.

The portal (families, students, tutors and partners) is the same register carried in a pocket, and it is white-labelled: it has no bookcloth cover. Its navigation is a clean leaf (a tab bar under the thumb on phones, a rail on wider screens) with the tenant's logo or name in ink. The tenant colour appears on primary fills and as a soft tint behind the current tab or row, never as text.

Scope of this record: it is evidenced by stages 1 to 4 and stage 7 of the build. Stage 1: the shared tokens and font in `packages/ui/src/styles.css`, the register marks, the admin shell and Home. Stage 2: the shared components in `packages/ui` (page header, button styles for links, fields, alerts, tabs, the data grid, chart labels), global defaults for form-control edges and hand-built tables, and the people list screens (Clients, Students, Tutors). Stage 3: the admin calendar (toolbar, day/week/tutor/room time grids, month and agenda). Stage 4: the portal's shared frame (`apps/portal/src/layout/PortalFrame.tsx`: header, tab bar, More sheet, rail, account menu) for every role, sign-in, the lesson card, and each role's home screen (family Home, tutor Today, affiliate Overview). Stage 7: the admin money screens (every Billing tab, the invoice record, the billing section of a client record but not the record page around it, Payments setup and bank reconciliation, the public pay and payment-details pages, Payroll with its pay runs, pay run record and pay items, Accounting settings, and Billing & plan), with two shared components in `packages/ui`: `FigureStrip` and `RuledPanel`. The other admin modules' screens and the portal's inner screens (Schedule, Billing, Messages, Classes, Privacy and the rest) sit inside their converted shells but have not themselves been carried into this world, beyond what they inherit from the shared components and global defaults. The reporting dashboard below Home is ruled off from Home's work area and no longer repeats Home's figures, but its widgets and heading still predate the world. Treat those surfaces as unconverted, not as examples.

**Key Characteristics:**

- Bookcloth-green navigation rail on a ruled, near-white register stock (dark scheme: night-green rail on a blue-slate stock).
- Blue-black ink for text; register-blue rules (1px) for every divider, table row and panel edge.
- One red margin rule for now, needs-marking, overdue and waiting counts; nothing else is red except errors.
- Source Sans 3 (self-hosted variable font) is the only family, in five fixed sizes, with tabular figures in tables, inputs, times and money.
- Authored SVG register marks for lesson state, the same five marks everywhere.
- Flat: panels are ruled, not raised. The only shadow is on floating menus.
- Money reads as ruled lines and ruled tables: figure strips, totals in the amount column, statuses in words.
- The portal is white-labelled: a clean-leaf header and tab bar (rail on wide screens), the business name in ink, the tenant colour only on primary fills and as a soft tint behind the current item.

## Colors

A cool, restrained palette: green-bound navigation, blue-black ink on ruled stock, one red accent that is rationed by meaning, and a tenant-replaceable fill colour. Every token is an HSL triplet on `:root` with a light and a dark value; components use the semantic tokens only.

### Primary

- **Register Ink Blue** (brand; light #2a54a2, dark #87a9ee): the fill of primary buttons, the caret, form accent colour and text selection (at 22% alpha). In the portal it is also the soft tint behind the current tab's icon (15%) and the current rail row (10%). It is the tenant's runtime colour: `applyBrandTheme` overwrites `brand` and `brand-foreground` with the organisation's colour and its AA-safe text colour (E24 FR-24-1).
- **Brand Foreground** (brand-foreground; light #ffffff, dark #0e1c35): text and icons on a brand fill.
- **Link Ink** (link; light #2a54a2, dark #87a9ee): text links, inline accents ("Open unconfirmed lessons", the hover colour of register row titles) and the global focus outline. Same value as the default brand, but it is never tenant-overridden, so links and focus keep AA on the stock (6.9:1 light, 7.6:1 dark) whatever colour a tenant picks, however pale.

### Secondary

- **Bookcloth Green** (shell; light #1e3e34, dark #0f241d): the admin navigation rail, the mobile navigation drawer, and the signed-in user's avatar disc. Nowhere else; the portal does not use it.
- **Bookcloth Raised** (shell-accent; light #2a5145, dark #1c3b31): the hover and current-page fill of rail items.
- **Bookcloth Lettering** (shell-foreground; light #e7efea, dark #e3ede8): rail text and the focus outline inside the rail; also the organisation monogram tile's fill (with bookcloth-green letter).
- **Bookcloth Muted** (shell-muted; light #a8c2b8, dark #9db8ae): rail icons, group headings and the product name under the organisation name.
- **Bookcloth Seam** (shell-rule; light #3d5c52, dark #264037): the 1px dividers inside the rail, under the organisation name and above Settings. Decorative (1.6:1 light, 1.5:1 dark on the rail), like the register rule on the stock.

### Tertiary

- **Margin Red** (margin; light #c8382d, dark #f07b70): the red margin rule. Used for the NOW rule in today's register and the calendar, today's date in the calendar, the header rule and day counts of Needs marking, the tutor's Waiting header rule and counts (only while something waits), the "overdue" line in the money strip, the "due" and "missed" register marks, the 1px inset rule on the current rail item, and the count pills. On the money screens: an overdue invoice's status, non-zero overdue buckets in the ageing table, the note under a client's Overdue figure ("Overdue since 6 Oct 2026."), a past-due plan status, a payment provider's unfinished setup, and the header rule and count of open collection cases.
- **Margin Red Foreground** (margin-foreground; light #ffffff, dark #0f241d): numerals inside count pills (5.2:1 light, 6.0:1 dark).

### Neutral

- **Register Stock** (background; light #f9f9f6, dark #11181d): the page ground and the top bar (at 95% opacity).
- **Clean Leaf** (surface; light #ffffff, dark #162027): panels, data grids and tables sitting on the stock, form fields, secondary buttons, info alerts, floating menus; in the portal also the header, tab bar, rail and More sheet.
- **Blue-Black Ink** (foreground; light #1a2332, dark #e5ebf1): all body text and the "completed" register tick.
- **Wash** (muted; light #edf2f8, dark #1c2831): hover fill for rows (data-grid rows at 60%), buttons and menu items; loading placeholders and skeleton rows.
- **Faded Ink** (muted-foreground; light #56617b, dark #a2afbe): secondary lines, column headings, figure labels, inactive tabs, chart axis labels, the "cancelled" mark (5.9:1 or better on the stock). On the money screens it also carries closed or empty states (draft, void and written-off invoice statuses, empty ageing buckets), the labels of an invoice's totals above Amount due, and destructive ghost actions.
- **Register Rule** (border; light #c3d5ea, dark #2f3f4c): panel and data-grid edges, the rule under a data grid's header row and under a tab row, the money strip's top and bottom rules, the top bar's lower edge, panel header rules, the edge of secondary buttons and info alerts, the rule that sets the dashboard off below Home's work area, the rule above a money table's totals (and again above Amount due), and the rule under the brand line on the public pay pages. Decorative only (1.5:1); never the sole boundary of a form control.
- **Faint Row Rule** (rule; light #e4edf6, dark #22303a): the rule between table rows (data grids and, by default, every hand-built table) and list rows, between figures in a money strip or figure strip, and above a panel's footer row.
- **Field Edge** (field; light #7c8ba2, dark #65798b): the boundary of every text input, select and textarea in the app (3.5:1 light, 3.7:1 dark against the surface fill), set globally so hand-styled controls comply too, and the pale "upcoming" register mark.

### Status

- **Danger** (light #b42318, dark #f28c82): error text, invalid-field borders, destructive button fills, and failures stated in words (a failed payout, an accounting sync error, a non-zero sync-error count). Not the margin red: an error is not "needs marking".
- **Danger Foreground** (danger-foreground; light #ffffff, dark #11181d): text on a danger fill (6.6:1 light, 7.5:1 dark).
- **Success** (light #1f7a4d, dark #5ac491): positive comparisons in words (revenue up on last month).
- **Warning** (light #995b0b, dark #e0a348): the warning alert's tinted fill (10%) and edge (40%). Status tints (danger, success, warning) are always drawn from their tokens, never raw palette colours.

### Named Rules

**The One Red Rule.** Margin red means now, overdue, or still to mark, plus the count of waiting items and a setup still waiting on the business. It is never decoration, never a brand colour and never an error colour.

**The Tenant Fills, the Register Inks Rule.** A tenant's colour replaces `brand` (primary-button fills, caret, selection, and the portal's soft tint behind the current item) and nothing else. Links and the focus outline use `link`, which tenants never change; text, rules, shell and margin red are fixed. The business name in the portal header is ink, not brand.

**The Soft Tint Rule.** In the portal, where you are is shown by the tenant colour as a soft tint behind the current item: brand at 15% in a pill behind the current tab's icon, brand at 10% behind the current rail row. The label beside it is ink at 600. The tint is never text, an icon colour, an underline or an edge.

**The Field Edge Rule.** A form control's boundary uses `field` (3:1 or better in both schemes); a global rule applies it to every text input, select and textarea, and invalid controls turn `danger`. `border` and `rule` are for dividers, panels and secondary-button edges only.

**The Bookcloth Rule.** Shell green is the admin navigation's cover: rail, drawer, avatar. Work areas never sit on it. Lines on the cover use `shell-rule`, never a white overlay. The white-labelled portal has no cover: its navigation is a clean leaf ruled off with `border`.

## Typography

**Body Font:** Source Sans 3 Variable (self-hosted via `@fontsource-variable/source-sans-3`), with ui-sans-serif, system-ui, sans-serif fallback. It is the only family; there is no separate display or mono face.

**Character:** a plain, humanist sans with unslashed zeros, chosen by the owner over Atkinson Hyperlegible Next because slashed zeros read badly on dates and invoice amounts. Weight, not a second family, carries hierarchy: 400 for reading, 500 for buttons and links, 600 for headings, times and figures.

### Hierarchy

- **Headline** (600, 26px, 1.25): admin page titles (the Home greeting and every page header). Headings balance their line wrapping. The portal is phone-first and titles its converted screens one step down, at 20px/600 (sign-in, Next lesson, Today, the affiliate welcome), and so do the public pay pages. An invoice's title is its number in tabular figures, with its status in words beside it at 16px/500.
- **Figure** (600, 20px, 1.4, tabular figures): money amounts in the money strip and every figure strip (a client's balances, the accounting sync counts); in the portal, the lesson card's time range, the tutor's earnings and the affiliate's figures.
- **Title** (600, 16px, 1.5): panel headings ("Today's register", "Needs marking") and the settings area heading; in money tables, the Amount due row and the total row of payouts. The portal reads at a 16px base, so a portal row's primary line (lesson title, the owed line) sits at this size, at 500 or 600.
- **Body** (400, 14px, 20px line): the app's working size: table cells, list rows, navigation, buttons, page subtitles. Times in the register are body at 600. In the portal it carries secondary lines (the lesson card's date and context) and navigation rows.
- **Caption** (400, 12px, 16px line): the one muted context line under a row's primary line, hints under fields, chart axis labels, table column headings (at 600, sentence case, faded ink, left-aligned; the default for every table head), and the portal tab bar's labels.
- **Label** (600, 12px, 0.05em tracking, uppercase): navigation group headings (admin rail, settings sub-menu, portal rail and More sheet) and the NOW rule's time label. Nowhere else.

### Named Rules

**The Five Sizes Rule.** 12, 14, 16, 20 and 26px carry the whole hierarchy, charts included. A new screen picks from these; it does not add a size.

**The Tabular Figures Rule.** Tables, inputs, `<time>` elements and money amounts use tabular figures so columns of numbers line up.

**The Label Is Navigation Rule.** Uppercase tracked labels name navigation groups and mark the NOW rule. They never sit above a page or panel heading as a kicker.

## Layout

The admin app is a two-column frame: a 248px (15.5rem) navigation rail fixed to the viewport height on the left, and a work column with a sticky 56px top bar. Page content sits in a centred column up to 1536px (96rem) wide, with 32px padding on desktop and 16px horizontal / 24px vertical padding on phones.

- **Rail:** organisation monogram and name at the top above a faint divider; Home; then the job groups in the user guide's order (People, Scheduling, Lessons and learning, Money, Sales and recruitment, Communication, Insight); then, below a divider at the foot, one Settings entry and (for multi-organisation users) the organisation switcher. Only permitted, switched-on modules appear. The nav list scrolls inside the rail and fades out over its last 40px.
- **Collapsing groups:** when more than 16 main-nav items are visible, groups collapse to their headings (disclosure buttons with a chevron). Home is always open; People and Scheduling are open on a first visit; the group holding the current page opens itself; opened groups are remembered per browser. A closed group shows the count of waiting items inside it.
- **Settings area:** Settings opens a section with its own grouped sub-menu (admin guide order: Organisation, Teaching, Messages, Data, Trust). From 1024px the sub-menu is a 208px sticky column (top 80px) beside the page; below that it stacks above.
- **Top bar:** search as a field (⌘K), Ask AI (⌘J), then a flexible gap, then Help, notifications and the account menu. Its lower edge is a register rule; it is the stock at 95% opacity with a light background blur.
- **Phones (below 768px):** the rail is hidden; a menu button in the top bar opens it as a modal drawer (288px, at most 85% of the viewport) over a 40% black backdrop. The drawer closes on navigation and is mounted only while open.
- **Page header:** every converted page opens with the headline title, an optional one-line description in faded ink, and its actions on the right (wrapping under on phones), 24px above the content. Actions are 8px apart and the primary action comes last, except that destructive actions (Void, Write off, Delete draft) follow it as small faded-ink ghosts.
- **Records inside a section** (an invoice, a pay run): a back link to the section ("Billing", "Payroll": body at 500 in link ink) sits 24px above the header in place of the section's tabs, because no tab would be current.
- **Money screens:** the invoice record is one column up to 64rem, or, when it has credit notes, a main column with a 22rem side column from 1024px. Billing & plan sits in one column up to 56rem, Payroll up to 72rem. Below 768px, money tables fold (see the One Caption Fold Rule).
- **Public pay pages:** one centred column up to 32rem with 16px sides (24px from 640px) and 32px top and bottom, 24px between parts; the brand line is ruled off above the title.
- **List screens:** page header (secondary actions as small secondary buttons, then the primary), one compact filter row 16px above the data grid, then the grid. The filter row wraps: the search field grows from a 224px (14rem) minimum, followed by the selects, any checkbox filter and Apply, all 36px high and 8px apart.
- **Home:** a header row (headline and subtitle left; actions right, wrapping under on phones), the money strip, then from 1024px a main column with a 352px (22rem) subordinate column for attention lists. Sections are 24px apart. The customisable dashboard, when permitted, sits below the work area after a register rule (24px above and below it) and leaves out widgets Home already shows (revenue, outstanding, next pay run, today's lessons, unconfirmed lessons) except while it is being customised.
- **Rhythm:** panel content is inset 20px; panel headers are 14px top and bottom; rows are 10px top and bottom. The rail is padded 12px with 4px item padding and 12px between groups.

The portal has its own frame, shared by every role (family and student, tutor, affiliate):

- **Phones (below 768px):** a sticky 56px clean-leaf header ruled off below (logo or business name left; the household switcher and the account initials right), one content column up to 48rem with 16px sides and 24px top and bottom, and a fixed tab bar at the foot: 64px slots plus the safe-area inset, centred up to 32rem. An 80px spacer keeps the last row clear of the bar.
- **Tabs:** up to four everyday destinations (each role names its own in order of use; the first four it is allowed become tabs) plus More for the rest. A role with five or fewer destinations gets them all as tabs and no More (the affiliate has four).
- **Wide screens (768px and up):** the tab bar gives way to a 240px clean-leaf rail on the left, ruled off on its right edge, its 56px head holding the brand; the header keeps only the switcher and account menu, and content sits up to 48rem with 32px sides and top.
- **Home screens:** sections 32px apart in one column; the most urgent fact first (the owed line, then the next lesson; for tutors, today's register, then what is waiting).
- **Sign-in:** one centred column up to 24rem, vertically centred: the brand mark, one clean-leaf panel, then the child sign-in below a register rule.

### Named Rules

**The One Work Area Rule.** Each screen has one leading work area; side columns stay narrower and subordinate (Home: register first, attention lists at 22rem).

**The Say It Once Rule.** A figure appears once per screen. Secondary areas below the work area leave out what the work area already shows.

**The Fixed Columns Rule.** Register tables keep a fixed column order and fixed widths for the time (96px) and mark (80px) columns; values update in place. On phones a secondary column (tutor) folds into the row's context lines rather than reflowing the table.

**The One Landmark Rule.** The portal shows one navigation landmark at a time: the tab bar on phones, the rail from 768px. The two are never both in the page.

**The Amount Column Rule.** A total sits in the column of the figures it adds up: an invoice's totals ladder in the Amount column (trailing columns such as a credit field or Remove keep it there), the payouts total under Amount, the ageing totals under each bucket, Amount due on the pay page under the line amounts. Figure columns are right-aligned with right-aligned headings, tabular, and fixed in width (8rem for an amount; 7rem on the pay page). Totals are summed exactly in decimals, one row per currency.

**The One Caption Fold Rule.** Below 768px a money table keeps its primary column and its amount, plus the status on invoices and payouts; the other columns (client, due date, tutor, student, method, period, and a pay run's status) fold into the primary cell's one caption, joined by " · ", instead of reflowing the table or scrolling it sideways. A table that is all figures (ageing) keeps its columns and scrolls inside its labelled region.

## Elevation & Depth

The system is flat. Depth comes from the bookcloth/stock contrast and from 1px rules: panels are white leaves on the stock with a register-rule edge, not raised cards. The sticky top bar is separated by a rule, not a shadow.

### Shadow Vocabulary

- **Floating menu** (`box-shadow: 0 8px 24px -8px rgb(15 23 42 / 0.25)`): the account menu (admin and portal), the only element that floats above the page.
- **Current-page margin rule** (`box-shadow: inset 1px 0 0 hsl(var(--tt-margin))`): not depth; a 1px red rule drawn inside the current admin rail item's left edge. The portal rail does not use it (see the Soft Tint Rule).

The portal's More sheet is modal: it sits over a 40% black backdrop and is set off by its top register rule, with no shadow. The fixed tab bar is set off by a register rule along its top edge.

### Named Rules

**The Ruled, Not Raised Rule.** Panels, strips and lists are separated by 1px rules. Shadows are reserved for elements that float over the page.

## Shapes

Gently rounded and ruled. Controls, alerts, rail items and menu rows have 8px corners; panels (register, attention lists, data grids, the portal's lesson card) have 12px, and the portal's More sheet has 12px top corners only; count pills, the avatar, the portal's initials disc and its current-tab pill are fully round. Every line is 1px, except the NOW rule, a 2px margin-red line across the full table width (or across today's calendar column), and the active tab's 2px ink underline. Coloured emphasis on an edge is never thicker than 1px: the current rail item carries a 1px inset margin rule and Needs marking a 1px margin-red header rule.

Register marks are authored SVG on a 20px grid with round caps and joins: a tick (2.2px stroke) for completed, a solid ring (2px) for missed, a ring struck from lower left to upper right (1.5px) for cancelled, and a dashed ring (1.75px, 3/2.6 dash) for still-to-mark, red when over and pale field-blue when still to come. Each mark carries an accessible name. Rail icons are 16px outline icons at 1.75px stroke; top-bar icons are 20px; disclosure chevrons (rail groups and `<details>` summaries) are 14px. In the portal, tab-bar and More-sheet icons are 20px and portal rail icons 18px, all in faded ink except the current tab's, which is ink.

## Components

### Buttons

Quiet, rectangular controls; the tenant colour shows here.

- **Shape:** gently curved (8px), 40px high (32px small), 16px side padding (12px small), body size at 500.
- **Primary:** brand fill with brand-foreground text. One primary per header, placed last ("Book a lesson", "Add a family").
- **Hover / Focus:** primary fades to 90% opacity; all buttons take the global 2px link-ink outline at 2px offset on keyboard focus; disabled is 50% opacity with a not-allowed cursor; loading shows an inline spinner and sets `aria-busy`.
- **Secondary:** clean-leaf (surface) fill, register-rule edge, ink text; hover fills with wash. Beside a page's primary, secondary actions are small (Duplicates, Export CSV, Export Excel) so the primary leads.
- **Links that act as buttons:** take the same look from the shared button styles (variant and size), never a hand-written class string.
- **Ghost:** no fill or edge; hover fills with wash. In faded ink it is the quietest action in a row (the lesson card's Cancel lesson, always last). Destructive actions in a record's header (Void, Write off, Delete draft) are small faded-ink ghosts after the primary; choosing one opens a ruled panel in place with a reason field, the danger button and a ghost Cancel in its footer.
- **Danger:** danger fill with danger-foreground text for destructive actions; hover fades to 90% opacity like primary.

### Inputs / Fields

- **Style:** 40px high, 8px corners, 12px side padding, body size, a 1px field-edge boundary on a clean-leaf (surface) fill. Shared text and select fields share this one style. Labels sit above in body at 500; hints below in caption, faded ink.
- **Compact (filter bars):** 36px high. The label can be kept for screen readers only when the control speaks for itself: a search field with a placeholder, or a select whose first option names the filter ("Any status", "Lessons booked: any").
- **Global edge:** every text input, select and textarea, shared or hand-styled, gets the field edge from a global rule; checkboxes, radios, ranges, colour and file inputs are left alone.
- **Focus:** the global 2px link-ink outline at 2px offset; the caret is brand.
- **Error:** the border turns danger (globally for any `aria-invalid` control); the error text replaces the hint (caption, danger) and is announced; the control is described by the message.
- **Search field (top bar):** a field-edged control on the surface that opens the command palette, with its shortcut shown as a small key cap.
- **Unit field:** a short numeric setting (a percentage, a number of days) is a 96px (6rem) field, right-aligned with tabular figures, followed 8px away by its unit in faded ink ("%", "days"); label above and hint below as usual. Credit amounts typed into an invoice's lines use the same right-aligned narrow field (7rem).

### Page Header

The headline title, an optional description line in faded ink, and the actions on the right with the primary last. It replaces bare page titles on converted screens.

### Filter Bar

One compact row inside a search landmark: the search field grows, then the filter and sort selects, any checkbox filter (36px high) and a small secondary Apply button at the same 36px height. No visible labels above the row; each control keeps an accessible name.

### Navigation

- **Rail item:** body size in bookcloth lettering, 16px bookcloth-muted icon, 8px corners, 4px × 10px padding. Hover fills with bookcloth raised. Current page: bookcloth raised fill, 600 weight, a 1px inset margin rule on the left edge, and `aria-current="page"`.
- **Group heading:** label style in bookcloth muted. When groups collapse it becomes a full-width disclosure button (`aria-expanded`) with a 14px chevron that turns 90° in 150ms.
- **Count pill:** margin-red pill with margin-foreground numerals at caption size (12px, 16px line) and 600, tabular, capped at "99+", hidden from assistive tech and paired with a visually hidden sentence ("3 waiting"). Shown on the item, on a closed group's heading, and on the notifications bell.
- **Settings sub-menu:** ink text on the stock; hover wash; current item wash fill at 600.
- **Rail dividers:** 1px bookcloth seam (`shell-rule`) under the organisation name and above Settings.
- **Mobile:** the same rail inside a modal drawer, with a close button in its top-right corner.

### Portal Navigation

One frame for every portal role; the role supplies its destinations, their groups and its order of everyday use.

- **Header:** 56px, clean leaf, register rule below, sticky under the safe-area inset. The brand is the tenant's logo (32px high) or the business name in ink at 600, never in the brand colour. On wide screens the brand moves to the rail's head and the header keeps only the controls.
- **Tab bar (phones):** fixed to the foot, clean leaf with a register rule on top, even columns. Each tab is a 64px slot: a 20px icon inside a 56 × 28px fully round pill, with the label below at caption size, truncated to one line. Other tabs are faded ink. The current tab is ink at 600, its pill filled with the brand at 15%, and `aria-current="page"`. More is the last slot (an ellipsis icon, `aria-haspopup="dialog"`) and takes the same current treatment when the page is one of its destinations.
- **More sheet:** a modal dialog that slides up from the foot (200ms, ease-out), up to 85% of the viewport high, clean leaf with 12px top corners and a register rule on top, over a 40% black backdrop. A fixed header (More at 16px/600, a 40px close button) is ruled off below; the list scrolls under it, contains its overscroll, and fades out over its last 56px above the safe-area inset. Destinations are grouped under label-style headings in faded ink; rows are 48px high with 20px sides, a 20px faded-ink icon, body size, divided by faint row rules, wash on hover, current at 600. It closes on choosing a row, on the close button, on Escape and on a backdrop tap, and is mounted only while open.
- **Rail (wide screens):** 240px, clean leaf, register rule on its right edge, sticky to the viewport height, the brand in a 56px ruled head. Groups have label-style headings in faded ink, 20px apart. Rows are body size in ink with an 18px faded-ink icon, 8px corners, 8px × 12px padding, wash on hover. The current row is filled with the brand at 10% and set at 600 (no margin rule).
- **Account menu:** the person's initials (caption at 600) in a 32px round disc on the stock with a register-rule edge, inside a 40px round button with a wash hover and a visually hidden name. It opens a 240px floating menu (clean leaf, register-rule edge, 8px corners, 4px padding, the floating-menu shadow): the person's name in faded ink, then Sign out with a 16px icon. Escape or a click outside closes it.

### Tabs

One row that never wraps: it scrolls sideways (scrollbar hidden) and fades out over its last 24px. Tabs are body size in faded ink with 8px × 12px padding; hover turns them ink. The selected tab is ink at 600 with a 2px ink underline sitting on the row's register rule. Arrow keys move between tabs.

### Panels

- **Corner Style:** 12px.
- **Background:** clean leaf (surface) on the stock.
- **Shadow Strategy:** none (see Elevation & Depth).
- **Border:** 1px register rule; the header is divided from the body by a register rule (margin red for Needs marking).
- **Internal Padding:** header 14px × 20px with the title left and a count or total right; rows 10px × 20px divided by faint row rules; a ruled footer row holds the one link onward ("Open unconfirmed lessons").
- **States:** loading shows pulsing wash bars; empty shows one faded-ink sentence, plus a link onward where one helps.
- **Shared form (`RuledPanel`):** a section labelled by its heading (h2, or h3 inside a larger section), with an optional one-line description under the title in faded ink and an optional aside on the right (a count, total or status in words). The header rule is the register rule, or margin red while something waits (open collection cases, with their count in margin red at 600 as the aside). The body is inset 16px × 20px, or flush for lists, tables and forms that bring their own rows; list rows are 10px × 20px between faint row rules. `PanelFooter` is the ruled footer row: a faint rule above, 12px × 20px, items 8px apart and wrapping, holding the one link onward or the panel's own actions (Save, a confirm button, Disconnect).
- **Panel states:** loading is two pulsing wash bars with one announced status; empty is one faded-ink sentence inset 24px × 20px.

### Data Grid

The register table for every list screen. A clean-leaf panel with 12px corners and a register-rule edge. The header row has no fill, only a register rule below it; headings are caption at 600 in faded ink, on one line. Cells are body size with 10px × 16px padding; rows are divided by faint row rules, and clickable rows take a 60% wash on hover. Loading shows three pulsing skeleton rows with one announced status; empty shows one centred faded-ink sentence with generous (40px) padding. "Load more" (cursor pagination) is a small ghost button below a faint rule. With a caption the grid is a labelled, focusable region so keyboard users can scroll wide tables on phones. The scroll region is positioned, so visually hidden content inside it (the caption, hidden header text) cannot widen the page. Figure columns have right-aligned headings and right-aligned tabular cells; Amount due is at 600.

Hand-built tables inherit the same defaults: collapsed borders, left-aligned 12px/600 faded-ink headings and faint rules between body rows. A hand-built money table (invoice lines, payouts, ageing) sits in the same kind of positioned, labelled, focusable scroll region, has a visually hidden caption, rules its header off with a register rule, and puts its totals in a `<tfoot>` under a register rule (see the Amount Column Rule).

### Alerts

8px corners, 12px × 16px padding, body size, an optional 500-weight title. Info is a clean-leaf panel with a register-rule edge; warning, danger and success are their status token at 10% fill with a 40% edge. Warning and danger are announced as alerts, info and success as status.

### Loading

Waiting is quiet and late, never a centrepiece.

- **Loading line:** between screens, a 2px ink-blue line slides along the foot of the top bar while a screen's first data is on its way (background refreshes and polling never trigger it). It fades in after 150ms, so quick screens show nothing, and it is decorative (`aria-hidden`); with reduced motion it holds still at half strength.
- **Page loader:** a fixed 16px ring (a faint full circle with one quarter arc) beside "Loading…" in faded ink at body size, announced as a status. It fades in after 300ms. Lists use the data grid's skeleton rows instead.
- **Inline spinner:** the same ring in the surrounding colour, with no delay, inside buttons and rows.

### Today's Register (signature component)

A table of today's lessons in time order: time (600, tabular), the lesson title with one context line beneath (students · place), tutor, and the register mark centred in the last column. Column headings are caption at 600 in faded ink. A 2px margin-red NOW rule with a "NOW · 20:24" label is inserted before the first lesson that has not ended (or after the last row). The header's right side reads "Marked 3 of 7". Rows that are over and unmarked link straight to marking; others link to the calendar.

In the tutor's portal the same register is a ruled list panel rather than a table: header 12px × 16px with "Your lessons" at 16px/600 and "Marked x of y" in faded ink; each row a 56px time column (start at 600, end as a faded caption), the lesson title at 500 with one caption context line (students · place), its actions, and the mark at the row's end. The NOW rule is the same 2px margin-red line with its label-style "NOW · 16:20" label, refreshed each minute and hidden from assistive tech. Actions wrap under the title: Join (primary) when online, then "Open and complete" as a primary button on a due lesson (secondary "Open" otherwise). Below it a "Waiting for you" panel lists reports to write, job offers and new notifications as 48px rows with the count in margin red at 600 and a chevron; its header rule is margin red only while something waits, otherwise a register rule and one sentence. When the tutor may see pay, the earnings line follows: a ruled line (register rule above and below) with "Earned this month" as a faded-ink link left and the amount in the figure style right.

### Money Strip (signature component)

One ruled line of money, not tiles: a register-rule above and below, three figures (revenue this month, outstanding, next pay run) divided by faint vertical rules (horizontal rules when stacked on phones). Each figure is a faded-ink label that links to its report, the amount in the figure style, and one sentence of comparison or status (success colour for an increase, margin red for an overdue amount, faded ink otherwise). No sparklines, deltas-as-badges or icons.

The shared form is `FigureStrip`: the figures are one `<dl>` with a register rule above and below. From 768px the columns follow the count of figures, divided by faint vertical rules, with the first figure flush to the left edge and the others inset 20px. Below 768px the figures stack, divided by faint horizontal rules. Each figure is a body-size faded-ink label, the value at 20px/600 tabular, 16px above and below, and at most one sentence of note at body size. Its tone (margin, success or danger) colours the note; a figure without a note takes the tone on its value instead. Margin red is for overdue or waiting, danger only for errors. A client's billing reads Owed, Overdue, Credit and Not yet invoiced; the Overdue note says "Nothing overdue." in faded ink, or "Overdue since 6 Oct 2026." in margin red at 500 while something is overdue. Inside a panel (the accounting sync counts) the strip drops its outer rules, and a non-zero error count is in danger. Home's money strip predates `FigureStrip` and keeps its own markup with the same look.

The affiliate's Overview uses the same strip for its three counts (clicks, referred, converted): three even columns between register rules, divided by faint vertical rules, each a body-size faded-ink label over its figure; the earned and unpaid totals follow as one sentence.

### Invoice (signature component)

The invoice record reads as one ruled document, not a dashboard.

- **Header:** the "Billing" back link, then the title: the invoice number in tabular figures at 26px/600 with its status in words beside it at 16px/500 ("Overdue" in margin red at 600). A draft is titled "Draft invoice" with no status word. Below it, one faded-ink line: the client's name as an ink link, then "Issued …" and "Due …" in tabular figures, joined by " · ". The actions follow in order: small secondary buttons (Download PDF, Email to client, Credit note, Use client credit), then the one primary (Collect now on an open invoice, Issue on a draft), then the destructive actions as small faded-ink ghosts (Void, Write off, Delete draft).
- **Invoice lines:** a ruled panel ("Invoice lines" with the currency as the aside) holding a table with Date, Description (the tutor as a caption beneath), Student and a fixed 8rem Amount column. A credited line shows "£15.00 credited" as a caption under its amount.
- **Totals ladder:** in the `<tfoot>`, in the Amount column, under a register rule: Subtotal and Tax (only when there is tax), Total, Credit applied and Paid (only when non-zero, written as negatives with a true minus sign), each with a right-aligned faded-ink label at body size and an ink figure. Amount due closes the ladder below its own register rule, label and figure both at 16px/600.
- **Phones:** each line folds to one primary line (the description) and one caption ("tutor · date · student"), with the amount on the right; the ladder's labels move next to the Amount column.
- **Credit notes:** when there are any, a 22rem ruled side panel from 1024px (below the lines on smaller screens): each row has the number at 500 and the amount at 600 tabular, over a caption with the reason and a link to its PDF.

### Statuses

Every money status is a word, never a badge or a pill. An overdue invoice, a past-due plan and a payment provider's unfinished setup ("Setup not finished") are in margin red at 600. A failed payout and an accounting sync error are in danger at 500, with the reason as a caption or as accessible text. Draft, void and written-off invoices, and sync states that need nothing ("In Xero"), are in faded ink. Everything else ("Issued", "Paid", "Active") is ink.

### Ageing Table

Clients down the side, buckets across (Not yet due, 1–30 days, 31–60 days, 61–90 days, Over 90 days, Total), each a fixed 8rem right-aligned column. A zero bucket is faded ink; Not yet due is ink; a non-zero overdue bucket is margin red at 500. The row total is at 600. A `<tfoot>` Total row under a register rule sums each column exactly, one row per currency, at 600, with the overdue buckets still in margin red when non-zero.

### Plan and Usage Rows

Billing & plan is a column of ruled panels, not pricing cards or progress bars. The plan panel names the plan in its title with the status in words as the aside. Usage is ruled rows (name left, "9 of 15" or "64 (unlimited)" right, tabular), with the figure at 600 when the limit is reached, then a body-size sentence for billable tutors and the next invoice. Plans are ruled rows of three columns from 640px: the name at 600 over a caption description, the prices and limits in tabular figures, and a small secondary "Choose …" on the right; the current plan shows "Your plan" at 600 in place of the button. The monthly or annual choice is a pair of radios in the panel's header. Credits and add-ons are ruled rows with a 600 name, the balance or price in tabular figures, and small secondary actions.

### Public Pay Pages

The pay page and the payment-details setup page carry the tenant, not TutorTrack. A brand line opens the page: the tenant's logo at 32px high (with its dark-scheme version when there is one), or the business name in ink at 16px/600, ruled off below by a register rule with 16px beneath it and 20px before the title. The title follows at 20px/600, with one faded-ink line of client and due date. The lines are a ruled panel of 10px × 20px rows with a 7rem amount column, closed by Amount due at 16px/600 under a register rule.

### Disclosure

A `<details>` section that hides secondary settings (provider-specific settings, export codes). The summary is body size at 500 in link ink, with no native marker and a 14px chevron before it that turns 90° in 150ms when open. Inside a panel it sits in its own row under a register rule, inset 14px × 20px; standing alone in a form it is ruled above and below by faint row rules.

### Owed Line (portal)

The family's money, said once at the top of Home and only when something is owed: one ruled line (register rule above and below, 12px top and bottom) with "You owe £84.00." at 16px/600 tabular on the left and a primary Pay now on the right. No tile, no icon, no red: owing is not overdue.

### Lesson Card (portal signature component)

The next lesson, and every lesson in the family's lists. A clean-leaf panel with 12px corners, a register-rule edge and 16px padding, 12px between its parts:

- **When:** the weekday and date in faded ink at body size (plus the status when it is not planned), then the time range at 20px/600 tabular, with the register mark (20px) at the top right.
- **What:** the lesson title at 16px/600, one faded-ink line of tutor and place ("Online" for online lessons), the tutor's contact details as a caption when shared, and any note for the family in ink.
- **Actions:** below a faint row rule, in order of use: Join (primary, full width; before the join window opens it is a disabled secondary, "Join opens at 16:50"), Open the classroom, Ask to move, Can't make it, Add to calendar (all secondary), and Cancel lesson last as a faded-ink ghost. On phones they sit in two even columns; from 640px they wrap in one row. When online cancelling has closed, a caption sentence takes Cancel lesson's place.
- **Inline forms:** cancelling, moving and reporting an absence open in place below the actions (the cancellation policy shown first as an alert), with a small confirming button and a ghost "Keep the lesson".

The week on Home is the card's compact form: one ruled list panel whose rows are 12px × 16px, a 64px column with the short weekday and day as a faded caption over the time at 600 tabular, then the title at 500 with one caption line of tutor and place, and the mark at the row's end. Latest reports and news follow as ruled list panels (a report row: title at 500, date as a tabular caption on the right, 60% wash on hover).

### Copy Link (portal)

A link the person shares (referral and partner links). The label at body size and 500, then the link as a one-line read-only value: a field-edged box with 8px corners on the stock, 8px × 12px padding, body size, truncated with the full link as its tooltip. Copy link is a secondary button with a copy icon that turns to a tick once copied; on phones it takes the full width below the value, from 640px it sits beside it at the value's height. A caption status line below announces "Link copied."

### Portal Sign-in

The brand mark centred above one clean-leaf panel (12px corners, register-rule edge, 20px padding): "Sign in" at 20px/600, the email field and a full-width primary "Email me a sign-in link"; after sending, one status sentence replaces the form. The child sign-in follows as a ruled section (a register rule above, 20px gap) with its own 16px/600 heading and a full-width secondary button, then the "Powered by" credit in faded ink.

### Attention Lists

Ruled panels of at most five rows ("Needs marking", "Overdue invoices"). Each row: an optional register mark, a primary line, one caption context line, and a right-aligned fact (days waiting in margin red, or the amount owed at 600 tabular). Whole rows are links with a wash hover.

### Calendar

- **Toolbar:** the page header (title, New lesson) and then two rows. The first is ruled off below: previous and next as 32px ghost icon buttons around a secondary Today button, the range title at 16px/600 (announced politely when it changes), and on the right a segmented view switcher: a clean-leaf strip with an 8px corner and 1px rule, its options in faded ink, the pressed one an ink fill with stock lettering at 500 (`aria-pressed`). On phones the switcher takes the full width and its options share it. The second row holds the small selects (Tutor, Status, Colour by) with visually hidden labels, the agenda's Select lessons button and a "More options" disclosure for the second time zone, printing and saved filters.
- **Time grid:** hour rows ruled in register rule on the stock, caption-size hour labels in faded ink. Day and week columns mark today with its heading in margin red at 600 and `aria-current="date"`; tutor and room columns never do. In today's column (and across every resource column, which are all today) a 2px margin-red NOW rule with an 8px dot at its start shows the current time between 07:00 and 22:00, refreshed each minute and hidden from assistive tech.
- **Lesson block:** 8px corners, 6px × 4px padding, caption-size ink text; the fill is the category colour mixed 16% into the clean leaf and the 1px edge is the category colour at full strength, so ink stays readable on any service, tutor or status colour. A 14px register mark leads the title; cancelled blocks are struck through at 70% opacity. Status colouring uses tokens: planned in ink blue, completed in success, missed in margin red, cancelled in faded ink.
- **Month:** in-month days are clean leaf, other days the stock; lesson chips use the same tint-and-edge as blocks. Today's date number is margin red.
- **Agenda:** one clean-leaf panel per day (12px corners, register-rule edge, faint row rules, 10px × 16px rows) under a 16px/600 date heading, margin red for today. Lessons run in time order, with the register mark at the row's end.

## Do's and Don'ts

### Do:

- **Do** use the semantic tokens (`brand`, `link`, `foreground`, `rule`, `field`, `margin`, …) through Tailwind's colour names; never write raw colours in components.
- **Do** keep text links and focus outlines on `link`, so they stay AA whatever colour the tenant chooses.
- **Do** draw form-control boundaries with `field` (3:1 or better in both schemes); the global rule already covers inputs, selects and textareas, so don't override it with `border`.
- **Do** show lesson state with `RegisterMark` and an accessible label, the same five marks on every screen.
- **Do** separate content with 1px register or row rules; keep panels flat.
- **Do** express comparisons in words beside the figure ("£120 more than last month").
- **Do** give every row one primary line and at most one caption context line.
- **Do** collapse navigation groups when more than 16 items are visible, and show waiting counts on closed groups.
- **Do** use tabular figures for times, tables and money, and pick sizes only from 12, 14, 16, 20 and 26px.
- **Do** open a page with the shared page header, secondary actions small and the primary last, with any destructive actions after it as small faded-ink ghosts.
- **Do** open a record inside a section (an invoice, a pay run) with a back link to the section, not with the section's tabs.
- **Do** put a total in the column of the figures it adds up, in a `<tfoot>` row under a register rule, with figure columns right-aligned and fixed in width.
- **Do** fold a money table's secondary columns into the primary cell's one caption below 768px, joined by " · ".
- **Do** give money statuses in words: margin red at 600 for overdue or waiting, danger for failures, faded ink for draft, void or closed, ink otherwise.
- **Do** build figures with `FigureStrip` and panels with `RuledPanel` and `PanelFooter`.
- **Do** put list filters in one compact row with self-describing first options, above a data grid.
- **Do** style links that act as buttons with the shared button styles.
- **Do** check every new pair in both schemes; the dark scheme has its own values for every token.
- **Do** build portal screens inside `PortalFrame`: up to four everyday tabs plus More on phones, the rail from 768px, one navigation landmark at a time, sign out in the account menu.
- **Do** mark the current portal tab or rail row with the soft brand tint (15% behind the tab's icon, 10% behind the rail row) and the label in ink at 600.
- **Do** order a lesson's actions by use: Join first and full width, Cancel lesson last as a faded-ink ghost.

### Don't:

- **Don't** use margin red for decoration, branding or errors; errors use `danger`.
- **Don't** let the tenant colour reach link text, the focus outline, rules, the shell or the margin red.
- **Don't** build KPI tiles, sparklines, stat cards, pricing cards or usage progress bars; money reads as one ruled strip, and plans and usage read as ruled rows ("9 of 15").
- **Don't** put a coloured side border thicker than 1px on any card, row or nav item.
- **Don't** use unicode glyphs or generic status badges for lesson state, or badges and pills for any other status (invoice, payout, sync, plan); state is a register mark or words.
- **Don't** add drop shadows to panels or cards; only floating menus cast one.
- **Don't** add a second typeface or a display size above 26px.
- **Don't** use uppercase tracked labels as kickers above headings, or a faded line naming the business or section above a page title; a business name above a public page's title is a brand line in ink, ruled off below.
- **Don't** show the flat list of every module; navigation stays grouped by job and permission-gated.
- **Don't** use raw palette colours (amber, white overlays) for status tints or rail lines; use `warning`, `danger`, `success` and `shell-rule`.
- **Don't** repeat a figure the screen already shows in a second widget or tile.
- **Don't** set text, icons or edges in the tenant colour in the portal; the business name is ink and the current item is a tint, not brand-coloured text.
- **Don't** use bookcloth green in the portal, or wrap the portal's destinations into a cloud of links; the rest go under More, grouped by job.
