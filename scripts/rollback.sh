#!/usr/bin/env bash
# ============================================================
# Staykaro AI Caller — Rollback Script
# NH-05: Revert to a previous git commit on the VPS.
#
# Usage:
#   bash scripts/rollback.sh                 ← rolls back one commit
#   bash scripts/rollback.sh <commit-sha>    ← rolls back to specific SHA
# ============================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/staykaro}"
ENV_FILE="$APP_DIR/.env"
COMPOSE_BASE="$APP_DIR/docker-compose.yml"
COMPOSE_PROD="$APP_DIR/docker-compose.prod.yml"
COMPOSE_CMD="docker compose -f $COMPOSE_BASE -f $COMPOSE_PROD --profile all --env-file $ENV_FILE"
TARGET_SHA="${1:-}"

log()   { echo -e "\033[36m[$(date '+%H:%M:%S')]\033[0m $*"; }
ok()    { echo -e "\033[32m[OK]\033[0m $*"; }
error() { echo -e "\033[31m[ERROR]\033[0m $*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || error ".env not found at $ENV_FILE"
[ -d "$APP_DIR/.git" ] || error "No git repo at $APP_DIR. Cannot rollback."

CURRENT=$(git -C "$APP_DIR" rev-parse --short HEAD)
log "Current commit: $CURRENT"

if [ -z "$TARGET_SHA" ]; then
    TARGET_SHA=$(git -C "$APP_DIR" rev-parse --short HEAD~1)
    log "No target specified — rolling back to previous commit: $TARGET_SHA"
else
    log "Rolling back to: $TARGET_SHA"
fi

# ── Checkout target ──────────────────────────────────────────
git -C "$APP_DIR" checkout "$TARGET_SHA"
ok "Checked out $TARGET_SHA."

# ── Rebuild and restart ──────────────────────────────────────
log "Rebuilding images at $TARGET_SHA..."
$COMPOSE_CMD build --parallel

log "Restarting services..."
$COMPOSE_CMD up -d --remove-orphans
ok "Services restarted."

# ── Verify ───────────────────────────────────────────────────
sleep 10
if curl -fsS --max-time 5 "http://localhost:80/" > /dev/null 2>&1; then
    ok "Rollback complete. Running at: $TARGET_SHA (was: $CURRENT)"
else
    error "Health check failed after rollback. Manual intervention required."
fi
