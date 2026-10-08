#!/usr/bin/env bash
# One-shot developer setup for TutorTrack on Ubuntu 22.04 / 24.04.
#
#   curl -fsSL https://raw.githubusercontent.com/markbr75/tutortrack/main/scripts/setup-ubuntu.sh | bash
#   # or, from a clone:  bash scripts/setup-ubuntu.sh
#
# Installs: git, make, Docker Engine + compose plugin, Node 22, pnpm 9, uv (which installs
# Python 3.12 itself), GitHub CLI. Then clones the repo, starts the backing services,
# installs dependencies, migrates, seeds demo data and runs the full check suite.
# Safe to re-run.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/markbr75/tutortrack.git}"
TARGET_DIR="${TARGET_DIR:-$HOME/tutortrack}"

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

log "Base packages"
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg git make build-essential

if ! command -v docker >/dev/null 2>&1; then
  log "Docker Engine"
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" |
    sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
sudo usermod -aG docker "$USER"

if ! command -v node >/dev/null 2>&1 || [ "$(node -v | cut -d. -f1)" != "v22" ]; then
  log "Node.js 22"
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi

if ! command -v pnpm >/dev/null 2>&1; then
  log "pnpm 9"
  sudo npm install -g pnpm@9.15.9
fi

if ! command -v uv >/dev/null 2>&1; then
  log "uv (Python package manager)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

if ! command -v gh >/dev/null 2>&1; then
  log "GitHub CLI"
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg |
    sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg status=none
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] \
https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y gh
fi

log "Repository"
if [ ! -d "$TARGET_DIR/.git" ]; then
  git clone "$REPO_URL" "$TARGET_DIR"
fi
cd "$TARGET_DIR"
[ -f .env ] || cp .env.example .env

# The docker group change only applies to new logins; run compose through `sg` this time.
log "Backing services (postgres 5442, redis 6389, s3 9010, mailpit 8025)"
sg docker -c "docker compose up -d --wait postgres redis s3 mailpit"

log "Dependencies"
(cd backend && uv sync)
(cd frontend && pnpm install)

log "Database, storage bucket and demo data"
(cd backend && uv run python manage.py migrate)
(cd backend && uv run python manage.py ensure_storage_bucket)
(cd backend && uv run python manage.py seed_demo)

log "Full check suite (lint, types, migrations, tests, API client drift)"
make check

cat <<'EOF'

Setup complete. Start the app in two terminals:

  cd ~/tutortrack/backend && uv run python manage.py runserver 127.0.0.1:8010
  pnpm --dir ~/tutortrack/frontend dev

Open http://brightminds.localhost:5173 and sign in as admin@tutortrack.localhost
(password: tutortrack). API docs: http://localhost:8010/api/v1/docs/

Working on this box from another machine? Forward the ports and browse locally:
  ssh -L 5173:localhost:5173 -L 8010:localhost:8010 <user>@<this-box>

To push CI workflow files, your GitHub login needs the workflow scope:
  gh auth login --scopes workflow

Log out and back in once so you can run docker without sudo.
EOF
