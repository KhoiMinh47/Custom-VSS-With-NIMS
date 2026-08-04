#!/bin/sh
set -eu

mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"

for bucket in vss-clips vss-snapshots vss-thumbnails vss-artifacts; do
  mc mb --ignore-existing "local/$bucket"
done

mc anonymous set none local/vss-clips
mc anonymous set none local/vss-snapshots
mc anonymous set none local/vss-thumbnails
mc anonymous set none local/vss-artifacts
mc ls local
