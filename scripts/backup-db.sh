#!/usr/bin/env bash
# ============================================================
# Staykaro AI Caller — Database Backup
# NK-17: Daily full base backup, on top of the continuous WAL archive
# docker-compose.yml's postgres.command already enables (archive_mode=on,
# archive_command → /backups/wal_archive). Together these give point-in-time
# recovery (Database Design §10), not just a daily snapshot — a base backup
# alone can only restore to the moment it was taken.
#
# Usage:
#   bash scripts/backup-db.sh                 ← full base backup + prune
#   RETENTION_DAYS=7 bash scripts/backup-db.sh ← shorter retention
#
# Run this on a schedule (cron/systemd timer on the VPS — see
# infrastructure/README or crontab -e):
#   0 2 * * * cd /opt/staykaro && bash scripts/backup-db.sh >> /var/log/staykaro-backup.log 2>&1
#
# What this does NOT do: sync backups off the VPS. Database Design §10 calls
# for backups "stored separately from the production VPS" — losing the VPS
# entirely must not also lose the backups sitting on its own disk. That sync
# (rsync/rclone/S3, whichever this deployment picks) is an operator step with
# its own credentials; wire it in after this script, don't build it into it.
# ============================================================
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"
CONTAINER="${POSTGRES_CONTAINER:-staykaro-postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
TIMESTAMP="$(date -u '+%Y%m%d-%H%M%S')"

log()   { echo -e "\033[36m[$(date '+%H:%M:%S')]\033[0m $*"; }
ok()    { echo -e "\033[32m[OK]\033[0m $*"; }
error() { echo -e "\033[31m[ERROR]\033[0m $*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || error ".env not found at $ENV_FILE"
# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a
POSTGRES_USER="${POSTGRES_USER:-staykaro_user}"
POSTGRES_DB="${POSTGRES_DB:-staykaro}"
[ -n "${POSTGRES_PASSWORD:-}" ] || error "POSTGRES_PASSWORD not set in $ENV_FILE"

docker inspect "$CONTAINER" > /dev/null 2>&1 || error "Container $CONTAINER is not running — start the stack first."

log "Starting base backup $TIMESTAMP (retention: ${RETENTION_DAYS}d)..."
docker exec "$CONTAINER" mkdir -p "/backups/base/$TIMESTAMP" "/backups/wal_archive"

# -Ft: tar format (one file per tablespace, easiest to move/verify as a unit)
# -z: gzip compressed
# -Xs: stream WAL alongside the backup, so the base backup is self-contained
#      even if the continuous archive_command's segments are pruned before a
#      restore reads this specific backup's start/end LSN range.
# -c fast: don't wait for the next scheduled checkpoint — this is an
#      operational backup, not free background maintenance.
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTAINER" \
  pg_basebackup \
    -h 127.0.0.1 \
    -U "$POSTGRES_USER" \
    -D "/backups/base/$TIMESTAMP" \
    -Ft -z -Xs -c fast -P \
  || error "pg_basebackup failed — see output above. No partial backup left in place (pg_basebackup cleans up on failure)."

ok "Base backup written to $CONTAINER:/backups/base/$TIMESTAMP"

# pg_verifybackup (PG13+) checks the backup's own checksums and manifest —
# catches a corrupted backup at backup time, not months later during an
# actual disaster.
if docker exec "$CONTAINER" sh -c 'command -v pg_verifybackup' > /dev/null 2>&1; then
  log "Verifying backup integrity..."
  # pg_verifybackup expects the plain (non-tar) directory layout with a
  # backup_manifest at the top level — tar format's manifest lives inside
  # base.tar.gz, so verify against a temporary extraction instead of the
  # tar output directly.
  docker exec "$CONTAINER" sh -c "
    set -e
    mkdir -p /tmp/verify-$TIMESTAMP/pg_wal
    tar -xzf /backups/base/$TIMESTAMP/base.tar.gz -C /tmp/verify-$TIMESTAMP
    tar -xzf /backups/base/$TIMESTAMP/pg_wal.tar.gz -C /tmp/verify-$TIMESTAMP/pg_wal
    cp /backups/base/$TIMESTAMP/backup_manifest /tmp/verify-$TIMESTAMP/backup_manifest
    pg_verifybackup /tmp/verify-$TIMESTAMP
    rm -rf /tmp/verify-$TIMESTAMP
  " || error "Backup verification FAILED for $TIMESTAMP — treat this backup as unusable."
  ok "Backup integrity verified."
else
  log "pg_verifybackup not available in this image — skipping integrity check (backup still written)."
fi

# ── Retention: prune base backups and WAL segments older than N days ───────
log "Pruning backups older than ${RETENTION_DAYS}d..."
docker exec "$CONTAINER" find /backups/base -mindepth 1 -maxdepth 1 -type d -mtime "+$RETENTION_DAYS" -print -exec rm -rf {} \;
docker exec "$CONTAINER" find /backups/wal_archive -type f -mtime "+$RETENTION_DAYS" -print -delete

ok "Backup $TIMESTAMP complete."
echo "$TIMESTAMP"
