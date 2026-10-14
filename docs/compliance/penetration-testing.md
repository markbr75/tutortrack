# Penetration testing

**Owner:** CTO · **Review:** yearly

- **Frequency:** once a year, and before launching a new region or a major new surface
  (public API, widgets, the portal PWA).
- **Tester:** an independent CREST-accredited firm (CHECK-approved where customers need it).
- **Scope:** the admin app, the portal, public pages and widgets, the public API (API keys and
  OAuth), the authentication flows (passwords, magic links, MFA, passkeys, SSO), tenant
  isolation between two test organisations, file upload and download, webhooks (SSRF), and
  the AWS configuration review. Production data is never used: tests run against a staging
  stack seeded with demo data.
- **Remediation:** critical 14 days, high 30 days, medium 90 days; re-test confirms the fix.
  Findings and their status go in the risk register.
- **Evidence:** the report, the remediation tickets and the re-test letter (shared with
  customers under NDA on request).
