# ADR 0045: Sole traders are the only tutor

- **Status:** Accepted
- **Date:** 2026-10-23
- **Scope:** people (tutor creation and status), identity (invitations, `/me`), tenancy
  (type of business), the admin app (menu, Team page). Extends ADR 0041.

## Context

ADR 0041 trimmed the admin app for sole traders (mode "solo") but kept **Tutors** in the menu,
because that was where the owner added themselves as a tutor. It was presentation only: a sole
trader could still add tutors, invite people with the Tutor role and see **Jobs** (offering
lessons to tutors). The owner's feedback: "as you are the only tutor there should not be the
ability to set up multiple tutors". The setup wizard and "Add yourself as a tutor" now make the
owner a tutor, so the list no longer has a job to do.

## Decision

1. **One tutor in solo mode, enforced in services.** `people.services.check_solo_tutor` refuses
   a tutor while another is counted (onboarding, active or restricted). `create_tutor` and
   `change_tutor_status` call it (so a second tutor can't be added or reactivated), and
   `identity.services.invite` refuses every Tutor-role invitation, because that is always
   someone else. The error (422) names the fix: change *Type of business*.
2. **No switch to Sole trader with a team.** `tenancy.services.update_organisation` refuses a
   change to solo mode while more than one tutor is counted (`people.selectors.teaching_tutor_count`).
   Otherwise a business would have tutors whose menus are hidden.
3. **"My tutor profile" replaces Tutors.** `/me` sends `membership.tutor_id`. In solo mode, the
   menu item opens `/tutors/<own id>`, or the list (with "Add yourself as a tutor") if the
   owner doesn't teach yet. **Jobs** joins the team-only items. The Team page doesn't offer
   the Tutor role.
4. **Sample data** for a sole trader uses their own tutor record, or one sample tutor.
5. Test organisations (`OrganisationFactory`) default to mode "multi": most tests model a team,
   and sole-trader tests set "solo" through `update_organisation`.

## Consequences

- Pages stay reachable by URL; what changed is that the data rules now match the menu.
- An organisation that was already solo with several tutors (made before this change) keeps
  them, but can't add more. Changing its type to a team type restores the full menus.
- Plan limits are unchanged and are checked after the solo rule.
