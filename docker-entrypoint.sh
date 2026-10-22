#!/bin/sh
set -eu
mkdir -p /data/home /data/known_faces
chown appuser:appuser /data /data/home /data/known_faces
exec gosu appuser "$@"
