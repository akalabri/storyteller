#!/bin/bash
# Run this on the remote server (akaecho97@34.171.54.149) in ~/storyteller
# after minio-data-snapshot.tar.gz has been fully copied.

set -e
cd ~/storyteller

echo "Stopping minio and dependent services..."
docker compose stop minio backend frontend 2>/dev/null || true

echo "Backing up existing minio-data (if any)..."
[ -d minio-data ] && mv minio-data "minio-data.bak.$(date +%s)" || true

echo "Extracting snapshot..."
tar xzvf minio-data-snapshot.tar.gz

echo "Starting services..."
docker compose up -d

echo "Done. Minio volume replaced with snapshot from local storyteller."
