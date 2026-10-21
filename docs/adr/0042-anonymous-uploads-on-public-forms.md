# ADR 0042: Anonymous uploads on public forms, and gap batch G5a

- **Status:** Accepted
- **Date:** 2026-10-21
- **Scope:** core (`core.storage.public`, `/public/uploads`, retention), leads (enquiry
  form file fields), recruitment (application form CV and video, interviews, probation,
  offboarding, subject tests), scheduling (`fit_slots`), calendar_sync (stand-alone meetings).

## Context

Two public forms needed files from people who have no login: families attaching school
reports to an enquiry (FR-17-1) and applicants sending a CV and a video introduction
(FR-18-1). The only upload path (`/files/uploads`) needs a signed-in user: it records the
uploader, and access rules let the uploader open their own files. The E24 widgets were
expected to bring anonymous uploads, but they post to the tenant cross-origin and can't PUT
to storage under a bucket CORS policy we don't control per customer site.

Anonymous uploads open three risks: the bucket used as free file hosting, a token guessed or
replayed to attach someone else's file, and a renamed executable passed off as a PDF.

## Decision

1. **One shared mechanism, `core.storage.public`,** used by both forms. It keeps the
   existing direct-to-storage flow (presigned PUT, `complete_upload` checks of size and
   declared type, the ClamAV scan task) and adds:
   - **Upload contexts.** Apps register a resolver (`register_context("form", …)` in leads,
     `"opening"` in recruitment) that returns the kinds a published form accepts. An upload
     is refused unless the form exists, is published (an opening also open) and has a file
     field of that kind.
   - **Kinds with their own limits:** `document` (PDF, Word, JPEG/PNG/WebP/HEIC; 10 MB), `cv`
     (PDF, Word; 10 MB) and `video` (MP4, MOV, WebM; 100 MB), from `PUBLIC_UPLOADS` settings.
   - **Signature sniffing** on completion: the first bytes are read with a ranged GET and
     must match the declared type (`%PDF-`, the OLE/ZIP headers, image magic numbers,
     `ftyp`/EBML for video); a mismatch rejects the file and deletes the object.
   - **Signed upload tokens** (`django.core.signing`, salted, 24 hours) carry the file id, the
     organisation, the kind and the context. The visitor never sees a file id. `claim()`
     attaches a file to the new record exactly once, only for the same form and a field of
     the same kind, and only after the upload completed.
   - **Unclaimed uploads are purged** by the E29 retention engine (`unclaimed_public_uploads`,
     2 days by default, minimum 1), keyed by the `org/<org>/public/` storage prefix and an
     empty owner, so no new column is needed on `StoredFile`.
   - Files are private with no uploader; staff open them through the owner's access rule
     (`leads.enquiry`/`leads.formsubmission` → `leads.enquiry.view`,
     `recruitment.tutorapplication` → `recruitment.application.view`).
   - Both endpoints are throttled per IP (`public_upload`, 60/hour).
2. **Form submissions carry tokens, records keep files.** A `file` field's answer is a token
   (or a list); the owning service claims them after creating the enquiry or application and
   rewrites the submission's answer as file references, so tokens are never stored as data.
3. **Widgets link to the hosted form** for file fields rather than uploading.

Other decisions in the batch, recorded in the E18 notes: interview booking reuses the slot
engine by factoring its core into `scheduling.availability.fit_slots(free, busy, …)` and
feeding it either the interviewer's tutor availability or organisation interview hours;
stand-alone meetings for interviews go through `calendar_sync.meetings` rather than a new
model; `InterviewWorkflow` and `ProbationReviewWorkflow` are Temporal workflows (timers and a
human decision), while offboarding stays a checklist with auto-ticking steps because it has
no timers.

## Consequences

- One code path to harden (and to test) for every future anonymous upload, such as E24
  booking forms.
- Integrators can upload through the same public endpoints before posting a form.
- If the bucket's CORS policy ever allows customer sites, widgets can adopt the same flow.
- A token's 24-hour life means a visitor who leaves a form open overnight re-adds the file.
