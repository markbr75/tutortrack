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
---

# Design System: TutorTrack

## Overview

**Creative North Star: "The Register"**

TutorTrack's admin app is drawn from the teacher's register and mark book, because marking a lesson is what bills it and pays for it. The navigation is the bookcloth cover: a deep green rail with the organisation's name at the top and modules grouped by job. The work area is the register's stock: a near-white ground ruled in pale blue, written in blue-black ink. One red margin rule is the only loud colour, and it means one thing: now, or something that still needs marking or is overdue. Lesson state is shown with authored register marks (a tick, a ring, a struck ring, a dashed ring), never with generic status badges.

The system is dense and desk-oriented: one family in five sizes, 14px body text, tabular figures wherever numbers are compared, and 1px rules instead of shadows or tinted cards. Depth comes from rules and the shell/stock contrast, not elevation. The tenant's brand colour reaches primary-button fills, the caret and text selection only; the ink (including the focus ring), the rules, the shell and the margin red stay constant so contrast holds in both colour schemes and under any tenant colour.

Scope of this record: it is evidenced by stages 1 to 3 of the build. Stage 1: the shared tokens and font in `packages/ui/src/styles.css`, the register marks, the admin shell and Home. Stage 2: the shared components in `packages/ui` (page header, button styles for links, fields, alerts, tabs, the data grid, chart labels), global defaults for form-control edges and hand-built tables, and the people list screens (Clients, Students, Tutors). Stage 3: the admin calendar (toolbar, day/week/tutor/room time grids, month and agenda). The other modules' screens and the portal role shells have not yet been carried into this world, beyond what they inherit from the shared components and global defaults. The portal already loads the shared tokens and font but still uses its earlier shell. The reporting dashboard below Home is ruled off from Home's work area and no longer repeats Home's figures, but its widgets and heading still predate the world. Treat those surfaces as unconverted, not as examples.

**Key Characteristics:**

- Bookcloth-green navigation rail on a ruled, near-white register stock (dark scheme: night-green rail on a blue-slate stock).
- Blue-black ink for text; register-blue rules (1px) for every divider, table row and panel edge.
- One red margin rule for now, needs-marking, overdue and waiting counts; nothing else is red except errors.
- Source Sans 3 (self-hosted variable font) is the only family, in five fixed sizes, with tabular figures in tables, inputs, times and money.
- Authored SVG register marks for lesson state, the same five marks everywhere.
- Flat: panels are ruled, not raised. The only shadow is on floating menus.

## Colors

A cool, restrained palette: green-bound navigation, blue-black ink on ruled stock, one red accent that is rationed by meaning, and a tenant-replaceable fill colour. Every token is an HSL triplet on `:root` with a light and a dark value; components use the semantic tokens only.

### Primary

- **Register Ink Blue** (brand; light #2a54a2, dark #87a9ee): the fill of primary buttons, the caret, form accent colour and text selection (at 22% alpha). It is the tenant's runtime colour: `applyBrandTheme` overwrites `brand` and `brand-foreground` with the organisation's colour and its AA-safe text colour (E24 FR-24-1).
- **Brand Foreground** (brand-foreground; light #ffffff, dark #0e1c35): text and icons on a brand fill.
- **Link Ink** (link; light #2a54a2, dark #87a9ee): text links, inline accents ("Open unconfirmed lessons", the hover colour of register row titles) and the global focus outline. Same value as the default brand, but it is never tenant-overridden, so links and focus keep AA on the stock (6.9:1 light, 7.6:1 dark) whatever colour a tenant picks, however pale.

### Secondary

- **Bookcloth Green** (shell; light #1e3e34, dark #0f241d): the navigation rail, the mobile navigation drawer, and the signed-in user's avatar disc. Nowhere else.
- **Bookcloth Raised** (shell-accent; light #2a5145, dark #1c3b31): the hover and current-page fill of rail items.
- **Bookcloth Lettering** (shell-foreground; light #e7efea, dark #e3ede8): rail text and the focus outline inside the rail; also the organisation monogram tile's fill (with bookcloth-green letter).
- **Bookcloth Muted** (shell-muted; light #a8c2b8, dark #9db8ae): rail icons, group headings and the product name under the organisation name.
- **Bookcloth Seam** (shell-rule; light #3d5c52, dark #264037): the 1px dividers inside the rail, under the organisation name and above Settings. Decorative (1.6:1 light, 1.5:1 dark on the rail), like the register rule on the stock.

### Tertiary

- **Margin Red** (margin; light #c8382d, dark #f07b70): the red margin rule. Used for the NOW rule in today's register and the calendar, today's date in the calendar, the header rule and day counts of Needs marking, the "overdue" line in the money strip, the "due" and "missed" register marks, the 1px inset rule on the current rail item, and the count pills.
- **Margin Red Foreground** (margin-foreground; light #ffffff, dark #0f241d): numerals inside count pills (5.2:1 light, 6.0:1 dark).

### Neutral

- **Register Stock** (background; light #f9f9f6, dark #11181d): the page ground and the top bar (at 95% opacity).
- **Clean Leaf** (surface; light #ffffff, dark #162027): panels, data grids and tables sitting on the stock, form fields, secondary buttons, info alerts, floating menus.
- **Blue-Black Ink** (foreground; light #1a2332, dark #e5ebf1): all body text and the "completed" register tick.
- **Wash** (muted; light #edf2f8, dark #1c2831): hover fill for rows (data-grid rows at 60%), buttons and menu items; loading placeholders and skeleton rows.
- **Faded Ink** (muted-foreground; light #56617b, dark #a2afbe): secondary lines, column headings, figure labels, inactive tabs, chart axis labels, the "cancelled" mark (5.9:1 or better on the stock).
- **Register Rule** (border; light #c3d5ea, dark #2f3f4c): panel and data-grid edges, the rule under a data grid's header row and under a tab row, the money strip's top and bottom rules, the top bar's lower edge, panel header rules, the edge of secondary buttons and info alerts, and the rule that sets the dashboard off below Home's work area. Decorative only (1.5:1); never the sole boundary of a form control.
- **Faint Row Rule** (rule; light #e4edf6, dark #22303a): the rule between table rows (data grids and, by default, every hand-built table) and list rows, and between money-strip figures.
- **Field Edge** (field; light #7c8ba2, dark #65798b): the boundary of every text input, select and textarea in the app (3.5:1 light, 3.7:1 dark against the surface fill), set globally so hand-styled controls comply too, and the pale "upcoming" register mark.

### Status

- **Danger** (light #b42318, dark #f28c82): error text, invalid-field borders, destructive button fills. Not the margin red: an error is not "needs marking".
- **Danger Foreground** (danger-foreground; light #ffffff, dark #11181d): text on a danger fill (6.6:1 light, 7.5:1 dark).
- **Success** (light #1f7a4d, dark #5ac491): positive comparisons in words (revenue up on last month).
- **Warning** (light #995b0b, dark #e0a348): the warning alert's tinted fill (10%) and edge (40%). Status tints (danger, success, warning) are always drawn from their tokens, never raw palette colours.

### Named Rules

**The One Red Rule.** Margin red means now, overdue, or still to mark, plus the count of waiting items. It is never decoration, never a brand colour and never an error colour.

**The Tenant Fills, the Register Inks Rule.** A tenant's colour replaces `brand` (primary-button fills, caret, selection) and nothing else. Links and the focus outline use `link`, which tenants never change; text, rules, shell and margin red are fixed.

**The Field Edge Rule.** A form control's boundary uses `field` (3:1 or better in both schemes); a global rule applies it to every text input, select and textarea, and invalid controls turn `danger`. `border` and `rule` are for dividers, panels and secondary-button edges only.

**The Bookcloth Rule.** Shell green is the navigation's cover: rail, drawer, avatar. Work areas never sit on it. Lines on the cover use `shell-rule`, never a white overlay.

## Typography

**Body Font:** Source Sans 3 Variable (self-hosted via `@fontsource-variable/source-sans-3`), with ui-sans-serif, system-ui, sans-serif fallback. It is the only family; there is no separate display or mono face.

**Character:** a plain, humanist sans with unslashed zeros, chosen by the owner over Atkinson Hyperlegible Next because slashed zeros read badly on dates and invoice amounts. Weight, not a second family, carries hierarchy: 400 for reading, 500 for buttons and links, 600 for headings, times and figures.

### Hierarchy

- **Headline** (600, 26px, 1.25): page titles (the Home greeting and every page header). Headings balance their line wrapping.
- **Figure** (600, 20px, 1.4, tabular figures): money amounts in the money strip.
- **Title** (600, 16px, 1.5): panel headings ("Today's register", "Needs marking") and the settings area heading.
- **Body** (400, 14px, 20px line): the app's working size: table cells, list rows, navigation, buttons, page subtitles. Times in the register are body at 600.
- **Caption** (400, 12px, 16px line): the one muted context line under a row's primary line, hints under fields, chart axis labels, table column headings (at 600, sentence case, faded ink, left-aligned; the default for every table head).
- **Label** (600, 12px, 0.05em tracking, uppercase): navigation group headings (rail and settings sub-menu) and the NOW rule's time label. Nowhere else.

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
- **Page header:** every converted page opens with the headline title, an optional one-line description in faded ink, and its actions on the right (wrapping under on phones), 24px above the content. Actions are 8px apart and the primary action comes last.
- **List screens:** page header (secondary actions as small secondary buttons, then the primary), one compact filter row 16px above the data grid, then the grid. The filter row wraps: the search field grows from a 224px (14rem) minimum, followed by the selects, any checkbox filter and Apply, all 36px high and 8px apart.
- **Home:** a header row (headline and subtitle left; actions right, wrapping under on phones), the money strip, then from 1024px a main column with a 352px (22rem) subordinate column for attention lists. Sections are 24px apart. The customisable dashboard, when permitted, sits below the work area after a register rule (24px above and below it) and leaves out widgets Home already shows (revenue, outstanding, next pay run, today's lessons, unconfirmed lessons) except while it is being customised.
- **Rhythm:** panel content is inset 20px; panel headers are 14px top and bottom; rows are 10px top and bottom. The rail is padded 12px with 4px item padding and 12px between groups.

### Named Rules

**The One Work Area Rule.** Each screen has one leading work area; side columns stay narrower and subordinate (Home: register first, attention lists at 22rem).

**The Say It Once Rule.** A figure appears once per screen. Secondary areas below the work area leave out what the work area already shows.

**The Fixed Columns Rule.** Register tables keep a fixed column order and fixed widths for the time (96px) and mark (80px) columns; values update in place. On phones a secondary column (tutor) folds into the row's context lines rather than reflowing the table.

## Elevation & Depth

The system is flat. Depth comes from the bookcloth/stock contrast and from 1px rules: panels are white leaves on the stock with a register-rule edge, not raised cards. The sticky top bar is separated by a rule, not a shadow.

### Shadow Vocabulary

- **Floating menu** (`box-shadow: 0 8px 24px -8px rgb(15 23 42 / 0.25)`): the account menu, the only element that floats above the page.
- **Current-page margin rule** (`box-shadow: inset 1px 0 0 hsl(var(--tt-margin))`): not depth; a 1px red rule drawn inside the current rail item's left edge.

### Named Rules

**The Ruled, Not Raised Rule.** Panels, strips and lists are separated by 1px rules. Shadows are reserved for elements that float over the page.

## Shapes

Gently rounded and ruled. Controls, alerts, rail items and menu rows have 8px corners; panels (register, attention lists, data grids) have 12px; count pills and the avatar are fully round. Every line is 1px, except the NOW rule, a 2px margin-red line across the full table width (or across today's calendar column), and the active tab's 2px ink underline. Coloured emphasis on an edge is never thicker than 1px: the current rail item carries a 1px inset margin rule and Needs marking a 1px margin-red header rule.

Register marks are authored SVG on a 20px grid with round caps and joins: a tick (2.2px stroke) for completed, a solid ring (2px) for missed, a ring struck from lower left to upper right (1.5px) for cancelled, and a dashed ring (1.75px, 3/2.6 dash) for still-to-mark, red when over and pale field-blue when still to come. Each mark carries an accessible name. Rail icons are 16px outline icons at 1.75px stroke; top-bar icons are 20px.

## Components

### Buttons

Quiet, rectangular controls; the tenant colour shows here.

- **Shape:** gently curved (8px), 40px high (32px small), 16px side padding (12px small), body size at 500.
- **Primary:** brand fill with brand-foreground text. One primary per header, placed last ("Book a lesson", "Add a family").
- **Hover / Focus:** primary fades to 90% opacity; all buttons take the global 2px link-ink outline at 2px offset on keyboard focus; disabled is 50% opacity with a not-allowed cursor; loading shows an inline spinner and sets `aria-busy`.
- **Secondary:** clean-leaf (surface) fill, register-rule edge, ink text; hover fills with wash. Beside a page's primary, secondary actions are small (Duplicates, Export CSV, Export Excel) so the primary leads.
- **Links that act as buttons:** take the same look from the shared button styles (variant and size), never a hand-written class string.
- **Ghost:** no fill or edge; hover fills with wash.
- **Danger:** danger fill with danger-foreground text for destructive actions; hover fades to 90% opacity like primary.

### Inputs / Fields

- **Style:** 40px high, 8px corners, 12px side padding, body size, a 1px field-edge boundary on a clean-leaf (surface) fill. Shared text and select fields share this one style. Labels sit above in body at 500; hints below in caption, faded ink.
- **Compact (filter bars):** 36px high. The label can be kept for screen readers only when the control speaks for itself: a search field with a placeholder, or a select whose first option names the filter ("Any status", "Lessons booked: any").
- **Global edge:** every text input, select and textarea, shared or hand-styled, gets the field edge from a global rule; checkboxes, radios, ranges, colour and file inputs are left alone.
- **Focus:** the global 2px link-ink outline at 2px offset; the caret is brand.
- **Error:** the border turns danger (globally for any `aria-invalid` control); the error text replaces the hint (caption, danger) and is announced; the control is described by the message.
- **Search field (top bar):** a field-edged control on the surface that opens the command palette, with its shortcut shown as a small key cap.

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

### Tabs

One row that never wraps: it scrolls sideways (scrollbar hidden) and fades out over its last 24px. Tabs are body size in faded ink with 8px × 12px padding; hover turns them ink. The selected tab is ink at 600 with a 2px ink underline sitting on the row's register rule. Arrow keys move between tabs.

### Panels

- **Corner Style:** 12px.
- **Background:** clean leaf (surface) on the stock.
- **Shadow Strategy:** none (see Elevation & Depth).
- **Border:** 1px register rule; the header is divided from the body by a register rule (margin red for Needs marking).
- **Internal Padding:** header 14px × 20px with the title left and a count or total right; rows 10px × 20px divided by faint row rules; a ruled footer row holds the one link onward ("Open unconfirmed lessons").
- **States:** loading shows pulsing wash bars; empty shows one faded-ink sentence, plus a link onward where one helps.

### Data Grid

The register table for every list screen. A clean-leaf panel with 12px corners and a register-rule edge. The header row has no fill, only a register rule below it; headings are caption at 600 in faded ink, on one line. Cells are body size with 10px × 16px padding; rows are divided by faint row rules, and clickable rows take a 60% wash on hover. Loading shows three pulsing skeleton rows with one announced status; empty shows one centred faded-ink sentence with generous (40px) padding. "Load more" (cursor pagination) is a small ghost button below a faint rule. With a caption the grid is a labelled, focusable region so keyboard users can scroll wide tables on phones.

Hand-built tables inherit the same defaults: collapsed borders, left-aligned 12px/600 faded-ink headings and faint rules between body rows.

### Alerts

8px corners, 12px × 16px padding, body size, an optional 500-weight title. Info is a clean-leaf panel with a register-rule edge; warning, danger and success are their status token at 10% fill with a 40% edge. Warning and danger are announced as alerts, info and success as status.

### Loading

Waiting is quiet and late, never a centrepiece.

- **Loading line:** between screens, a 2px ink-blue line slides along the foot of the top bar while a screen's first data is on its way (background refreshes and polling never trigger it). It fades in after 150ms, so quick screens show nothing, and it is decorative (`aria-hidden`); with reduced motion it holds still at half strength.
- **Page loader:** a fixed 16px ring (a faint full circle with one quarter arc) beside "Loading…" in faded ink at body size, announced as a status. It fades in after 300ms. Lists use the data grid's skeleton rows instead.
- **Inline spinner:** the same ring in the surrounding colour, with no delay, inside buttons and rows.

### Today's Register (signature component)

A table of today's lessons in time order: time (600, tabular), the lesson title with one context line beneath (students · place), tutor, and the register mark centred in the last column. Column headings are caption at 600 in faded ink. A 2px margin-red NOW rule with a "NOW · 20:24" label is inserted before the first lesson that has not ended (or after the last row). The header's right side reads "Marked 3 of 7". Rows that are over and unmarked link straight to marking; others link to the calendar.

### Money Strip (signature component)

One ruled line of money, not tiles: a register-rule above and below, three figures (revenue this month, outstanding, next pay run) divided by faint vertical rules (horizontal rules when stacked on phones). Each figure is a faded-ink label that links to its report, the amount in the figure style, and one sentence of comparison or status (success colour for an increase, margin red for an overdue amount, faded ink otherwise). No sparklines, deltas-as-badges or icons.

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
- **Do** open a page with the shared page header, secondary actions small and the primary last.
- **Do** put list filters in one compact row with self-describing first options, above a data grid.
- **Do** style links that act as buttons with the shared button styles.
- **Do** check every new pair in both schemes; the dark scheme has its own values for every token.

### Don't:

- **Don't** use margin red for decoration, branding or errors; errors use `danger`.
- **Don't** let the tenant colour reach link text, the focus outline, rules, the shell or the margin red.
- **Don't** build KPI tiles, sparklines or stat cards; money reads as one ruled strip.
- **Don't** put a coloured side border thicker than 1px on any card, row or nav item.
- **Don't** use unicode glyphs or generic status badges for lesson state.
- **Don't** add drop shadows to panels or cards; only floating menus cast one.
- **Don't** add a second typeface or a display size above 26px.
- **Don't** use uppercase tracked labels as kickers above headings.
- **Don't** show the flat list of every module; navigation stays grouped by job and permission-gated.
- **Don't** use raw palette colours (amber, white overlays) for status tints or rail lines; use `warning`, `danger`, `success` and `shell-rule`.
- **Don't** repeat a figure the screen already shows in a second widget or tile.
