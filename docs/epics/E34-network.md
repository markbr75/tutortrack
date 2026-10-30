# E34 — The TutorTrack Network

- **Status:** Planned (written 2026-10-30; no ticket started)
- **Depends on:** E05 People, E07 Jobs, E08 Scheduling, E09 Delivery, E12 Payroll (self-billing),
  E13 Communications, E18 Recruitment (checklists, checks, click-to-sign), E19 Matching (offers,
  job board, cover, shared shortlists), E28 Import (imported invoices), E29 Privacy (consent,
  provider registry, erasure, regional stacks), E32 Temporal, E33 Workflows
- **ADR:** [0048](../adr/0048-the-network-shared-pathways-and-consented-data-release.md)

## 1. Summary

TutorTrack becomes a **network**. A tutoring business can share jobs and processes with:

- its own tutors;
- other businesses on TutorTrack, including sole traders, which are already businesses in solo
  mode (ADR 0041, 0045);
- tutors who aren't on TutorTrack at all.

Three ideas carry the epic:

1. **Shared pathways.** A business defines the steps someone must follow, and that person works
   through them wherever they are. Examples: applying for a posted job, joining (onboarding onto)
   a job, finishing a job. The owner calls these shared processes; the product calls them
   **pathways**, because "Processes" already names the E32 run timelines shown on records
   (`/api/v1/processes`).
2. **Information about a family is released only after consent.** Before consent, a tutor or
   partner sees the anonymised brief that E19 offers already use. Names, contact details,
   address, needs and history are released per job, per recipient and per type of information,
   after the family agrees. The release ends when consent is withdrawn or the job ends.
3. **Businesses stay separate.** Data isolation (ADR 0003) is unchanged. The network passes
   minimal, consented copies between businesses, and each business writes its own records
   through its own services. There are never shared rows and never a direct database link from
   one business's table to another's.

The pathway engine and the consent gate are built **inside one business first** (T01–T03). They
are useful straight away to an agency with its own tutors. The network then reuses them (T04 on).

### Owner decisions (2026-10-30)

- **Subcontracting is the model.** The business that shares a job keeps the family and the
  billing; the partner delivers the lessons. A **handoff** (passing the family over for a
  finder's fee) comes last (T11).
- **TutorTrack records money between businesses but doesn't move it.** The sharing business pays
  the partner through its normal pay run and a self-billing statement. The partner's books
  receive that statement as an invoice and the payout as a payment. Moving money with Stripe
  Connect is out of scope.
- **Consent first, always, across businesses.** Data protection law may not require it when a
  partner only processes data for the sharing business. We ask anyway, and a handoff needs it.
  For a business's own tutors, the consent gate is an organisation setting (off by default, so
  existing businesses don't change).
- **Staff may record consent given by phone or on paper.** They record the method and a note,
  and it is audited.
- **The open network (T10) is for verified members only**, and comes after connections have
  proved themselves.
- **Charging:** the network is free on every plan to start, to grow the network. A `network`
  plan feature gates it, so it can be priced later; the pricing decision is part of T10.

## 2. Functional requirements

### FR-34-1 Shared pathways

- A **pathway template** is an ordered list of **stages**, and each stage holds **steps**. Each
  step has:
  - a **type** (from a registry);
  - **who does it**: the participant, the business's staff, the family, or the system;
  - what **finishes** it;
  - an optional **deadline** with reminders;
  - optional **"needed before"** gates, for example "before the first lesson" or "before
    information is released".
- **Step types (registry).** Each type declares its settings, who may do it, what the
  participant sees and the service it calls when it finishes:

  | Step type | What it does | Reuses |
  |---|---|---|
  | Questions | A short form | E17 forms |
  | Upload a document | The participant uploads a file; staff verify it | E18 compliance records |
  | Show a check | A check of a required type, from the passport (FR-34-9) or an upload | E18 requirement types, background-check providers |
  | Sign an agreement | Click-to-sign a versioned agreement | E18 / gap G2 signing |
  | Book a call | The participant picks a slot; an online meeting is made | E08 slots, E22 meetings |
  | Trial lesson | A trial lesson is booked and marked | E08, E09 |
  | Family chooses | The family picks the tutor from a shared shortlist | E19 shortlist sharing |
  | Family consents | Asks the family to agree to share information (FR-34-3) | New |
  | Read and acknowledge | A document or handover pack, ticked as read | New |
  | Staff review | A named role approves or rejects, with a reason | New |
  | System check | Finishes when a condition holds (for example "calendar connected") | E33 plain questions |
- **Ready-made templates** are installed for every business and can be edited and reset to
  default, like E33 built-in workflows:
  - **Apply for a job:** answer questions → show checks → book a call → trial lesson (optional)
    → staff choose → family chooses (optional).
  - **Join a job:** sign the job agreement → checks in date → family consents → read the
    handover pack and safeguarding policy → intro call with the family → set up the online
    classroom (online jobs) → confirm the first lesson.
  - **Finish a job:** final report → return resources (E21 loans) → final statement → family
    feedback (E09) → information access ends.
- **Where pathways start:**
  - an application to a job posting (E19 job board) starts the posting's Apply pathway;
  - accepting an offer, or being assigned to a job, starts the job's Join pathway;
  - leaving a job, or the job ending, starts Finish.
  - Staff can also start any template for a tutor or a partner by hand.
- **Gates.**
  - Until Join reaches its "Ready" gate, the tutor's assignment on the job is **joining**:
    - lessons can be scheduled;
    - the tutor sees only the anonymised brief;
    - with `pathways.block_lessons_until_joined` (on by default), the first lesson can't be
      confirmed.
  - Finish ends information access when it completes.
- **The participant's view.** One **Tasks** list shows each step with its due date, what to do
  and its current state:
  - own tutors and guests see it in the tutor app;
  - partners see it in their own TutorTrack, under **Network**.
  - Staff see every run on the job, application or tutor page as a timeline (like E33 runs),
    and can complete their own steps, send a reminder, skip a step (with a reason) or cancel.
- **Workflows hook in.** Pathways publish events. A business adds extra emails and nudges with
  E33 workflows, so the pathway editor needs no timing rules of its own.
- **AC:**
  - A step can't be finished by anyone other than the person it names.
  - A gate holds until every step before it is finished or skipped with a reason.
  - Editing a template never changes runs already started; they keep their version.

### FR-34-2 Pathway editor

- Settings › Pathways lists templates. The editor is a stage-and-step list in the style of the
  E18 onboarding checklist editor and the E33 sequence editor. It offers + Add a step, Move up
  and down, gates, problems in words, Save, and Reset to default.
- Each job posting and each job can use a different Apply or Join template; the business
  default is used otherwise.
- WCAG 2.2 AA.

### FR-34-3 Consent before information is shared

- **Types of information.** Each is consented to separately:

  | Key | What it covers |
  |---|---|
  | `student_name` | The student's full name |
  | `student_details` | Year group or age, school, exam boards |
  | `contact_details` | The parent's or carer's name, email and phone |
  | `address` | The lesson address (only offered for in-person jobs) |
  | `learning_needs` | Needs, SEN and access arrangements |
  | `special_category` | Medical and other special-category information (explicit consent; always asked separately) |
  | `history` | Past lesson reports and progress |

  Safeguarding notes are **never** shared. A concern goes from one business's safeguarding lead
  to the other's (E29), never through copied data.
- **Asking.**
  - The **Family consents** step, or staff using "Ask the family" on a job, sends a signed link
    (ADR 0031 pattern) to the contact who can consent:
    - the primary contact or a guardian for a child;
    - the student themselves for an adult learner.
  - The page shows:
    - the tutor's profile card (E19 `tutor_card`);
    - the receiving business, if it's a partner;
    - each type of information asked for, and why;
    - how long the sharing lasts (until the job ends, or a date);
    - how to withdraw.
  - The family accepts or refuses each type.
  - It can be combined with **Family chooses**: one link to choose the tutor and consent.
- **Recording.**
  - Each answer is an E29 `ConsentRecord`: a new consent type `share-with-tutor`, versioned,
    with method and who gave it.
  - A **data share grant** holds the recipient (a tutor, or a partner business), the job, the
    types granted, the consent record and an expiry.
  - Staff can record consent given by phone or on paper (method `staff`, a note required). It
    is audited and the family is sent a confirmation email.
- **Releasing.**
  - Tutor-facing APIs, the tutor app and partner copies show a type of information only while a
    live grant covers it, through one function, `privacy.sharing.visible`. Without a grant, the
    student appears as first name and initial, with the postcode district.
  - Every read of released information by a partner is logged with `audit.record_read`.
- **Withdrawing and ending.**
  - The family can see and withdraw grants in the client portal ("Who can see your
    information"); staff can revoke them on the job.
  - A grant ends when it is withdrawn or revoked, when it expires, or when Finish completes.
  - When a grant ends, released fields disappear at once. A partner's copies are erased through
    the E29 provider registry. Their lesson and money records stay, with names removed, so their
    accounts still balance.
- **Own tutors.**
  - With `privacy.consent_for_own_tutors` off (the default), a business's own tutors see what
    they see today.
  - With it on, they follow the same rules as partners.
  - Partners and guests always follow these rules.
- **AC:**
  - With no grant, no API a tutor or partner can call returns a covered field. A test checks
    every tutor-facing and partner-facing serializer.
  - Withdrawing consent removes access within one request, and erases the partner's copies
    within one outbox cycle.

### FR-34-4 Connections

- **Network profile.** A business publishes a short profile:
  - its name and logo (from the E24 brand kit);
  - its type (sole trader, team, agency);
  - its subjects and levels;
  - the area it covers, and whether it teaches online;
  - a short description.
  It is visible only to its connections until T10.
- **Connecting.**
  - A business invites another by email or by a link.
  - If the person invited has no business, the link offers sign-up as a sole trader (the solo
    wizard).
  - The invited business accepts or declines.
  - Either side can pause or end a connection at any time. Ending stops new sharing; jobs that
    are running finish under their terms.
- **Terms**, agreed by both sides and versioned:
  - what may be shared: jobs, cover, the job board;
  - the default rate basis (a rate per hour, or a share of the charge);
  - the self-billing agreement (E12), so the sharing business can self-bill the partner;
  - data-processing terms: the sharing business is the controller, the partner processes data
    for it.
  A change to the terms needs both sides to accept the new version.
- **Sole traders** see a **Network** menu item in solo mode, for shared jobs and their tasks.
  Jobs received from a partner use the sole trader's own tutor record (ADR 0045 still holds).
- **AC:**
  - Neither business can see anything of the other's until both have accepted.
  - A connection is between two businesses in the same region (ADR 0028). An invitation to an
    email address on another region's stack is refused, with an explanation.

### FR-34-5 Sharing a job with a connection

- **Offering.**
  - From a job, staff offer it to one or more connections (`network.share`). This uses the E19
    offer cascade: one after another or all at once, with expiry.
  - The offer carries:
    - the anonymised brief (as E19);
    - the rate to the partner;
    - the job's required checks;
    - its Apply and Join templates.
- **Applying.**
  - The partner sees the offer under Network › Shared jobs and works through the Apply pathway.
  - A partner that is an agency **nominates one of its own tutors**, and that tutor's checks are
    the ones shown.
  - A job received from a partner can't be shared on again: one level of subcontracting only.
- **Accepting.** When the sharing business chooses the partner:
  - an **engagement** links the two businesses;
  - the partner's copy of the job is created in the partner's business:
    - the client is the sharing business (a Client of kind organisation, made once per
      connection);
    - billing method "self-billed by the client" (FR-34-6);
    - its own tutor assigned;
  - the Join pathway starts, and the family consent step inside it releases information into
    the partner's copy.
- In the sharing business, the partner appears on the job as a **partner tutor**: a tutor
  record of kind `partner` with no membership. Matching, the calendar, reports and payroll then
  work unchanged.
- **AC:**
  - Before the Join pathway's consent step finishes, the partner's copy holds no field covered
    by FR-34-3.
  - A partner can only see engagements it is a party to.

### FR-34-6 Running an engagement

- **Schedule.**
  - The sharing business owns the schedule. Lessons it books, moves or cancels on the job are
    copied to the partner's copy.
  - The partner can ask to move a lesson (E08 `reschedule.requested`, which goes back to the
    sharing business).
  - The partner can decline a changed lesson; the sharing business then sees it as needing
    cover.
- **Delivery.** The partner's tutor marks attendance and writes lesson reports in the partner's
  business. Both flow back to the sharing business's lesson (actor type `network`), where its
  own rules apply: charging the family, sharing reports and chasing late reports.
- **Money.**
  - Attendance in the sharing business creates pay items for the partner tutor at the agreed
    rate (E12).
  - Its pay run issues a self-billing statement to the partner. That arrives in the partner's
    business as an imported invoice (E28 `invoice.imported`) on the sharing business's client
    account.
  - Recording the payout in the sharing business records the payment in the partner's
    business.
  - The partner's copy never invoices the sharing business itself, so nothing is billed twice.
- **Ending.** Either side can end an engagement with notice (set in the terms).
  - The Finish pathway runs and the grants end.
  - Lessons not yet delivered go back to the sharing business, which sees them as needing
    cover.
- **Erasure.** Erasing a student or family in the sharing business erases the partner's copies
  too. Erasure in the partner's business never reaches back.
- **AC:**
  - Every copied change is idempotent, keyed by the source event id, so a replay changes
    nothing.
  - The money in the two businesses' books agrees for every completed lesson. There is a
    Hypothesis test over attendance outcomes and rates.

### FR-34-7 Guest tutors (not on TutorTrack)

- Staff add a **guest tutor** with a name and an email or mobile number. This is a tutor record
  of kind `guest`, in the business only.
- **Offers** (E19) and **cover requests** reach a guest by a signed link. The guest reads the
  anonymised brief and accepts or declines without an account.
- **Accepting** creates a passwordless login (magic link) with the built-in **Guest tutor**
  role, and starts the Join pathway. The guest then has a **guest workspace**, the tutor app
  limited to:
  - their tasks;
  - their lessons with this business;
  - marking attendance and writing reports;
  - their statements.
- Guests always follow FR-34-3: no information without consent.
- Guests must meet the job's required checks through the pathway (upload, or a request to a
  background-check provider) before the "Ready" gate.
- **"Run your own tutoring on TutorTrack."** A guest can start a sole-trader business. The
  sharing business is then asked to turn the guest relationship into a connection; when it
  agrees, the guest's jobs move to engagements from the next lesson on.
- Guests count as tutors for plan limits only once they have delivered a lesson (the existing
  `delivered` seat mode).
- **AC:** a guest can't see any job, lesson or family outside their own engagements.

### FR-34-8 Cover and the job board across connections

- **Cover.** A cover request (E19) can fall back to connections when none of the business's own
  tutors accepts in time. The setting `network.cover_fallback` says how long to wait before
  asking connections. A partner that takes cover gets a short engagement for those lessons only.
- **Job board.** A posting's audience can include connections. Partner staff see it under
  Network and apply with a nominated tutor through the posting's Apply pathway.

### FR-34-9 Tutor checks passport

- A tutor's verified checks (DBS, right to work, ID, qualifications) are held against their
  **login**, not a business. They are verified once by a background-check provider, or by the
  business that saw the original document, with who verified it and when.
- The tutor chooses which businesses may see each check, and can withdraw access at any time.
- A business maps passport checks to its own requirement types. A **Show a check** step, or its
  compliance page, accepts a passport check that is in date. Expiry still comes from the
  original.
- **AC:**
  - A business sees no passport check that the tutor hasn't shared with it.
  - Withdrawing access hides the check at once and marks the requirement as not met.

### FR-34-10 The open network

- Verified businesses and passport-verified tutors can make their network profile visible to
  every business in their region.
  - Verifying a business uses its identity checks with the payment provider and a platform
    review.
- **Public listings.**
  - A business can publish a job to the open network, with the anonymised brief only.
  - A listing also has a public page and a share link, for WhatsApp, email or social media.
    This is how a job reaches tutors who aren't on TutorTrack: the page leads to applying as a
    guest, or signing up as a sole trader.
- **Discovery:** search network profiles by subject, level, area and online teaching.
- **Trust:**
  - when an engagement ends, both sides rate it;
  - members can report or block another member, and the platform reviews reports (E30).
- **Pricing:** decide between a fee per placement and a Network add-on, using usage from T05
  to T09, then build it on E04.

### FR-34-11 Handoff for a finder's fee (later)

- A business can hand a family to a connection: the family's records move to the partner's
  business after explicit consent from the family (controller to controller), and the sharing
  business earns a finder's fee through E25 commission rules.

## 3. Data model

**Pathways** (app `pathways`; tenant tables, RLS):

- `PathwayTemplate(key, name, kind: apply | join | finish | custom, builtin_key, edited, active)`
- `PathwayTemplateVersion(template, version, stages JSONB)`
- `PathwayRun(template_version, subject_type, subject_id, participant_type: tutor | partner,
  participant_id, status, stage, started_at, finished_at)`
- `PathwayStep(run, key, type, assignee, status: waiting | open | done | skipped | rejected,
  due_at, data JSONB, completed_at, completed_by, reason)`
- Step types are registered with `@step_type(key)` in `<app>/pathway_steps.py`. Ready-made
  templates are registered with `@builtin_pathway(key)` and discovered automatically, like E33
  built-ins.

**Consent and release** (in `privacy`; tenant tables, RLS):

- `DataShareGrant(job, recipient_type: tutor | partner, recipient_id, kinds[], consent_records,
  expires_at, ended_at, end_reason)`
- New consent type `share-with-tutor` (category `data_processing`). Consent method `staff` is
  used for offline consent, with a note.

**Network** (app `network`; platform tables in the regional database). The tables are
**party-scoped**: a new RLS helper, `core.migrations_utils.enable_party_rls(columns)`, shows a
row only when the current organisation is one of its parties or in its audience. No
BYPASSRLS role is used.

- `NetworkProfile(organisation, kind, subjects, levels, area, online, description, visibility:
  connections | network, verified_at)`
- `Connection(org_a, org_b, status: invited | active | paused | ended, invited_by, terms_version,
  accepted_a_at, accepted_b_at)` and `ConnectionTerms(connection, version, shares, rate_basis,
  notice_days, self_billing_version, dpa_version)`
- `NetworkOffer(from_org, to_orgs[], source_job_id, brief JSONB, rate, required_checks,
  apply_template_version, status, expires_at)`: an anonymised snapshot, frozen at sending.
- `Engagement(org_a, job_a_id, org_b, job_b_id, connection, status, started_at, ended_at)`
  and `LessonLink(engagement, lesson_a_id, lesson_b_id)`. These hold ids only; there are no
  foreign keys across businesses.
- `SharedTask(engagement or offer, run_id, step_key, view JSONB, status)`: what a partner's
  Tasks list shows. It is written by the sharing business and holds no covered fields.
  `TaskAction(shared_task, action, data, by_user)` is written by the partner and turned into a
  signal on the sharing business's run.
- `Delivery(engagement, kind, payload EncryptedField, source_event_id, consumed_at)`: the
  hand-over of released information and copied changes. The receiving side applies it through
  its own services and then clears the payload, so personal data doesn't rest in network
  tables.
- `PassportCheck(user, requirement_key, verified_by, verified_at, expires_at, document)` and
  `PassportShare(check, organisation, granted_at, withdrawn_at)`.
- `NetworkListing`, `ListingApplication`, `EngagementRating` and `NetworkReport` (T10).

**Changes to existing models:**

- `people.TutorProfile.kind`: `own` (default) | `partner` | `guest`. Partner and guest tutors
  have no membership, or a guest-role membership.
- `jobs.JobTutor.join_status`: `joining` | `ready` (null for assignments made before E34).
- `jobs.Job.BillingMethod`: add `self_billed_by_client`. Charges are recorded but never
  invoiced, and imported self-billing statements settle them.
- `matching.JobPosting.audience`: add `connections` and `network`; `JobPosting.apply_template`.

## 4. API

- `/api/v1/pathway-templates` (CRUD, `reset-to-default`), `/api/v1/pathway-runs` (list and
  detail timeline, `start`, `cancel`), `/api/v1/pathway-runs/{id}/steps/{key}` (`complete`,
  `skip`, `reject`, `remind`), and `/api/v1/me/tasks` for the participant.
- `/api/v1/data-share-grants` (list, `revoke`), `/api/v1/jobs/{id}/ask-family`, and the public
  `/api/v1/public/consents/{token}` (GET, POST). In the portal, `/api/v1/portal/data-sharing`
  (list, `withdraw`).
- `/api/v1/network/profile`, `/api/v1/network/connections` (`invite`, `accept`, `decline`,
  `pause`, `end`, `terms`), `/api/v1/network/offers` (`send`, `withdraw`; for the receiving
  side, `nominate` and `decline`), `/api/v1/network/engagements` (list, detail, `end`),
  `/api/v1/network/tasks`, and `/api/v1/network/listings` (T10).
- `/api/v1/guest-tutors` (create, `invite`), and the public `/api/v1/public/offers/{token}`.
- `/api/v1/me/passport` (checks, `share`, `withdraw`).
- **Webhooks:** `pathway.completed`, `engagement.started`, `engagement.ended`. Consent and
  release events are internal only: ids only, never webhook event types.

## 5. Permissions

- `pathway.view`, `pathway.manage` (templates), `pathway.step.complete` (staff steps; the step's
  own role still applies).
- `privacy.data_share.request` (ask the family, record offline consent) and
  `privacy.data_share.manage` (revoke).
- `network.view`, `network.connection.manage` (owner and admin), `network.share` (offer jobs and
  cover; coordinators via `matching.*` as well), and `network.engagement.manage`.
- `people.guest_tutor.manage`. A new built-in role, **Guest tutor**, holds only the
  participant's own tasks, lessons, attendance, reports and statements.
- **Plan:** a new `network` feature on every plan (owner decision). Pathways and consent come
  with the features they attach to: the job board needs `matching`, and the Join pathway
  applies wherever jobs exist.

## 6. Delivery plan

Each ticket is one pull request, merged when CI is green, with the guides, README and test plan
updated in the same change.

- [ ] **T01 — Pathway engine.** The `pathways` app (models, RLS, isolation tests), the step-type
  registry with the first types (questions, upload, sign, read and acknowledge, staff review,
  system check), `PathwayRunWorkflow`, the services, the API, and events. Replay histories.
- [ ] **T02 — Ready-made pathways, editor and Tasks.**
  - `@builtin_pathway`: Apply, Join and Finish (install, edit, reset).
  - The remaining step types: show a check, book a call, trial lesson, family chooses.
  - Wired to the E19 job board (Apply), to offer acceptance and assignment (Join and
    `join_status`, and blocking lesson confirmation until joined), and to leaving or ending a
    job (Finish).
  - The Settings › Pathways editor, run timelines on jobs and tutors, and Tasks in the tutor
    app. WCAG 2.2 AA.
- [ ] **T03 — Consent and information release.**
  - The types of information, the `share-with-tutor` consent type, and the Family consents step
    with its public page (combined with Family chooses).
  - Data share grants, offline consent, and `privacy.sharing.visible` applied to every
    tutor-facing serializer, with the field-coverage test.
  - "Who can see your information" in the client portal; revoke, expiry and end of job
    (`DataShareGrantWorkflow`); the `privacy.consent_for_own_tutors` setting.
  - Privacy provider entries for DSAR export and erasure.
- [ ] **T04 — Network foundations.**
  - The `network` app; `enable_party_rls`; network profiles; connections (invite by email or
    link, accept, pause, end, region check) with versioned terms, self-billing and
    data-processing terms; the `network` plan feature.
  - The Network area in the admin app, shown in solo mode as well.
  - ADR 0048 confirmed against what was built.
- [ ] **T05 — Share a job with a connection.**
  - Network offers on the E19 cascade, the partner's Shared jobs inbox, `SharedTask` and
    `TaskAction`, nominating a tutor, and Apply across businesses.
  - On acceptance: the engagement, the partner's copy of the job (the sharing business as an
    organisation client, `self_billed_by_client`), the `partner` tutor record, Join across
    businesses, and releasing information into the partner's copy through `Delivery`.
- [ ] **T06 — Running an engagement.**
  - `LessonLink`; copying schedule changes; reschedule requests; declined lessons becoming
    cover; attendance and reports flowing back.
  - Self-billing statements arriving as imported invoices, and payouts as payments, with the
    Hypothesis test that both businesses' books agree.
  - Ending an engagement, erasure reaching the partner, and `EngagementWorkflow`.
- [ ] **T07 — Guest tutors.** Guest tutor records, offer and cover links, the Guest tutor role
  and workspace, checks through the pathway, seat counting, and starting a sole-trader business
  with the move to a connection.
- [ ] **T08 — Cover and the job board across connections.** `network.cover_fallback`, short
  cover engagements, and posting audiences that include connections.
- [ ] **T09 — Tutor checks passport.** Passport checks on the login, verification, sharing and
  withdrawing, mapping to each business's requirement types, and the Show a check step reading
  the passport.
- [ ] **T10 — The open network.** Verification, public network profiles and discovery, public
  listings with share links leading to guest or sole-trader sign-up, ratings, reporting and
  blocking (E30 review queue), and the pricing decision built on E04.
- [ ] **T11 — Handoff for a finder's fee.** Moving a family to a connection with explicit
  consent, and the finder's fee through E25 commission.

Order: T01 → T02 → T03 → T04 → T05 → T06, then T07, T08 and T09 in any order, then T10 and T11.
T07 needs only T03 (it can be built before T04 if guest tutors are wanted sooner).

## Temporal workflows (E32)

- `PathwayRunWorkflow` `pathway:{org}:{run}`. Signals: `step_done`, `step_reopened`,
  `cancelled`. Timers: deadlines and reminders. Gates are evaluated in the workflow; every side
  effect is an activity calling `pathways.services`. A partner's `TaskAction` reaches it as a
  signal through the bridge.
- `DataShareGrantWorkflow` `data-grant:{org}:{grant}`. It waits for the expiry or a `revoked`
  signal, then ends the grant and starts erasure at the partner.
- `EngagementWorkflow` `engagement:{org}:{engagement}`: started → active → notice → ended. It
  runs Finish and ends the grants when the engagement ends.
- Network offers reuse `JobOfferCascadeWorkflow` (E19). The recipients are businesses instead
  of tutors, through a patched branch.
- Connection invitations, listing expiry and passport expiry are read from dates when a request
  arrives, so they need no workflow and no sweeper (CLAUDE.md 4a).

## Events

- `pathway.started`, `pathway.step_completed`, `pathway.stage_completed`, `pathway.completed`,
  `pathway.cancelled`
- `data_share.requested`, `data_share.granted`, `data_share.declined`, `data_share.revoked`,
  `data_share.expired` (internal: ids only)
- `connection.invited`, `connection.accepted`, `connection.paused`, `connection.ended`,
  `connection.terms_changed`
- `network_offer.sent`, `network_offer.accepted`, `network_offer.declined`,
  `network_offer.withdrawn`; `engagement.started`, `engagement.ended`
- `guest_tutor.invited`, `guest_tutor.joined`, `guest_tutor.converted`
- `passport.check_shared`, `passport.check_withdrawn`
- `network_listing.published`, `network_listing.closed`

## Settings

- `pathways.block_lessons_until_joined` (default on), `pathways.default_templates`
- `privacy.consent_for_own_tutors` (default off), `privacy.share_default_days` (how long a
  grant lasts when the job has no end date; default: until the job ends)
- `network.cover_fallback` (hours before cover is offered to connections; default off),
  `network.profile_visibility`

## Implementation notes

None yet.
