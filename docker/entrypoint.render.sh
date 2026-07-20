#!/bin/sh
# Entrypoint for the hosted Render image (Dockerfile.render).
#
# On Render there is no bind-mounted host volume (the persistent disk at
# /app/data is managed and already writable), so the PUID/PGID ownership-repair
# dance in docker/entrypoint.sh is unnecessary here — we run as root and bind
# the port Render injects via $PORT.
set -eu

# First-time setup is idempotent (creates auth.json/.env only if missing).
# || true so a non-critical hiccup never blocks startup — matches entrypoint.sh.
python /app/setup.py || true

# Guard the one invariant a hosted deploy can't recover from on its own: with
# auth enabled, an admin account must exist. setup.py swallows its own admin
# errors and exits 0, so on failure the app would boot healthy (the "/" health
# check passes) yet nobody could ever log in. Assert it here so a seeding
# failure surfaces as a failed deploy instead. Reuses src.constants so the
# path tracks ODYSSEUS_DATA_DIR exactly like the app resolves it.
if [ "$(printf '%s' "${AUTH_ENABLED:-true}" | tr '[:upper:]' '[:lower:]')" != "false" ]; then
    python - <<'PY'
import json
import sys

from src.constants import AUTH_FILE

try:
    with open(AUTH_FILE, encoding="utf-8") as fh:
        users = json.load(fh).get("users", {})
except (OSError, ValueError) as exc:
    sys.exit(f"[fatal] admin auth not initialized ({AUTH_FILE}): {exc}")

if not users:
    sys.exit(f"[fatal] admin auth file {AUTH_FILE} has no users — seeding failed")
PY
fi

# Seed an OpenAI model endpoint from OPENAI_API_KEY on first boot so chat works
# out of the box — setting the key alone leaves the model_endpoints table empty,
# which surfaces as "No chat session active" in the composer. Idempotent (skips
# if the key is unset or an OpenAI endpoint already exists) and non-fatal: a seed
# hiccup must not block the deploy — the admin can always add the endpoint from
# the UI.
python /app/docker/seed_openai_endpoint.py || true

exec uvicorn app:app --host 0.0.0.0 --port "${PORT:-7000}"
