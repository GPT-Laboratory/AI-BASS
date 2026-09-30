#!/usr/bin/env bash
set -Eeuo pipefail

# ==== CONFIG ====
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/mongodb}"
RETENTION_DAYS=14
LOGFILE="${LOGFILE:-${BACKUP_DIR}/backup.log}"
mkdir -p "$(dirname "$LOGFILE")"

# Make sure cron can find common binaries
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# ==== LOGGING ====
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOGFILE}"
}

# ==== CLEANUP ====
log "Starting cleanup of old backups (older than ${RETENTION_DAYS} days)..."

# Check if backup directory exists
if [ ! -d "${BACKUP_DIR}" ]; then
  log "WARNING: Backup directory ${BACKUP_DIR} does not exist. Nothing to clean up."
  exit 0
fi

# Count backups before cleanup
BEFORE_COUNT=$(find "${BACKUP_DIR}" -name "mongodb_backup_*.archive" -type f 2>/dev/null | wc -l)

# Find and delete backups older than retention period
DELETED_FILES=$(find "${BACKUP_DIR}" \
  -name "mongodb_backup_*.archive" \
  -type f \
  -mtime +${RETENTION_DAYS} \
  -print -delete 2>/dev/null)

# Count how many files were deleted
DELETED_COUNT=$(echo "${DELETED_FILES}" | grep -c "mongodb_backup_" || true)

if [ "${DELETED_COUNT}" -gt 0 ]; then
  log "SUCCESS: Deleted ${DELETED_COUNT} old backup(s):"
  echo "${DELETED_FILES}" | while read -r file; do
    if [ -n "$file" ]; then
      log "  - $(basename "$file")"
    fi
  done
else
  log "INFO: No backups older than ${RETENTION_DAYS} days found. Total backups: ${BEFORE_COUNT}"
fi

# Count backups after cleanup
AFTER_COUNT=$(find "${BACKUP_DIR}" -name "mongodb_backup_*.archive" -type f 2>/dev/null | wc -l)
log "Cleanup complete. Remaining backups: ${AFTER_COUNT}"

exit 0
