# E19 — Tutor matching and job marketplace: manual tests

**Scope.** Scored tutor search for a job (hard filters, nine weighted factors, availability heatmap, map), shortlists, direct offers (sequential or simultaneous, with expiry and admin confirmation), the internal job board, cover requests, matching analytics and (Phase 2b) sharing a shortlist with the family. Spec: [E19](../epics/E19-matching-marketplace.md); decisions in [ADR 0013](../adr/0013-matching-hard-filters-and-offer-cascades.md).

**Built differently from the spec (Implementation notes win):**
- Weights are the org setting `matching.weights` (edited on **Matching → Weights**), not a table.
- Rating uses referee ratings (E18) and, since E25/E09, family ratings. Gender preference and SEN tags are not built.
- The map is a schematic plot of rounded tutor locations, not map tiles.
- The public job board is the E18 vacancies page.
- Offer cascades are per batch (`job-offer:{org}:{batch}`), so a job can be offered again after a cascade ends.

**Common preconditions.**
- Stack running and seeded (see [README](README.md)); admin app http://brightminds.localhost:5173, tutor portal http://brightminds.localhost:5174/portal/tutor. Password: `SEED_ADMIN_PASSWORD` (default `tutortrack`).
- The trial carries the Agency plan, so `matching` is on.
- Seed: Ada Okafor's job (Physics, A level) is **seeking a tutor**; Arjun Patel's job is active with Nia Adeyemi (Tuesdays 16:30). Seeded tutor subjects are *claimed*, not approved, and Sam Clarke is `onboarding`.
- **Matching setup (do once):** on Sam Clarke's tutor record, approve Physics (A level) and set his status to **Active**; approve Nia's Maths (GCSE). Make sure neither is restricted by compliance (verify a DBS for each if needed, see E18 TP-E18-022/023). Give Sam availability (e.g. Mon–Fri 15:00–20:00, as the seed gives active tutors) and an address so distance can score.
- A second tutor login is useful for offers: invite Sam to the portal from his tutor record and accept in a private window (Mailpit), or use tutor@ (Nia) for Maths jobs.
- Temporal worker running for offer expiry and cover deadlines (http://localhost:8233).

## Matching search (FR-19-1, T01, T02, T07)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E19-001 | Search from a job | Coordinator | Matching setup done | 1. Open **Jobs**, then Ada Okafor's Physics job.<br>2. Click **Find a tutor** (`/jobs/<id>/match`). | Sam Clarke is listed with a score 0–100, distance and availability. Nia (no approved Physics) is not listed. A `MatchQuery` is stored. | P1 | backend: `tutortrack/matching/tests/test_matching.py::test_search_api_records_query_and_shortlist` | |
| TP-E19-002 | Unapproved and restricted tutors never match | Coordinator | Un-approve Sam's Physics, or restrict Sam | 1. Re-run the search with no extra criteria. | "No tutors match…" message. (AC FR-19-1) | P1 | backend: `tutortrack/matching/tests/test_matching.py::test_only_approved_compliant_tutors_match_unless_include_restricted` | |
| TP-E19-003 | Lapsed blocking check excludes a tutor | Coordinator | Sam's DBS expired (E18) | 1. Search. | Sam not listed even if his status was manually set active. | P1 | backend: `tutortrack/matching/tests/test_matching.py::test_only_approved_compliant_tutors_match_unless_include_restricted` | |
| TP-E19-004 | Include restricted (Admin only) | Admin, Coordinator | Sam restricted or claimed only | 1. As Admin, tick **Include restricted and unapproved tutors**.<br>2. As Coordinator, look for the toggle. | Admin: Sam listed, flagged **Restricted** with reasons, and can't be offered from the UI; the search is audited. Coordinator: no toggle; the API refuses `include_restricted`. | P1 | backend: `tutortrack/matching/tests/test_matching.py::test_include_restricted_needs_permission` | |
| TP-E19-005 | Score breakdown | Coordinator | TP-E19-001 | 1. Expand **Score breakdown** for Sam. | Nine factors: Availability, Distance, Rating, Experience, Spare capacity, Similar lessons taught, Margin, Offer acceptance, Time since last job. Unknown inputs show **Unknown** (scored 0.5). | P1 | backend: `tutortrack/matching/tests/test_matching.py::test_scoring_breakdown_ranks_free_tutor_first` | |
| TP-E19-006 | Availability heatmap per slot | Coordinator | Job with weekly slots (e.g. Wed 17:00) | 1. Look at the availability column/heatmap. | Each slot over the next four weeks shows free/busy for the tutor; a lesson clash or time off lowers availability. | P2 | backend: `tutortrack/matching/tests/test_matching.py::test_lesson_clash_lowers_availability` | |
| TP-E19-007 | Travel radius and delivery mode | Coordinator | In-person job; Sam's address far away (beyond his radius) | 1. Search.<br>2. Change the job to online and search again. | In person: Sam excluded. Online: Sam included. | P2 | backend: `tutortrack/matching/tests/test_matching.py::test_mode_radius_exclusions_branch_and_current_tutors` | |
| TP-E19-008 | Excluded and current tutors | Coordinator | Add Sam to Ada's "excluded tutors" | 1. Search. | Sam not listed. Tutors already on the job are not listed either. | P2 | backend: `tutortrack/matching/tests/test_matching.py::test_mode_radius_exclusions_branch_and_current_tutors` | |
| TP-E19-009 | Ad hoc criteria | Coordinator | None | 1. On **Matching**, search ad hoc: subject Physics, level A level, postcode LS6 2AB, language, maximum pay rate £30. | Results honour the criteria; the postcode is geocoded by the fake geocoder. | P2 | backend: `tutortrack/matching/tests/test_matching.py::test_ad_hoc_criteria_from_input` | |
| TP-E19-010 | Map of tutors and lessons | Coordinator | Search results | 1. Open **Map**. | A labelled schematic ("Map of the lessons and N tutors") with rounded tutor locations; no exact addresses. Keyboard and screen-reader users get the same information in the list. | P2 | No | |
| TP-E19-011 | Weights change the ranking | Admin | Two matching tutors | 1. On **Matching → Weights**, set Distance high and others low; save ("Weights saved.").<br>2. Search again. | Ranking changes accordingly. Coordinators can't change weights. | P2 | backend: `tutortrack/matching/tests/test_matching.py::test_weights_setting_changes_score` | |
| TP-E19-012 | Branch filter | Branch manager | multi_branch on; a tutor in another branch | 1. Search as manager@. | Only tutors of MAIN listed. | P3 | backend: `tutortrack/matching/tests/test_matching.py::test_mode_radius_exclusions_branch_and_current_tutors` | |
| TP-E19-013 | AI explanation of a match | Coordinator | AI features on (fake provider) | 1. On a result, ask for the AI explanation. | A short explanation from the fake provider appears, clearly marked as AI. | P3 | No | |

## Shortlists and offers (FR-19-2, T03, T04)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E19-014 | Shortlist tutors | Coordinator | Results | 1. Click **Shortlist** for Sam (and another tutor). | Marked **Shortlisted**; the score is kept per job. | P1 | backend: `tutortrack/matching/tests/test_matching.py::test_search_api_records_query_and_shortlist` | |
| TP-E19-015 | Send a sequential offer | Coordinator | Two shortlisted tutors | 1. Tick both in order, **How to offer** = One after another, hours = 24, **Send offers**. | Offers show the first as **Waiting for an answer**, the second **Queued**. The first tutor gets a notification. | P1 | backend: `tutortrack/matching/tests/test_workflows.py::test_sequential_cascade_moves_on_after_a_decline_and_fills` | |
| TP-E19-016 | Offer brief is anonymised | Tutor | Offer to Sam (or Nia for a Maths job) | 1. In the portal open **Jobs** (`/portal/tutor/jobs`) → **Job offers**. | Shows students' first names and initials (e.g. "Ada O."), postcode district (not the full address), schedule, pay rate if shown, notes, "answer by <time>". | P1 | backend: `tutortrack/matching/tests/test_matching.py::test_offer_brief_is_anonymised_and_acceptance_assigns_tutor` | |
| TP-E19-017 | Decline moves the cascade on | Tutor | TP-E19-015 | 1. First tutor clicks **Decline** with reason "Too far". | Their offer **Declined** with the reason; the next tutor's offer is sent. | P1 | backend: `tutortrack/matching/tests/test_matching.py::test_decline_with_reason_and_expiry` | |
| TP-E19-018 | Accept assigns the tutor | Tutor | Offer to Sam | 1. Sam clicks **Accept**. | Batch **Filled**. Sam is assigned to Ada's job; a lesson series is created from the job's weekly schedule if it had none; Sam and the Okafor family get introduction notifications; other offers are **Withdrawn** with a notice. | P1 | backend: `tutortrack/matching/tests/test_matching.py::test_offer_brief_is_anonymised_and_acceptance_assigns_tutor` | |
| TP-E19-019 | Simultaneous offers: first acceptance wins | Coordinator, two tutors | Two shortlisted | 1. Send **All at once**.<br>2. Tutor A accepts, then tutor B tries. | A wins; B's offer shows **Withdrawn** and accept is refused. | P1 | backend: `tutortrack/matching/tests/test_matching.py::test_start_offers_rules` | |
| TP-E19-020 | Admin confirmation mode | Coordinator | `matching.admin_confirms` on | 1. Tutor accepts.<br>2. Coordinator clicks **Confirm tutor** (or **Turn down**). | Batch **Waiting for your confirmation** until confirmed; then assigned. Turn down moves to the next tutor. | P2 | backend: `tutortrack/matching/tests/test_matching.py::test_admin_confirmation`, `tutortrack/matching/tests/test_workflows.py::test_an_accepted_offer_waits_for_the_coordinator` | |
| TP-E19-021 | Unanswered offers expire; batch exhausted | Coordinator | Offer with 1 hour expiry; Temporal worker | 1. Don't answer; watch `JobOfferCascadeWorkflow` timers in the Temporal UI. | Offers become **No answer**; the batch ends **No one accepted** and staff get an alert. | P2 | backend: `tutortrack/matching/tests/test_workflows.py::test_unanswered_offers_expire_and_the_batch_is_exhausted` | |
| TP-E19-022 | Withdraw offers | Coordinator | Open batch | 1. Click **Withdraw offers**. | All open offers **Withdrawn**; tutors notified; the batch **Withdrawn**; a new batch can be sent later. | P2 | No | |
| TP-E19-023 | Restricted tutor can't be offered | Admin | Include restricted on | 1. Try to tick a restricted tutor for an offer. | Not selectable; the API refuses with `tutor_not_compliant`. | P1 | backend: `tutortrack/matching/tests/test_matching.py::test_start_offers_rules` | |

## Job board (FR-19-3, T05)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E19-024 | Post a job to the board | Coordinator | Ada's job seeking a tutor | 1. On the match page click **Post to the job board**. | "Open to N eligible tutors · 0 applied". Eligible tutors (passing hard filters) are notified. | P1 | backend: `tutortrack/matching/tests/test_matching.py::test_job_board_publish_apply_select` | |
| TP-E19-025 | Tutor applies | Tutor | Eligible tutor (Sam) | 1. Portal **Jobs → Job board**.<br>2. Add a message and proposed slots, click **Apply**. | "You've applied". Ineligible tutors (e.g. Nia) see "No open jobs for you right now." | P1 | backend: `tutortrack/matching/tests/test_matching.py::test_job_board_publish_apply_select` | |
| TP-E19-026 | Applying twice | Tutor | TP-E19-025 | 1. Apply again (API). | Refused; one application per tutor. | P3 | backend: `tutortrack/matching/tests/test_matching.py::test_posting_application_unique` | |
| TP-E19-027 | Staff choose an applicant | Coordinator | Two applicants | 1. Review applicants (sorted by match score).<br>2. Click **Choose this tutor**. | The chosen tutor is assigned like an accepted offer ("You got the job"); others see "Another tutor was chosen". | P1 | backend: `tutortrack/matching/tests/test_matching.py::test_job_board_publish_apply_select` | |
| TP-E19-028 | Take a posting off the board | Coordinator | Open posting | 1. Click **Take off the job board**. | Tutors no longer see it. | P3 | No | |

## Cover requests (FR-19-4, T06)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E19-029 | Coordinator asks for cover | Coordinator | Arjun's lessons with Nia; a second approved Maths tutor free on Tuesdays | 1. Open **Matching → Cover requests**.<br>2. Create a cover request for next Tuesday's 16:30 lesson. | Status **Looking for cover**, "N tutors asked", deadline shown. Free eligible tutors (up to `matching.cover_notify_limit`) are notified. | P1 | backend: `tutortrack/matching/tests/test_matching.py::test_cover_notifies_free_tutors_and_acceptance_moves_lessons` | |
| TP-E19-030 | Tutor asks cover for own lesson | Tutor | tutor@ (Nia) | 1. From her lesson in the portal, ask for cover. | Request created for her own lesson only; not for other tutors' lessons. | P2 | backend: `tutortrack/matching/tests/test_matching.py::test_cover_rules_and_unfilled` | |
| TP-E19-031 | Another tutor takes the cover | Tutor | TP-E19-029 | 1. Second tutor opens **Jobs → Cover**, clicks **I'll cover it**. | **Covered**. Only that lesson moves to the new tutor (re-priced for pay); the job keeps Nia; later lessons unchanged. | P1 | backend: `tutortrack/matching/tests/test_matching.py::test_cover_notifies_free_tutors_and_acceptance_moves_lessons` | |
| TP-E19-032 | Staff assign cover directly | Coordinator | Open request | 1. Open **Who's free** and **Give them the cover**. | Lesson reassigned; request **Covered**. | P2 | No | |
| TP-E19-033 | Nobody takes it | Coordinator | Request with cut-off soon; Temporal worker | 1. Wait for the `CoverRequestWorkflow` deadline. | **No cover found**; staff alerted. | P2 | backend: `tutortrack/matching/tests/test_workflows.py::test_cover_nobody_takes_is_escalated_at_the_deadline` | |
| TP-E19-034 | Cover rules | Coordinator | A past or cancelled lesson | 1. Request cover for it. | Refused (planned future lessons only). | P3 | backend: `tutortrack/matching/tests/test_matching.py::test_cover_rules_and_unfilled` | |

## Shortlist sharing (FR-19-5, T08, Phase 2b)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E19-035 | Share the shortlist with the family | Coordinator | Ada's job with two shortlisted tutors; Tom Okafor's email | 1. On the match page open **Share the shortlist with the family**.<br>2. Leave all tutors unticked, add a message, 14 days, **Send to the family**. | "2 tutors sent to Tom Okafor"; status **Waiting for the family**, "Not opened yet", "Open until <date>". Mailpit has the `shortlist_shared` email with `/shortlists/<token>`. | P1 | backend: `tutortrack/matching/tests/test_sharing.py::test_sharing_sends_the_family_a_signed_link` | |
| TP-E19-036 | Public page shows minimal tutor cards | Family | TP-E19-035 | 1. Open the link in a private window. | "Tutors for Physics"; cards with display name (first name and initial), headline, bio, approved subjects, qualifications, experience, languages, modes, rating and photo. No surnames, contact details, addresses, pay rates or scores. Staff view shows "Opened <date>". | P1 | backend: `tutortrack/matching/tests/test_sharing.py::test_public_page_shows_minimal_tutor_cards` | |
| TP-E19-037 | Family chooses a tutor | Family | TP-E19-036 | 1. Click **Choose Sam C.**, add a note, **Choose this tutor**. | "Thank you for choosing…". Staff get `staff_shortlist_choice`; with `matching.share_choice_starts_offer` on, an offer goes to Sam (his portal **Jobs**). Staff view shows "Chose Sam C.". | P1 | backend: `tutortrack/matching/tests/test_sharing.py::test_choosing_a_tutor_starts_an_offer_and_tells_staff` | |
| TP-E19-038 | Choice without an automatic offer | Coordinator | Setting off, or offers already out | 1. Family chooses. | Choice recorded; staff decide; no offer batch started. | P2 | backend: `tutortrack/matching/tests/test_sharing.py::test_choice_without_automatic_offer` | |
| TP-E19-039 | Only shared tutors can be chosen | Family | Share of one tutor | 1. Post a different tutor id to `/api/v1/public/shortlists/<token>`. | Refused. | P2 | backend: `tutortrack/matching/tests/test_sharing.py::test_only_shared_tutors_can_be_chosen` | |
| TP-E19-040 | Revoked, expired and foreign links | Coordinator, Family | A share | 1. Click **Withdraw link** and open it.<br>2. Open an expired link.<br>3. Open the token on northside.localhost:5173. | "This link is no longer available" / "This link has expired…" / "This link isn't valid" (404). | P1 | backend: `tutortrack/matching/tests/test_sharing.py::test_expired_revoked_and_foreign_links` | |

## Analytics (FR-19-6, T09)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E19-041 | Matching analytics | Admin | Filled and unfilled jobs, offers | 1. Open **Matching → Analytics**. | Time to match (90 days: jobs matched, average and median hours), offer acceptance per tutor (sent, accepted), unmatched demand by subject and area with longest wait (days), searches with no results by subject. | P2 | backend: `tutortrack/matching/tests/test_matching.py::test_analytics` | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E19-042 | Coordinator can search, offer, post, cover and share | Coordinator | coordinator@ | 1. Use each action. | Allowed; but no **Include restricted** toggle and no weight changes. | P1 | No | |
| TP-E19-043 | Tutor sees only own offers, postings and cover | Tutor | tutor@ | 1. Open `/matching` in the admin app.<br>2. Open `/portal/tutor/jobs`. | Admin matching refused. Portal shows only offers sent to Nia, postings she's eligible for, cover she can take. | P1 | No | |
| TP-E19-044 | Finance has no matching | Finance | finance@ | 1. Look for **Matching**. | Hidden; `/api/v1/matching/search` 403. | P2 | No | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E19-045 | Another organisation's tutors never match | Owner (Northside) | owner@northside.localhost; a Northside job seeking a tutor | 1. Search for a tutor in Northside. | Brightminds tutors never appear. Brightminds shortlists, batches, postings and cover requests are 404 there. | P1 | backend: `tutortrack/matching/tests/test_matching.py::TestShortlistIsolation`, `::TestOfferBatchIsolation`, `::TestJobPostingIsolation`, `::TestCoverRequestIsolation`, `tutortrack/matching/tests/test_sharing.py::TestShortlistShareIsolation` | |

## i18n, time zones and currency

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E19-046 | Schedules, deadlines and pay | Tutor | Offer | 1. Check days (Mon–Sun), times, "answer by", pay rate. | Days in en-GB short form, UK times (right across the clock change), pay as £28.00/h. | P2 | No | |

## Errors and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E19-047 | Tutor becomes restricted while an offer is open | Tutor, Admin | Open offer to Sam | 1. Restrict Sam.<br>2. Sam clicks **Accept**. | Refused with `tutor_not_compliant`; the cascade moves on. | P2 | No | |
| TP-E19-048 | Shares in DSAR export and erasure | Admin | Shared shortlist with a family note | 1. Export then erase Tom Okafor (E29). | The note and message are in the export and removed on erasure. | P3 | backend: `tutortrack/matching/tests/test_sharing.py::test_shares_are_in_dsar_exports_and_erased` | |

## Gap batch G5c (2026-10-21): exam board, SEN experience and gender preference (FR-19-1)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E19-049 | Needs come from the job's students | Coordinator | Arjun: exam board AQA (and CCEA), SEN tags dyslexia, ADHD; Maths lists AQA and Edexcel | 1. Open the job's **Find a tutor** page. | The "Students' needs" panel shows AQA (not CCEA) and Dyslexia, ADHD; a tutor teaching AQA with both tags ranks above one with neither recorded, who ranks above one teaching only OCR with one tag; the breakdown shows Exam board and SEN experience. | P1 | backend: `tutortrack/matching/tests/test_needs.py::test_exam_board_and_sen_experience_rank_tutors`; frontend: `matching/Needs.test.tsx` | |
| TP-E19-050 | Searches without needs score as before | Coordinator | A job whose students have no needs recorded | 1. Search. | The breakdown has the original nine factors only and the scores are unchanged. | P2 | backend: `test_needs.py::test_searches_without_needs_score_as_before` | |
| TP-E19-051 | Gender preference is off by default | Admin, Coordinator | Arjun prefers a female tutor; female and male tutors fit | 1. Search with the setting off.<br>2. **Matching → Weights**: turn on gender preferences; search again. | Both tutors match first; only the female tutor after turning it on. | P1 | backend: `test_needs.py::test_gender_preference_filters_only_when_turned_on` | |
| TP-E19-052 | Change the needs for one search | Coordinator | The job above | 1. Edit exam boards to "OCR, Edexcel", pick a gender preference, **Search again**. | Results use the edited needs; nothing is saved to the student. | P2 | backend: `test_needs.py::test_api_needs_override_and_sensitive_values_hidden`; frontend: `matching/Needs.test.tsx` | |
| TP-E19-053 | Sensitive needs stay hidden | Custom role without `people.student.view_sensitive` / `people.tutor.view_sensitive` | As above | 1. Search; open the student and the tutor records. | The search response shows no SEN tags or gender preference; the records hide SEN tags, the gender preference and the tutor's gender; searches store only the number of SEN tags. | P1 | backend: `test_needs.py::test_api_needs_override_and_sensitive_values_hidden`, `::test_people_fields_are_cleaned_and_permission_guarded` | |
| TP-E19-054 | Edit a matching profile | Coordinator | A tutor record | 1. **Matching profile → Edit**: SEN experience, exam boards, gender. | Saved trimmed and de-duplicated ("Dyslexia, dyslexia" → "Dyslexia"). | P2 | backend: `test_needs.py::test_people_fields_are_cleaned_and_permission_guarded`; frontend: `matching/Needs.test.tsx` | |
