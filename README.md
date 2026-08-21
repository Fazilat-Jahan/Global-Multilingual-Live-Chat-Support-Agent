# Global Multilingual Live Chat Support Agent

Production-grade MVP of an embeddable, multilingual, multi-agent AI customer support system. See `Global_Multilingual_Live_Chat_Support_Agent.md` for the full spec and `CLAUDE.md` for the phased build plan (Phases 1–10, all complete).

## Architecture

- **Frontend**: Next.js + TypeScript embeddable chat widget (`frontend/`)
- **Backend**: FastAPI + native OpenAI Agents SDK handoffs (Triage → RAG / Action / Escalation), guardrails, WebSocket protocol (`backend/`)
- **LLM**: Gemini via its OpenAI-compatible endpoint (`backend/model_provider.py`)
- **Vector DB**: Qdrant (multilingual embeddings, cross-lingual retrieval)
- **Persistence**: PostgreSQL (conversations/messages/tickets) + Redis (session cache, rate limiting)

## Local Development

### Prerequisites
- Python 3.11+
- Node.js 20+
- Docker + Docker Compose (for local Postgres/Redis/Qdrant — optional if using hosted equivalents, see below)

### Backend setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# then edit .env — at minimum set GEMINI_API_KEY
```

### Run local infrastructure (Postgres, Redis, Qdrant)

```bash
docker compose up -d
python -m backend.scripts.init_db      # creates tables
python -m backend.rag.ingestion        # embeds knowledge_base/ into Qdrant
```

### Run the API

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Health check (reports DB/Redis/Qdrant/model-provider connectivity individually): `GET http://localhost:8000/health`

### Run the frontend widget

```bash
cd frontend
npm install
cp .env.local.example .env.local   # set NEXT_PUBLIC_WS_URL if backend isn't on localhost:8000
npm run dev
```

### Tests

```bash
pip install -e ".[dev]"
pytest backend/tests/ -v
python -m evaluation.run_rag_eval        # RAG groundedness/abstention score report
python -m backend.tests.load.load_test   # basic load test (requires the API running)
```

Lint:

```bash
ruff check .                 # backend
cd frontend && npm run lint  # frontend
```

Some agent-routing and multilingual tests require a live Gemini call and are skipped (not failed) if the free-tier daily generation quota is exhausted — this is an external quota limit, not a code defect.

---

## Deployment

Recommended split (matches spec section 6):

| Component  | Platform                              |
|------------|----------------------------------------|
| Frontend   | Vercel                                  |
| Backend    | Render or Railway (deploys `Dockerfile`)|
| Postgres   | Neon (or Supabase/Railway Postgres)     |
| Redis      | Upstash                                 |
| Qdrant     | Qdrant Cloud (or a Docker deployment)   |

### 1. Provision managed services

- **Neon**: create a project, copy the connection string, and rewrite it to use the `asyncpg` driver: `postgresql+asyncpg://user:pass@host/db` (do **not** use `?sslmode=require&channel_binding=require` in the URL string — asyncpg needs TLS passed as `connect_args={"ssl": ...}`, which `backend/db/connection.py` already applies automatically for any non-localhost host).
- **Upstash**: create a Redis database, copy its `REDIS_URL`.
- **Qdrant Cloud**: create a cluster, copy its URL and API key.
- **Gemini**: get an API key from Google AI Studio.
- **SMTP + Slack** (for human escalation notifications, Phase 7): an app-password-enabled mailbox and/or a Slack incoming webhook URL.

### 2. Deploy the backend (Render example)

This repo includes `render.yaml` (a Render Blueprint) and a `Dockerfile`.

1. In Render, "New +" → "Blueprint" → connect this GitHub repo.
2. Render reads `render.yaml` and creates the web service from `Dockerfile`.
3. Fill in every env var marked `sync: false` in the Render dashboard (`DATABASE_URL`, `REDIS_URL`, `QDRANT_URL`, `QDRANT_API_KEY`, `GEMINI_API_KEY`, `SMTP_*`, `SLACK_WEBHOOK_URL`) — see `.env.example` for the full list. **Never commit these values.**
4. After the first deploy, run the one-off setup commands against the production database/Qdrant (Render shell, or locally with production env vars exported):
   ```bash
   python -m backend.scripts.init_db
   python -m backend.rag.ingestion
   ```
5. Render terminates TLS automatically — the service is reachable over HTTPS, and the WebSocket endpoint is reachable over WSS at `wss://<your-service>.onrender.com/ws/chat`.

Railway works the same way (Dockerfile-based deploy, dashboard env vars); a `Procfile` is also included for buildpack-based platforms that don't use the Dockerfile.

### 3. Deploy the frontend (Vercel)

1. Import this repo in Vercel, set the project root to `frontend/`.
2. Set the environment variable `NEXT_PUBLIC_WS_URL` to `wss://<your-backend-domain>/ws/chat`.
3. Deploy — Vercel handles HTTPS automatically. Vercel's zero-config Next.js build picks up `npm run build` from `frontend/package.json`.

### 4. CI

`.github/workflows/ci.yml` runs on every push/PR to `main`: backend tests (`pytest`) against real ephemeral Postgres/Redis/Qdrant service containers, backend lint (`ruff`), and frontend lint + build. Add a `GEMINI_API_KEY` repository secret (Settings → Secrets and variables → Actions) so the embedding-dependent RAG tests run for real instead of erroring on a missing key.

To make CI a hard gate before deploy, enable branch protection on `main` (Settings → Branches → require the `backend` and `frontend` status checks to pass before merging), and configure Render/Vercel to deploy only from `main`.

### 5. Smoke test the deployed environment

Once both are live, verify the full customer journey against the public URLs:
1. Open the Vercel frontend URL — the widget should connect without any login step.
2. Ask a FAQ question (e.g. "What is your return policy?") — should route to the RAG Agent and answer from the knowledge base.
3. Ask about an order (e.g. "What's the status of order 12345?") — should route to the Action Agent.
4. Ask to speak to a human — should route to the Escalation Agent, create a ticket, and reply with the Email/WhatsApp follow-up message in your language.
5. Check `GET https://<backend-domain>/tickets` to confirm the ticket was created, and confirm the escalation email/Slack notification actually arrived.
6. Kill and restore your network connection mid-chat — the widget should reconnect and resume the same conversation.
