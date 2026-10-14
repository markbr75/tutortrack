# Change management

**Owner:** Engineering lead · **Review:** yearly

1. Every change is a pull request against `main`, linked to an epic ticket.
2. At least one reviewer who did not write the change approves it.
3. CI must pass: `make check` (ruff, mypy, eslint, tsc, unit tests, migration drift, OpenAPI
   drift), the security job (Semgrep, gitleaks, pip-audit, pnpm audit) and the Playwright e2e
   job. Branch protection blocks merging otherwise.
4. Database migrations are backward compatible (expand/contract), so a deploy can roll back.
5. Deploys run from GitHub Actions only; the deploy log records who merged, the commit and
   the time. Rollback steps: `docs/runbooks/rollback.md`.
6. Emergency changes may skip the waiting period but not review or CI; they are reviewed
   again within two working days.
7. Significant design decisions are recorded as ADRs in `docs/adr/`.

**Evidence for auditors:** the pull request (review, CI checks), the deploy workflow run and
the release notes. Sample per quarter.
