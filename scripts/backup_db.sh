#!/usr/bin/env bash
set -Eeuo pipefail

# ==== CONFIG ====
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/mongodb}"
CONTAINER_NAME="company-mongo"
DB_NAME="companydb"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="mongodb_backup_${TIMESTAMP}.archive"
LOGFILE="${LOGFILE:-${BACKUP_DIR}/backup.log}"
mkdir -p "$(dirname "$LOGFILE")"

# Ensure backup directory exists
mkdir -p "${BACKUP_DIR}"

# Make sure cron can find common binaries
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# ==== LOGGING ====
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOGFILE}"
}

# ==== BACKUP ====
log "Starting MongoDB backup..."

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  log "ERROR: Container ${CONTAINER_NAME} is not running!"
  exit 1
fi

# Perform the backup using mongodump inside the container
if docker exec "${CONTAINER_NAME}" mongodump \
  --db="${DB_NAME}" \
  --archive="/tmp/${BACKUP_FILE}" \
  --gzip; then

  # Copy the backup from container to host
  if docker cp "${CONTAINER_NAME}:/tmp/${BACKUP_FILE}" "${BACKUP_DIR}/${BACKUP_FILE}"; then
    # Remove the temporary backup file from container
    docker exec "${CONTAINER_NAME}" rm -f "/tmp/${BACKUP_FILE}"

    # Get backup file size
    BACKUP_SIZE=$(du -h "${BACKUP_DIR}/${BACKUP_FILE}" | cut -f1)

    log "SUCCESS: Backup completed - ${BACKUP_FILE} (${BACKUP_SIZE})"
    exit 0
  else
    log "ERROR: Failed to copy backup from container to host"
    exit 1
  fi
else
  log "ERROR: mongodump failed"
  exit 1
fi
