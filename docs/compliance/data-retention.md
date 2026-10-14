# Data retention policy

**Owner:** DPO · **Review:** yearly

## What the product does
Each organisation has a retention period per category (Privacy centre → Retention). The
nightly **RetentionPurgeWorkflow** (a Temporal Schedule per organisation, 02:00 local time)
runs while `privacy.retention_purge` is `dry_run` (report only) or `on` (purge): it reports
what is past its period, purges or anonymises it in batches and notifies the admins. Staff can
start a dry run or a purge at any time. Anything under a **legal hold** is skipped.

| Category | Default | What happens |
|---|---|---|
| Archived students | 6 years after archiving | Erased (anonymised) across every app |
| Archived clients | 6 years after archiving (and all their students) | Erased across every app |
| Rejected or withdrawn tutor applications | 6 months | Erased |
| Lesson report notes and comments | 6 years after the lesson | Answers cleared, comments deleted |
| Online lesson recordings | 1 year | Recording links removed |
| Message log and in-app notifications | 2 years | Deleted |
| Form submissions that didn't become an enquiry | 1 year | Content cleared |
| Bill-payer details of erased people | `privacy.financial_retention_years` (6) | Invoice snapshots anonymised |
| Audit log | 7 years (minimum) | Deleted (the only allowed delete of the audit table) |

## Erasure
Erasure (from a data subject request or a retention policy) replaces names with a token such
as "Erased Student #1234", clears other personal fields, deletes files, notes and learning
records, ends logins and keeps **financial records** (amounts, dates, references) because
the law requires them; their personal parts are anonymised, and the bill payer's details stay
on invoices only until the financial retention period ends.

## Kept on purpose
- Safeguarding records: kept under safeguarding guidance (until the child's 25th birthday, or
  longer for allegations about adults); never auto-purged.
- Consent records: kept as evidence, with names and IP addresses removed on erasure.
- Suppression lists: kept so opt-outs keep working.
- Audit entries: kept for the audit period (they may contain old values).
