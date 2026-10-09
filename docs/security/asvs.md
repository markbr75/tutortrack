# OWASP ASVS 4.0.3 Level 2: TutorTrack status

Living checklist (E29 FR-29-1). Update it in the same PR as any change that affects a
control. Status: ✅ in place · 🟡 partial · ⏳ planned (epic) · ➖ not applicable.

| Chapter | Control area | Status | Where / notes |
|---|---|---|---|
| V1 Architecture | Threat model, trust boundaries, tenancy design | 🟡 | ADR 0001/0003 (shared schema + RLS, three DB roles). Formal threat model ⏳ E29 part 2 |
| V1.4 Access control architecture | Central enforcement, deny by default | ✅ | `core.permissions` (`has_perm`, `scope_queryset`), DRF default `IsAuthenticated`, `HasOrganisation`; RLS as a second layer |
| V2.1 Password security | Length ≥ 8, breached-password check, strength | ✅ | Django validators + zxcvbn ≥ 3 + HIBP k-anonymity (`identity/password_validation.py`) |
| V2.2 Authenticator lifecycle | Lockout, MFA, recovery | ✅ | Progressive lockout, TOTP + recovery codes, org-enforced 2FA for staff (E03) |
| V2.5 Credential recovery | Single-use, short-lived reset links, no enumeration | ✅ | 1h reset tokens, 15 min magic links, uniform 202 responses |
| V2.8 One-time passwords | Replay protection | ✅ | TOTP step can be used once (`MFADevice.last_used_step`) |
| V3 Session management | Server-side sessions, revocation, idle timeout, cookie flags | ✅ | `UserSession` tracking, revoke one/all, idle timeouts (org setting), HttpOnly/Secure/SameSite=Lax cookies (prod) |
| V3.5 Token-based sessions | Signed single-use handoff tokens | ✅ | `identity/tokens.py` (2 min, org-bound, single use) |
| V4 Access control | Object-level checks, 404 for others' records, tenant isolation | ✅ | Data scopes (all/branch/own), `TenantIsolationTestMixin` on every list/detail endpoint, RLS meta-test |
| V5 Validation & encoding | Serializer validation, ORM parameterisation, output encoding | ✅ | DRF serializers; no raw SQL with user input; React escapes output; RFC 7807 errors |
| V5.2 Sanitisation | Rich text / HTML input | ⏳ | When rich text arrives (E13 templates, E21 resources): sanitise with an allowlist |
| V5.3 Output encoding / injection | CSP | ✅ | `core.security` (nonce CSP for Django HTML, lock-down CSP for API), CloudFront CSP for the SPAs |
| V6 Stored cryptography | Approved algorithms, key management, rotation | 🟡 | Fernet (`core.crypto.EncryptedField`) with KMS envelope keys and `rotate_encryption_keys`; AES-GCM Temporal payload codec. KMS key policy review ⏳ infra |
| V7 Error handling & logging | No sensitive data in logs, audit of security events | ✅ | structlog without PII, `AuditEntry` (append-only, privileges), login events, sensitive-read audit (E29-T03) |
| V8 Data protection | Sensitive data classification, caching, retention | 🟡 | Field permissions, encryption of secrets/tax ids; retention + DSAR ⏳ E29 part 2 |
| V9 Communications | TLS everywhere, HSTS | ✅ | HSTS preload (Django + CloudFront), TLS 1.2+ at ALB/CloudFront, `rediss://` |
| V10 Malicious code | Dependency and code scanning, integrity | ✅ | CI: Semgrep, ruff `S` (Bandit), pip-audit, pnpm audit, gitleaks; Dependabot |
| V11 Business logic | Rate limits, anti-automation | ✅ | DRF scoped throttles on auth/signup, Turnstile on public forms, idempotency keys |
| V12 Files & resources | Upload type/size limits, AV scan, SSRF | ✅ | Presigned uploads with type/size checks, ClamAV, `core.net.safe_url` for outbound fetches |
| V13 API | Auth on every endpoint, schema validation, CORS | ✅ | OpenAPI-validated in CI, explicit CORS allowlist, CSRF for session auth |
| V14 Configuration | Secure headers, no debug in prod, secrets out of code | ✅ | `check --deploy` in CI, prod settings refuse to start without secrets, gitleaks |

## Known gaps and owners
- Threat model document and annual penetration test: E29 part 2 (FR-29-9).
- Suspicious-login detection beyond new-device alerts (impossible travel): needs GeoIP; E30.
- WebAuthn/passkeys: E03 Phase 2.
- Terraform security review (KMS key policies, WAF): before the first production deploy.
