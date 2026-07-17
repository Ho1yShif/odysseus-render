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

| Variable | Needed for | Where to get it |
|----------|-----------|-----------------|
| `OPENAI_API_KEY` | Chat, agents, research (LLM calls) | [platform.openai.com](https://platform.openai.com/api-keys) |
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
3. Open **Chat** and send a message — with `OPENAI_API_KEY` set, you'll get a reply.
4. Open **Deep Research**, enter a question, and run it. It searches the web through the bundled SearXNG (no extra key) and generates a sourced report — a good end-to-end showcase of the deploy.

### Scaling for heavy workloads

The Blueprint defaults the web service to `standard` (2 GB). Odysseus can be resource-hungry under heavy use — large deep-research runs, big documents, sizable embedding jobs, or many concurrent sessions. For those workloads, give the instance more resources: in the Render Dashboard, open the `odysseus` service → **Settings → Instance Type** and pick a larger plan (and bump `odysseus-chromadb` too if your vector store grows). You can downgrade later if the smaller plan proves sufficient.

## Learn more

Full documentation, the complete self-hosted feature set, and contributing guidelines live in the upstream project: [odysseus-dev/odysseus](https://github.com/odysseus-dev/odysseus).

## License

AGPL-3.0-or-later — see [LICENSE](LICENSE) and [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md).
