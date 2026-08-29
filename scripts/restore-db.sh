#!/usr/bin/env bash
# ============================================================
# Staykaro AI Caller — Database Restore (and restore TEST)
# NK-17: "Actual restore passes" — Database Design §10 is explicit that a
# backup nobody has ever restored doesn't count as a backup. This script is
# both the disaster-recovery procedure AND the thing that proves it works:
# it always restores into a brand-new, disposable scratch container — never
# the running staykaro-postgres — so running it is safe at any time,
# including as a recurring scheduled drill, not just during a real incident.
#
# Usage:
#   bash scripts/restore-db.sh                        ← restore latest base backup
#   bash scripts/restore-db.sh 20260829-020000         ← restore a specific backup
#   bash scripts/restore-db.sh latest --to "2026-08-29 02:15:00+00"
#                                                       ← point-in-time recovery
#                                                         via the WAL archive
#   bash scripts/restore-db.sh latest --keep           ← leave the scratch
#                                                         container running
#                                                         afterward for manual
#                                                         inspection
#
# To actually promote a scratch restore into production (a real disaster,
# not a drill): stop the app services, `docker volume rm staykaro_postgres_data`,
# rename/repoint the scratch container's volume to `staykaro_postgres_data`,
# then start the stack normally. That step is deliberately manual, not
# scripted — it's the one irreversible action in this whole file.
# ============================================================
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"
SOURCE_CONTAINER="${POSTGRES_CONTAINER:-staykaro-postgres}"
BACKUP_TARGET="${1:-latest}"
SCRATCH_NAME="staykaro-postgres-restore-test"
SCRATCH_VOLUME="staykaro_postgres_restore_test"
RECOVERY_TARGET_TIME=""
KEEP=0

shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --to) RECOVERY_TARGET_TIME="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

log()   { echo -e "\033[36m[$(date '+%H:%M:%S')]\033[0m $*"; }
ok()    { echo -e "\033[32m[OK]\033[0m $*"; }
error() { echo -e "\033[31m[ERROR]\033[0m $*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || error ".env not found at $ENV_FILE"
# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD not set in $ENV_FILE}"

docker inspect "$SOURCE_CONTAINER" > /dev/null 2>&1 || error "Container $SOURCE_CONTAINER is not running — needed to read the backup volume."

cleanup() {
  if [ "$KEEP" -eq 0 ]; then
    log "Tearing down scratch restore container..."
    docker rm -f "$SCRATCH_NAME" > /dev/null 2>&1 || true
    docker volume rm "$SCRATCH_VOLUME" > /dev/null 2>&1 || true
  else
    log "Leaving $SCRATCH_NAME running (--keep). Remove it manually with:"
    log "  docker rm -f $SCRATCH_NAME && docker volume rm $SCRATCH_VOLUME"
  fi
}
trap cleanup EXIT

# ── Resolve which base backup to restore ────────────────────────────────────
if [ "$BACKUP_TARGET" = "latest" ]; then
  BACKUP_TARGET=$(docker exec "$SOURCE_CONTAINER" sh -c 'ls -1 /backups/base 2>/dev/null | sort | tail -n1')
  [ -n "$BACKUP_TARGET" ] || error "No base backups found under /backups/base — run scripts/backup-db.sh first."
fi
docker exec "$SOURCE_CONTAINER" test -f "/backups/base/$BACKUP_TARGET/base.tar.gz" \
  || error "No backup found at /backups/base/$BACKUP_TARGET/base.tar.gz"

log "Restoring backup: $BACKUP_TARGET${RECOVERY_TARGET_TIME:+ (point-in-time target: $RECOVERY_TARGET_TIME)}"

# ── Bring up a fresh, disposable Postgres container from that base backup ──
docker volume rm "$SCRATCH_VOLUME" > /dev/null 2>&1 || true
docker volume create "$SCRATCH_VOLUME" > /dev/null

# Same image as the real service (docker-compose.yml) — a restore tested
# against a different Postgres major version proves nothing about the real
# recovery path.
IMAGE=$(docker inspect -f '{{.Config.Image}}' "$SOURCE_CONTAINER")
POSTGRES_BACKUPS_VOLUME=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/backups"}}{{.Name}}{{end}}{{end}}' "$SOURCE_CONTAINER")
[ -n "$POSTGRES_BACKUPS_VOLUME" ] || error "Could not find the postgres_backups volume mounted on $SOURCE_CONTAINER."

log "Extracting base backup into scratch volume..."
docker run --rm \
  -v "$SCRATCH_VOLUME:/var/lib/postgresql/data" \
  -v "$POSTGRES_BACKUPS_VOLUME:/backups:ro" \
  "$IMAGE" \
  bash -c "
    set -e
    tar -xzf /backups/base/$BACKUP_TARGET/base.tar.gz -C /var/lib/postgresql/data
    chmod 700 /var/lib/postgresql/data
    chown -R postgres:postgres /var/lib/postgresql/data
  "

# ── Configure archive recovery ──────────────────────────────────────────────
# recovery.signal (not standby.signal) — this is a one-shot restore to a
# normal read-write primary, not a hot standby replica.
#
# Passed in as env vars rather than interpolated into the inner script
# string: this settings *value* itself contains single quotes (the
# recovery_target_time timestamp) and %-placeholders (restore_command's %f
# %p) — string-building the inner bash -c source by substituting $RECOVERY_CONF
# into an outer double-quoted string mangles those quotes/percents before the
# container's own shell ever sees them (confirmed by hand: the previous
# version of this script silently wrote `restore_command = cp`, with %f/%p
# and the surrounding quotes stripped out entirely by the outer shell's own
# word-splitting). Env vars cross that boundary as opaque values, no
# re-quoting involved.
docker run --rm \
  -e RESTORE_TARGET_TIME="$RECOVERY_TARGET_TIME" \
  -v "$SCRATCH_VOLUME:/var/lib/postgresql/data" \
  "$IMAGE" \
  bash -c '
    set -e
    touch /var/lib/postgresql/data/recovery.signal
    {
      echo "restore_command = '"'"'cp /backups/wal_archive/%f %p'"'"'"
      if [ -n "$RESTORE_TARGET_TIME" ]; then
        echo "recovery_target_time = '"'"'$RESTORE_TARGET_TIME'"'"'"
        echo "recovery_target_action = '"'"'promote'"'"'"
      fi
    } >> /var/lib/postgresql/data/postgresql.auto.conf
    chown postgres:postgres /var/lib/postgresql/data/recovery.signal /var/lib/postgresql/data/postgresql.auto.conf
  '

# ── Start the scratch container and wait for recovery to complete ─────────
# No published port — this is verified over `docker exec`, never exposed.
docker run -d \
  --name "$SCRATCH_NAME" \
  -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  -v "$SCRATCH_VOLUME:/var/lib/postgresql/data" \
  -v "$POSTGRES_BACKUPS_VOLUME:/backups:ro" \
  "$IMAGE" > /dev/null

log "Waiting for archive recovery to complete (this replays WAL — can take a while)..."
ATTEMPTS=0
until docker exec "$SCRATCH_NAME" pg_isready -U "${POSTGRES_USER:-staykaro_user}" > /dev/null 2>&1; do
  ATTEMPTS=$((ATTEMPTS + 1))
  if [ "$ATTEMPTS" -ge 60 ]; then
    log "Recovery log tail:"
    docker logs --tail 40 "$SCRATCH_NAME" || true
    error "Timed out waiting for recovery to complete after ${ATTEMPTS}0s."
  fi
  sleep 10
done
ok "Recovery complete — restored database is accepting connections."

# ── Data-integrity verification ─────────────────────────────────────────────
# Not a full application-level check — a fast, concrete signal that the
# restored cluster is queryable and actually holds the tables/rows this
# system depends on, not an empty or partially-recovered database.
log "Verifying restored data..."
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$SCRATCH_NAME" \
  psql -U "${POSTGRES_USER:-staykaro_user}" -d "${POSTGRES_DB:-staykaro}" -c "
    SELECT 'clients' AS table_name, count(*) FROM clients
    UNION ALL SELECT 'admin_users', count(*) FROM admin_users
    UNION ALL SELECT 'call_requests', count(*) FROM call_requests
    UNION ALL SELECT 'audit_logs', count(*) FROM audit_logs;
  " || error "Restored database did not respond to a basic verification query."

ok "Restore of backup $BACKUP_TARGET verified successfully."
