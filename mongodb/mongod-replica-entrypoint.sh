#!/bin/sh
set -eu

# Start MongoDB in the background
echo "Starting MongoDB..."
mongod --config /etc/mongod.conf &
MONGOD_PID=$!

# Wait for MongoDB to be ready
echo "Waiting for MongoDB to be ready..."
until mongosh --host mongo:27017 --eval "db.adminCommand('ping')" >/dev/null 2>&1; do
    echo "MongoDB is not ready yet, waiting..."
    sleep 2
done

echo "MongoDB is ready, initializing replica set..."

# Initialize replica set
mongosh --host mongo:27017 /init-replica-set.js

echo "Replica set initialization completed"

# Setup mongot user and database
echo "Setting up mongot user and database..."
mongosh --host mongo:27017 /setup-mongot-user.js

echo "Mongot user setup completed"

echo "MongoDB initialization complete"

# Wait for the mongod process to finish
wait $MONGOD_PID
