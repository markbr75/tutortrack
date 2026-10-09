#!/usr/bin/env bash
# One-shot developer setup for TutorTrack on Ubuntu 22.04 / 24.04.
#
#   curl -fsSL https://raw.githubusercontent.com/markbr75/tutortrack/main/scripts/setup-ubuntu.sh | bash
#   # or, from a clone:  bash scripts/setup-ubuntu.sh
#
# Installs: git, make, Docker Engine + compose plugin, Node 22, pnpm 9, uv (which installs
# Python 3.12 itself), GitHub CLI. Then clones the repo, starts the backing services,
# installs dependencies, migrates and seeds demo data. Safe to re-run.
#
# The full test suite is heavy (parallel workers + 4 containers). It is skipped by default;
# run it with RUN_CHECKS=1, or later with `make check PYTEST_WORKERS=2 FE_CONCURRENCY=1`.
# Recommended: 4 GB RAM (8 GB comfortable), 2+ CPUs, 15 GB free disk.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/markbr75/tutortrack.git}"
TARGET_DIR="${TARGET_DIR:-$HOME/tutortrack}"

RUN_CHECKS="${RUN_CHECKS:-0}"

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*"; }

log "Preflight"
mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
swap_mb=$(awk '/SwapTotal/ {print int($2/1024)}' /proc/meminfo)
disk_gb=$(df -BG --output=avail "$HOME" | tail -1 | tr -dc '0-9')
cpus=$(nproc)
echo "RAM ${mem_mb} MB, swap ${swap_mb} MB, CPUs ${cpus}, free disk ${disk_gb} GB"
if [ "$mem_mb" -lt 3000 ]; then
  warn "Less than 3 GB RAM: the stack will likely freeze this machine."
  warn "Give the VM more memory (4 GB+) or add swap first:"
  warn "  sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile"
  exit 1
fi
if [ "$mem_mb" -lt 6000 ] && [ "$swap_mb" -lt 2000 ]; then
  warn "Under 6 GB RAM with little swap; consider adding a 4 GB swapfile (command above)."
fi
if [ "${disk_gb:-0}" -lt 10 ]; then
  warn "Less than 10 GB free disk; Docker images and dependencies need about 6-8 GB."
fi
# Keep test parallelism proportionate to the machine.
workers=$(( cpus > 4 ? 4 : (cpus > 1 ? cpus - 1 : 1) ))

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
log "Backing services (postgres 5442, redis 6389, s3 9010, mailpit 8025, temporal 7233/8233)"
sg docker -c "docker compose up -d --wait postgres redis s3 mailpit temporal"

log "Dependencies"
(cd backend && uv sync)
(cd frontend && pnpm install)

log "Database, storage bucket and demo data"
(cd backend && uv run python manage.py ensure_db_roles && uv run python manage.py migrate)
(cd backend && uv run python manage.py ensure_storage_bucket)
(cd backend && uv run python manage.py seed_demo)

if [ "$RUN_CHECKS" = "1" ]; then
  log "Full check suite with ${workers} test workers"
  make check PYTEST_WORKERS="$workers" FE_CONCURRENCY=1
else
  log "Quick smoke check (full suite skipped; set RUN_CHECKS=1 to run it)"
  (cd backend && uv run python manage.py check)
  curl -fsS http://localhost:9010 >/dev/null 2>&1 || true
fi

cat <<'EOF'

Setup complete. Run the full test suite when convenient:

  cd ~/tutortrack && make check PYTEST_WORKERS=2 FE_CONCURRENCY=1

Start the app in two terminals:

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
