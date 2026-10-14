# Sub-processors (list of 2026-10-14)

The source of truth is `tutortrack/privacy/compliance.py`; the public page is
`GET /api/v1/subprocessors` (filter with `?region=uk|eu|us|au`), shown in the Privacy centre
(Agreement & sub-processors). When the list changes, organisations are told once per
version (`manage.py notify_subprocessor_changes`) and may object within 30 days.

| Sub-processor | Purpose | Data | Location | Regions |
|---|---|---|---|---|
| Amazon Web Services | Hosting, database, storage, KMS, bulk email (SES) | All customer data | The organisation's region | all |
| Temporal Technologies | Workflow orchestration | Record ids only; payloads encrypted with our keys | The organisation's region | all |
| Postmark | Transactional email | Recipient, email address, message | United States (SCCs/UK addendum) | all |
| Twilio | SMS and WhatsApp | Phone number, message | United States (SCCs/UK addendum) | all |
| Stripe | Card payments and payouts | Payer details, payment data | US and EU (SCCs/UK addendum) | all |
| GoCardless (optional) | Direct Debit | Payer, bank details | UK and EU | uk, eu |
| PayPal (optional) | PayPal payments | Payer, payment data | Luxembourg | all |
| Cloudflare | Bot protection on public forms | IP address, browser signals | Global edge | all |
| Sentry | Error monitoring | Technical data, PII scrubbed | Germany | all |
| Google, Microsoft (optional) | Calendar and video connections | Lesson times, attendee emails | Global (SCCs) | all |
| Zoom, Lessonspace (optional) | Online lesson rooms | Participant names, times | Global (SCCs) | all |
| Xero, QuickBooks (optional) | Accounting sync | Client names, invoices, payments | Global (SCCs) | all |

"Optional" sub-processors only receive data when the organisation connects that integration.
