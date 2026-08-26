#!/usr/bin/env bash
# ============================================================
# Staykaro AI Caller — Deployment Script
# NH-05: Handles first-time deploy and subsequent updates.
#
# Run on the VPS as the deploy user:
#   bash /opt/staykaro/scripts/deploy.sh
#
# Environment:
#   REPO_URL      — Git repository HTTPS or SSH URL (required for first run)
#   DEPLOY_BRANCH — Branch to deploy (default: main)
#   APP_DIR       — Application directory (default: /opt/staykaro)
# ============================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/staykaro}"
BRANCH="${DEPLOY_BRANCH:-main}"
ENV_FILE="$APP_DIR/.env"
COMPOSE_BASE="$APP_DIR/docker-compose.yml"
COMPOSE_PROD="$APP_DIR/docker-compose.prod.yml"
COMPOSE_CMD="docker compose -f $COMPOSE_BASE -f $COMPOSE_PROD --profile all --env-file $ENV_FILE"

log()    { echo -e "\033[36m[$(date '+%H:%M:%S')]\033[0m $*"; }
ok()     { echo -e "\033[32m[OK]\033[0m $*"; }
error()  { echo -e "\033[31m[ERROR]\033[0m $*" >&2; exit 1; }
warn()   { echo -e "\033[33m[WARN]\033[0m $*"; }

# ── Preconditions ────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || error "Docker not found. Run scripts/setup-vps.sh first."
command -v git    >/dev/null 2>&1 || error "git not found."

[ -f "$ENV_FILE" ] || error ".env not found at $ENV_FILE. Copy .env.production.example and fill in values."

# ── 1. Pull or clone ─────────────────────────────────────────
log "Syncing code (branch: $BRANCH)..."
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" fetch --quiet origin
    git -C "$APP_DIR" checkout "$BRANCH"
    git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
    ok "Code updated to $(git -C "$APP_DIR" rev-parse --short HEAD)."
else
    [ -n "${REPO_URL:-}" ] || error "REPO_URL must be set for initial clone. Example: REPO_URL=https://github.com/org/repo bash deploy.sh"
    log "Cloning $REPO_URL → $APP_DIR..."
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
    ok "Repository cloned."
fi

# ── 2. Build images ──────────────────────────────────────────
log "Building Docker images..."
$COMPOSE_CMD build --parallel
ok "Images built."

# ── 3. Apply migrations (placeholder — enable when alembic is wired) ─────────
# log "Running database migrations..."
# $COMPOSE_CMD run --rm api alembic upgrade head
# ok "Migrations applied."

# ── 4. Restart services ──────────────────────────────────────
log "Starting services..."
$COMPOSE_CMD up -d --remove-orphans
ok "Services started."

# ── 5. Health checks ─────────────────────────────────────────
log "Waiting for services to become healthy (30s)..."
sleep 30

PASS=true

check() {
    local name="$1" url="$2"
    if curl -fsS --max-time 5 "$url" > /dev/null 2>&1; then
        ok "  $name → $url"
    else
        warn "  FAIL: $name → $url"
        PASS=false
    fi
}

check "Nginx gateway"       "http://localhost:80/"
check "API health"          "http://localhost:8000/health"
check "Integration Service" "http://localhost:8002/health"
check "Voice Gateway"       "http://localhost:9000/health"

if [ "$PASS" = false ]; then
    warn "One or more health checks failed."
    warn "Check logs: docker compose -f $COMPOSE_BASE -f $COMPOSE_PROD logs --tail=50"
    exit 1
fi

# ── 6. Summary ───────────────────────────────────────────────
echo ""
echo "============================================================"
ok "Deploy complete."
echo ""
echo "  Commit  : $(git -C "$APP_DIR" rev-parse --short HEAD)"
echo "  Branch  : $BRANCH"
echo "  Time    : $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo ""
echo "  Endpoints:"
echo "    http://<your-vps-ip>/          → Nginx gateway"
echo "    http://<your-vps-ip>/api/      → API (proxied)"
echo ""
echo "  Logs:"
echo "    make prod-logs"
echo "    docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f"
echo "============================================================"
