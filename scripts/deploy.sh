#!/usr/bin/env bash
set -Eeuo pipefail

# ==== CONFIG (your paths) ====
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
BRANCH="${BRANCH:-main}"
LOCKFILE="${REPO_DIR}/.deploy.lock"
LOGFILE="${LOGFILE:-${REPO_DIR}/deploy.log}"

# docker compose lives in the repo root
COMPOSE_DIR="${REPO_DIR}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.dev.yaml}"

# Make sure cron can find common binaries
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# ==== SCRIPT (non-overlapping thanks to flock) ====
(
  flock -n 9 || exit 0

  cd "${REPO_DIR}"

  # Ensure the local branch exists and is checked out
  if ! git rev-parse --verify "${BRANCH}" >/dev/null 2>&1; then
    git fetch -q origin "${BRANCH}"
    git checkout -q -b "${BRANCH}" "origin/${BRANCH}"
  else
    git checkout -q "${BRANCH}"
  fi

  # Check if origin/main has moved
  git fetch -q origin "${BRANCH}"
  LOCAL="$(git rev-parse HEAD)"
  REMOTE="$(git rev-parse "origin/${BRANCH}")"

  if [[ "${LOCAL}" == "${REMOTE}" ]]; then
    # No changes
    echo "$(date -Is) no changes detected (still @ ${LOCAL:0:7})" | tee -a "${LOGFILE}"
    exit 0
  fi

  echo "$(date -Is) changes detected: ${LOCAL:0:7} -> ${REMOTE:0:7}" | tee -a "${LOGFILE}"

  # Fast-forward only (avoid accidental merges)
  git pull --ff-only -q origin "${BRANCH}"

  # Rebuild/restart
  pushd "${COMPOSE_DIR}" >/dev/null

  # Optional: pull updated images referenced by tags
  docker compose -f "${COMPOSE_FILE}" pull || true
  docker compose -f "${COMPOSE_FILE}" up --build -d

  popd >/dev/null

  echo "$(date -Is) deploy complete @ $(git rev-parse --short HEAD)" | tee -a "${LOGFILE}"
) 9>"${LOCKFILE}"

