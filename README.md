<p align="center">
  <img src="docs/odysseus-wordmark.png" alt="Odysseus" width="238">
</p>

# Odysseus on Render

Deploy **Odysseus** on Render in one click. Get a self-hosted AI workspace — chat, agents, deep research, documents, email, notes, and calendar — running on your own instance with your own API keys.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Ho1yShif/odysseus)

<p align="center">
  <img src="docs/odysseus-browser.jpg" alt="Odysseus interface">
</p>

## What you get

This Blueprint provisions three services on Render:

| Service | What it is |
|---------|------------|
| `odysseus` | The web app (chat, agents, research, documents, email, notes, calendar). Persistent disk at `/app/data`. |
| `odysseus-searxng` | Bundled [SearXNG](https://github.com/searxng/searxng) for private web search — powers Deep Research with no extra key. |
| `odysseus-chromadb` | Bundled [ChromaDB](https://www.trychroma.com/) vector store for RAG and semantic memory. |

Auth is on by default (`AUTH_ENABLED=true`, secure cookies, a generated admin password), and both helper services are private — only the web app is exposed.

> This is the **hosted** build. Local-model serving (Cookbook/vLLM/llama.cpp), GPU inference, image upscaling, and host-Docker features from the [upstream project](https://github.com/odysseus-dev/odysseus) don't run on Render and are omitted here; Odysseus uses cloud LLM APIs instead. For the full self-hosted feature set, see the [upstream repo](https://github.com/odysseus-dev/odysseus).

## Deploy

1. Click **Deploy to Render** above.
2. Fill in the API keys you want (see below) in the deploy form, then apply the Blueprint.
3. Wait for all three services to go live.

### Environment variables

Set these as secrets in the deploy form. All are optional per feature — you only need the keys for the features you'll use.

To restrict `OPENAI_API_KEY`, a key with only the **Chat completions** (`/v1/chat/completions`) permission is enough — embeddings run locally (fastembed) and no other OpenAI endpoint is used. Set everything else to **None**.

| Variable | Needed for | Where to get it |
|----------|-----------|-----------------|
| `OPENAI_API_KEY` | Chat, agents, research (LLM calls) | [platform.openai.com](https://platform.openai.com/api-keys) |
| `OPENAI_DEFAULT_MODEL` | Model seeded as the default chat on first boot (default `gpt-5.6-sol`; change here or in the app) — not a secret | — |
| `DATA_BRAVE_API_KEY` | Brave web search (optional — SearXNG is bundled) | [brave.com/search/api](https://brave.com/search/api/) |
| `TAVILY_API_KEY` | Tavily search provider (optional) | [tavily.com](https://tavily.com/) |
| `SERPER_API_KEY` | Serper search provider (optional) | [serper.dev](https://serper.dev/) |
| `GOOGLE_API_KEY` + `GOOGLE_PSE_CX` | Google Programmable Search (optional) | [Google Cloud](https://developers.google.com/custom-search) |
| `HF_TOKEN` | Gated Hugging Face models (optional) | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |

Set automatically — no action needed: `ODYSSEUS_ADMIN_PASSWORD` (generated), `SEARXNG_SECRET` (generated), plus the internal service wiring.

**Advanced — `ALLOWED_ORIGINS` (CORS):** by default the app locks CORS to its own Render URL (it reads `RENDER_EXTERNAL_URL` automatically), so you don't need to set anything. Only set `ALLOWED_ORIGINS` if you serve the app from a **custom domain** or need to allow **additional origins** — provide a comma-separated list of the full origins (e.g. `https://app.example.com,https://www.example.com`).

### Using the app

1. Open the `odysseus` service URL once it's live.
2. Log in as **`admin`**. Your admin password is **created for you automatically** at deploy time — you don't set one. Find it in the Render Dashboard → the `odysseus` service → **Environment** → `ODYSSEUS_ADMIN_PASSWORD` (a strong, randomly generated 256-bit value). Copy it to log in, then change it from the app after first login. It's never printed to the logs.
3. Open **Chat** and send a message — with `OPENAI_API_KEY` set, you'll get a reply. On first boot the deploy auto-configures an OpenAI endpoint (default model `OPENAI_DEFAULT_MODEL`), so there's nothing to wire up in the model picker.
4. Open **Deep Research**, enter a question, and run it. It searches the web through the bundled SearXNG (no extra key) and generates a sourced report — a good end-to-end showcase of the deploy.

> Want to let strangers try the app without an admin password? See **[Demo mode](#demo-mode)** below — a public, no-signup chat surface you can turn on with `DEMO=true`. It's **off by default**, so a fresh deploy stays fully authenticated.

## Demo mode

`DEMO=true` runs a **public, no-signup, locked-down chat demo** on **your** OpenAI key — so anyone with the URL can try the chat without logging in. It is **off by default** (`DEMO=false`): a fresh fork or deploy gets the full authenticated app, unchanged. Only a deliberate `DEMO=true` turns it on.

**How it works.** With the flag on, the login gate opens *for chat only*. Each visitor gets an isolated, ephemeral demo session (an unguessable per-visitor cookie → a synthetic owner) under a least-privilege profile. Everything else — settings, admin, integrations, and every other API route — still requires the admin login exactly as before. The admin account and its password are untouched.

**What the demo can and can't do:**

| Capability | In demo |
|---|---|
| Chat (pinned cheap model, capped output) | ✅ on |
| Shell / code / file tools | ❌ off |
| File upload & personal-doc RAG | ❌ off |
| Image generation, TTS / STT | ❌ off |
| Deep research | ❌ off (expensive per run) |
| Email, MCP servers, cookbook, task scheduler | ❌ off |
| Memory writes, API-token minting | ❌ off |
| Settings / admin / integrations | ❌ off (admin login still required) |

**Abuse & cost limits** (demo-only; the demo spends **your** key, so watch your [OpenAI usage console](https://platform.openai.com/usage)):

| Variable | Default | What it caps |
|---|---|---|
| `DEMO_MODEL` | `gpt-5.6-luna` | the pinned (cheap) chat model |
| `DEMO_MAX_OUTPUT_TOKENS` | `512` | output tokens per reply |
| `DEMO_RATE_LIMIT_PER_MINUTE` | `10` | chat sends per minute, per client IP |
| `DEMO_MAX_MESSAGES_PER_SESSION` | `30` | total messages per visitor cookie session (UX friction) |
| `DEMO_MAX_MESSAGES_PER_IP_PER_DAY` | `200` | hard per-IP daily message ceiling (the real backstop) |

Raise or lower these in the deploy form / `render.yaml`. Set a limit to `0` to disable that one dimension; an unset variable falls back to the default (it **never** means "unlimited"). When a visitor hits a cap they get a friendly "deploy your own to keep going" reply — never an error.

The rate limit and the per-IP daily ceiling are keyed on the **trusted client IP** — the entry Render's proxy attests on `X-Forwarded-For`, read from the right (`TRUSTED_PROXY_HOPS` hops in, default `1`), never the spoofable leftmost value. So clearing cookies or churning the demo session **can't** reset them. The per-session cap is cookie-based, so it's UX friction only; the per-IP ceiling is the volume backstop. Visitors behind one NAT/IP share a bucket — that errs toward more limiting, which is what you want for a cost guard.

> `TRUSTED_PROXY_HOPS` is app-wide, not demo-only: the auth login/signup/setup rate limiters key on the same trusted IP. On first traffic the app logs a one-time `[trusted-ip] X-Forwarded-For sample` line — check it once on your deploy to confirm `1` hop resolves your real client IP (retune if you front the service with extra proxies).
>
> **Deploying off Render?** Set `TRUSTED_PROXY_HOPS` to match your topology: `0` if the service is directly internet-facing with **no** proxy in front (the whole `X-Forwarded-For` header is then attacker-supplied, so it's ignored and the limiters key on the real TCP peer), or `N` for `N` trusted proxies. Leaving the default `1` on a proxy-less deploy lets a client spoof `X-Forwarded-For` and bypass every IP-keyed limit.

> **Your real spend ceiling is the OpenAI limit, not these counters.** The caps above bound the burn *rate*; they reduce how fast the key can be spent, they don't cap total dollars. The one true per-call ceiling is `DEMO_MAX_OUTPUT_TOKENS`. For a hard dollar cap, set a [monthly usage limit on your OpenAI project](https://platform.openai.com/settings/organization/limits) — that's what protects the bill if the demo URL is discovered or abused.

**Session isolation & privacy.** Visitors can't see each other's chats (each is scoped to its own synthetic owner), and demo history is **ephemeral** — it lives in memory only and is never written to the deployer's disk. If you host a public demo URL, add a visible "public demo, may reset — don't submit anything sensitive" notice.

### Scaling for heavy workloads

The Blueprint defaults the web service to `standard` (2 GB). Odysseus can be resource-hungry under heavy use — large deep-research runs, big documents, sizable embedding jobs, or many concurrent sessions. For those workloads, give the instance more resources: in the Render Dashboard, open the `odysseus` service → **Settings → Instance Type** and pick a larger plan (and bump `odysseus-chromadb` too if your vector store grows). You can downgrade later if the smaller plan proves sufficient.

## Learn more

Full documentation, the complete self-hosted feature set, and contributing guidelines live in the upstream project: [odysseus-dev/odysseus](https://github.com/odysseus-dev/odysseus).

## License

AGPL-3.0-or-later — see [LICENSE](LICENSE) and [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md).
