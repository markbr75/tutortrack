# Access control and access reviews

**Owner:** CTO · **Review:** yearly

## Joiners, movers, leavers
- **Joiners** get accounts from a ticket approved by their manager, with the role's baseline
  access only. Production access is a separate, justified request.
- **Movers**: access is re-requested for the new role; the old access is removed the same day.
- **Leavers**: all accounts (SSO, GitHub, AWS, Temporal Cloud, Sentry, the support tool) are
  disabled on the last working day; the ticket is closed with evidence.

## Production and customer data
- Engineers have no standing access to production data. Break-glass roles are time-limited,
  require a ticket and are logged.
- Support staff see a customer's organisation only through **support access** that the
  customer grants (E03), recorded in the customer's audit log and notified to their staff.
- Platform admin tools (the BYPASSRLS database role) are limited to the platform admin app.

## Quarterly access review
Every quarter the CTO exports the members of each system (SSO groups, GitHub org and teams,
AWS IAM Identity Center assignments, Temporal Cloud users, Sentry, PagerDuty) and each
manager confirms or removes every entry. The signed export and the removal tickets are the
evidence. Inside the product, tenant owners review their own team (`/team`) and roles.

## Authentication
SSO with phishing-resistant MFA (passkeys or security keys) for staff; password manager for
the few non-SSO services; service credentials in AWS Secrets Manager, rotated yearly or on
staff departure.
