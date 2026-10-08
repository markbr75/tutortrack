# TutorTrack

Multi-tenant SaaS to run a tutoring business end to end: scheduling, billing, payments,
payroll, portals and more. Python (Django) + PostgreSQL backend, React + TypeScript frontend.

- **Spec and build plan:** [docs/README.md](docs/README.md) (31 epics, build order in [docs/04-roadmap.md](docs/04-roadmap.md))
- **Engineering rules:** [CLAUDE.md](CLAUDE.md)
- **Status:** E01 Platform Foundations done; next is E02 Multi-Tenancy.

## Quick start (Linux / macOS)

Prerequisites: Docker, Python 3.12, [uv](https://docs.astral.sh/uv/), Node 22, pnpm 9, make.

```bash
cp .env.example .env
make infra                     # postgres, redis, s3 (SeaweedFS), mailpit
make install                   # uv sync + pnpm install
make migrate
cd backend && uv run python manage.py ensure_storage_bucket && cd ..
make seed                      # admin@tutortrack.localhost / org "brightminds"
cd backend && uv run python manage.py runserver 127.0.0.1:8010   # terminal 1
pnpm --dir frontend dev                                           # terminal 2
```

Open http://brightminds.localhost:5173. API docs: http://localhost:8010/api/v1/docs/.
Or run everything in Docker with `make dev`.

`make check` runs everything CI runs (lint, types, migrations, tests, API client drift).
