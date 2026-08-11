# SearXNG image for hosting Odysseus on Render.
#
# The stock SearXNG image does not enable the `json` output format that Odysseus
# depends on, and on Render we can't bind-mount the repo's config file the way
# docker-compose.yml does. So bake Odysseus's settings.yml into the image and
# render it (with a per-deploy secret) at boot via the entrypoint below.
#
# Pinned deliberately (not :latest): Odysseus waits on SearXNG's health, so a
# broken upstream tag would block the whole app. 2026.6.2 crashes on boot
# (KeyError: 'default_doi_resolver'). Bump only after verifying a newer tag boots.
FROM docker.io/searxng/searxng:2026.5.31-7159b8aed

COPY config/searxng/settings.yml /usr/local/share/searxng-settings.yml.template
COPY docker/searxng-render-entrypoint.sh /usr/local/bin/searxng-render-entrypoint.sh
RUN chmod +x /usr/local/bin/searxng-render-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/searxng-render-entrypoint.sh"]
