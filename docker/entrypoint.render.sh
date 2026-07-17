#!/bin/sh
# Entrypoint for the hosted Render image (Dockerfile.render).
#
# On Render there is no bind-mounted host volume (the persistent disk at
# /app/data is managed and already writable), so the PUID/PGID ownership-repair
# dance in docker/entrypoint.sh is unnecessary here — we run as root and bind
# the port Render injects via $PORT.
set -e

# First-time setup is idempotent (creates auth.json/.env only if missing).
# || true so a setup hiccup never blocks the container from starting.
python /app/setup.py || true

exec uvicorn app:app --host 0.0.0.0 --port "${PORT:-7000}"
