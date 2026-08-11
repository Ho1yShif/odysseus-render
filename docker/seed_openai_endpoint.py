#!/usr/bin/env python3
"""Seed an OpenAI model endpoint on first boot of the hosted Render image.

Setting ``OPENAI_API_KEY`` alone does NOT make chat work: the chat send path
resolves the default model from the ``model_endpoints`` DB table (see
``routes/model_routes.py::get_default_chat``), which is empty on a fresh deploy.
With no endpoint, the composer shows "No chat session active" even though the key
is set. This registers an OpenAI endpoint from ``OPENAI_API_KEY`` and marks it the
global default so "open Chat, send a message, get a reply" works out of the box.

Runs in the entrypoint before the app boots, in a separate process. It shares the
app's Fernet key (a file under the persistent-disk data dir, see
``src.secret_storage``), so ``api_key`` is encrypted at rest exactly as the app
would encrypt it.

Idempotent and safe to run every boot:
- skips when ``OPENAI_API_KEY`` is unset,
- skips when an ``api.openai.com`` endpoint already exists (the DB lives on the
  persistent disk and survives redeploys), so it never duplicates or clobbers an
  endpoint the admin later edits.

The default model is pinned (not discovered via ``/v1/models``) so chat works even
when the key is restricted to ``/v1/chat/completions`` — the probe would 403 and
return no models otherwise. Override the pinned model with ``OPENAI_DEFAULT_MODEL``.
"""

import json
import logging
import os
import sys
import uuid
from pathlib import Path

# Run standalone from the entrypoint (python /app/docker/seed_openai_endpoint.py):
# Python puts this file's dir (docker/) on sys.path, not the repo root, so the
# core/ and src/ packages wouldn't import. Add the repo root (this file's parent
# dir's parent) explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("seed_openai_endpoint")

DEFAULT_MODEL = "gpt-5.6-sol"


def main() -> int:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        log.info("[seed] OPENAI_API_KEY not set — skipping OpenAI endpoint seed.")
        return 0

    # Imported lazily (after the key check) so a keyless deploy pays no import cost.
    from core.database import ModelEndpoint, SessionLocal, init_db
    from src.settings import load_settings, save_settings

    # Tables + migrations are idempotent; the app re-runs init_db() at startup.
    init_db()

    model = (os.getenv("OPENAI_DEFAULT_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL

    db = SessionLocal()
    try:
        existing = (
            db.query(ModelEndpoint)
            .filter(ModelEndpoint.base_url.like("%api.openai.com%"))
            .first()
        )
        if existing is not None:
            log.info("[seed] OpenAI endpoint already present (%s) — nothing to do.", existing.id)
            return 0

        ep_id = str(uuid.uuid4())[:8]
        ep = ModelEndpoint(
            id=ep_id,
            name="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key=api_key,  # EncryptedText encrypts at rest via the shared app key
            is_enabled=True,
            model_type="llm",
            endpoint_kind="api",
            # Pin (and cache) the default model so the picker + composer work even
            # when the key can't list /v1/models. A key with Models-read permission
            # still gets the full list via the app's background refresh.
            pinned_models=json.dumps([model]),
            cached_models=json.dumps([model]),
            owner=None,  # shared: visible to the admin and any additional users
        )
        db.add(ep)
        db.commit()

        settings = load_settings()
        settings["default_endpoint_id"] = ep_id
        settings["default_model"] = model
        save_settings(settings)

        log.info("[seed] Seeded OpenAI endpoint %s (default model %r).", ep_id, model)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
