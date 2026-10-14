# Vendor management

**Owner:** CTO · **Review:** yearly

## Before using a new supplier that processes customer data
1. Business need and the data involved (categories, children's data, volume).
2. Security evidence: SOC 2 Type II or ISO 27001 report (or a completed questionnaire),
   encryption, breach history.
3. Privacy: a DPA with Article 28 terms, data location, SCCs and the UK addendum for
   transfers outside the UK/EU, sub-processor transparency.
4. Region fit: the supplier must be able to keep data in the organisation's region where
   the product promises it (ADR 0028), or the feature stays optional and off by default.
5. DPO and CTO approval, then add it to `tutortrack/privacy/compliance.py`
   (`SUBPROCESSORS`), bump `SUBPROCESSORS_VERSION`, update [subprocessors.md](subprocessors.md)
   and run `manage.py notify_subprocessor_changes` after the deploy. Customers can object
   within 30 days under the DPA.

## Yearly review
For each sub-processor: still needed, current certification, incidents in the year, data
minimised. Record the outcome in the vendor register.
