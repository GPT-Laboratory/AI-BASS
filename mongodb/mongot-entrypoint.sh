#!/bin/sh
set -eu
: "${MONGOT_PASSWORD:?MONGOT_PASSWORD is required}"
umask 077
printf '%s' "$MONGOT_PASSWORD" > /tmp/mongot-password

echo "Waiting for MongoDB to complete initialization..."
echo "Sleeping for 30 seconds to ensure MongoDB replica set and user setup is complete..."
sleep 30

echo "Starting mongot..."
exec /mongot-community/mongot --config /mongot-community/config.default.yml
