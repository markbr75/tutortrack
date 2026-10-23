# ADR 0046: Invoice templates as structured settings with a live preview

- **Status:** Accepted
- **Date:** 2026-10-23
- **Scope:** billing (templates, invoice PDFs, the issue snapshot), people (a family's
  template), jobs (a job's template), core (inlined images), the admin app (Billing ›
  Invoice templates, the template editor, the family and job pages).

## Context

Every organisation had one fixed invoice layout (`billing/templates/billing/invoice.html`).
The only things an organisation could change were the brand kit (logo, colour, font,
document footer) and two API-only billing settings (payment instructions and invoice
footer). The owner asked to set up their own invoice templates, to use different looks
for different jobs, and for "a good invoice editor". A review also found that invoice,
credit note and statement PDFs always used the organisation's brand kit, never the
branch's, because the renderer didn't pass the branch.

## Decision

1. **Structured templates, not free HTML.** `billing.InvoiceTemplate` holds a style
   (Classic, Modern or Compact), an accent colour (empty: brand), a logo (brand kit, its
   own or none), a title, a trading name, a message above the lines, "How to pay", a footer
   (empty: the billing settings) and which optional columns show (date, student, tutor,
   quantity, price). We rejected a free HTML or WYSIWYG template editor: a user could break
   the PDF layout or WeasyPrint, it would need sanitising (it is rendered on our servers and
   emailed), it would lose the translated labels and the accessibility of the shared layout,
   and every organisation would need support to fix its templates. The three styles are CSS
   in `_style.html` on the same HTML.
2. **The editor previews live with the PDF's own code.** `POST /invoice-templates/preview`
   renders unsaved settings on a sample invoice to HTML, and the editor shows it in a
   sandboxed iframe (no scripts). `preview-pdf` returns the same sample as a PDF. The
   preview is the same template WeasyPrint prints, so what you see is what families get.
   The accent colour is checked as a hex value in the serializer as well as the service,
   because it goes into CSS and the preview is never saved.
3. **Which template applies:** the job's, when every charge on the invoice is for one job
   (the family's invoices set to one per job). Otherwise the family's template, otherwise
   the organisation's default (one per organisation, enforced by a partial unique
   constraint; the first template becomes the default). With none, the built-in Classic
   look.
4. **Frozen at issue.** `_snapshot` stores the resolved layout under
   `billing_snapshot["template"]`. `invoice_layout` reads it for issued invoices, so
   editing or deleting a template never changes an invoice already sent (financial records
   are immutable). Invoices issued before this change keep their stored wording with the
   Classic look. Drafts use the current template.
5. **Branch branding on documents.** `pdf.render_html` passes the invoice's (or the
   client's) branch to `branding.for_documents`. Logos are inlined by
   `core.storage.inline.image_data_uri`, which is now shared with the brand kit.
6. **Permission** `billing.template.manage`, granted by `billing.*` (finance) and to owners,
   admins and branch managers. Viewing needs `billing.invoice.view`. Choosing a family's
   template needs `people.client.edit`; a job's needs `jobs.job.edit`.

## Consequences

- New columns: `people.Client.invoice_template` and `jobs.Job.invoice_template` (both
  `SET_NULL`), and the `billing_invoicetemplate` table with RLS.
- Credit notes and statements keep the brand kit look. Templates for them can follow the
  same pattern if asked for.
- Column labels and the order of the parts are fixed. Adding a style means adding CSS
  rules and a choice, not changing the data.
