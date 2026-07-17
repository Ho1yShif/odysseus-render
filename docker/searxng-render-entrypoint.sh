#!/bin/sh
# Render entrypoint for the bundled SearXNG image.
#
# Odysseus requires SearXNG's `json` output format, which the stock image does
# not enable — so we ship config/searxng/settings.yml (baked in at build) and
# render it into place on boot, substituting the secret_key. Mirrors the wrapper
# in docker-compose.yml. Runs as root, writes /etc/searxng, then hands off to
# SearXNG's own entrypoint (which drops privileges).
set -eu

if [ ! -s /etc/searxng/settings.yml ] || grep -q '__SEARXNG_SECRET__' /etc/searxng/settings.yml; then
    secret="${SEARXNG_SECRET:-}"
    if [ -z "$secret" ]; then
        secret="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
    fi
    mkdir -p /etc/searxng
    sed "s|__SEARXNG_SECRET__|$secret|g" /tmp/searxng-settings.yml.template > /etc/searxng/settings.yml
fi

exec /usr/local/searxng/entrypoint.sh
