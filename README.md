# Global Multilingual Live Chat Support Agent

A production-grade, embeddable AI customer support chat system. A visitor opens the widget on any website, writes in their own language without creating an account, and a multi-agent AI system understands the request, answers from the business's own knowledge base, performs authorized account actions, and escalates to a human when it should — all in real time over WebSocket.

This repo is a complete, working implementation: FastAPI backend, native multi-agent orchestration via the OpenAI Agents SDK, a Next.js chat widget, retrieval-augmented answers grounded in Qdrant, and the guardrails, persistence, and deployment configuration needed to run it for real — not just a demo.

## What It Does

1. A customer opens the chat widget on a website (no login required) and writes a message in any language.
2. A **Triage Agent** detects the language and intent, then natively hands the conversation off to the right specialist:
   - **RAG Agent** — answers FAQ, policy, and product questions, grounded only in the client's knowledge base.
   - **Action Agent** — looks up order status, refund status, and creates support tickets through authorized tools.
   - **Escalation Agent** — takes over when the customer asks for a human, or when nothing else can resolve the request.
3. Every reply comes back in the customer's own language, even after a handoff between agents.
4. If escalated, the system saves a summary, opens a ticket, notifies the human team by Email and Slack, and tells the customer — in their language — that someone will follow up outside the chat (there is no live human takeover inside the widget).
5. The conversation persists across reconnects: closing the tab and reopening it resumes the same conversation.

## Key Features

- **No login required** — anonymous, session-based chat; authentication only kicks in for customer-specific actions.
- **Multilingual by design** — every agent (not just Triage) is instructed to reply in the customer's language, and knowledge-base retrieval works cross-lingually (e.g. an Urdu question against English-language docs).
- **Native agent handoffs** — routing between Triage, RAG, Action, and Escalation uses the OpenAI Agents SDK's built-in handoff mechanism, not custom if/else logic.
- **Grounded answers, no hallucination** — the RAG agent only answers from retrieved knowledge-base content and says so when it doesn't have enough information.
- **Guardrails at every boundary** — input filtering (prompt injection, abuse, length), output checks (safety, language consistency, no leaked internals), and tool guardrails (authorization + business-rule validation before any sensitive action runs).
- **Real human escalation, not a chat takeover** — tickets, structured summaries, and Email/Slack notifications, with the customer told to expect follow-up outside the chat.
- **Resilient by default** — retries with backoff around transient LLM/network failures, rate limiting, and safe fallback messages instead of crashes or leaked errors.
- **Durable sessions** — conversations and messages persist in Postgres; Redis handles fast session/rate-limit lookups.

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js + TypeScript, Tailwind CSS |
| Backend | FastAPI (Python), WebSocket for real-time chat |
| Agent orchestration | OpenAI Agents SDK (native handoffs, guardrails, tools) |
| LLM | Google Gemini, via its OpenAI-compatible endpoint |
| Vector database | Qdrant (multilingual embeddings, cross-lingual retrieval) |
| Relational database | PostgreSQL (conversations, messages, tickets) |
| Cache / sessions | Redis (session state, rate limiting) |
| Deployment | Docker, Render/Railway (backend), Vercel (frontend) |

## Architecture Overview

```
Customer (any language)
        │
        ▼
  Chat Widget (Next.js) ──WebSocket──▶ FastAPI backend
                                            │
                                    Input Guardrails
                                            │
                                      Triage Agent
                                  (detect language + intent)
                                            │
                       ┌────────────────────┼────────────────────┐
                       ▼                    ▼                    ▼
                   RAG Agent           Action Agent        Escalation Agent
                (Qdrant search)     (order/refund/ticket    (ticket + Email/
                                       tools, authorized)     Slack + notify)
                       │                    │                    │
                       └────────────────────┼────────────────────┘
                                            ▼
                                    Output Guardrails
                                            │
                                            ▼
                              Response streamed back to widget
```

Every specialist agent shares the same multilingual instruction (so language doesn't drift after a handoff), and every sensitive tool call passes through a guardrail that checks authorization and business rules **before** it touches the database — the LLM only ever requests an action, it never executes one directly.

## Running Locally

### Prerequisites
- Python 3.11+
- Node.js 20+
- Docker + Docker Compose (for local Postgres/Redis/Qdrant)

### 1. Backend setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# edit .env — at minimum set GEMINI_API_KEY
```

### 2. Start local infrastructure and prepare data

```bash
docker compose up -d
python -m backend.scripts.init_db      # creates database tables
python -m backend.rag.ingestion        # embeds knowledge_base/ into Qdrant
```

### 3. Run the backend API

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Health check (reports DB/Redis/Qdrant/model-provider connectivity individually): `GET http://localhost:8000/health`

### 4. Run the frontend widget

```bash
cd frontend
npm install
cp .env.local.example .env.local   # set NEXT_PUBLIC_WS_URL if the backend isn't on localhost:8000
npm run dev
```

Open `http://localhost:3000` to test the widget end to end.

### Tests

```bash
pytest backend/tests/ -v
python -m evaluation.run_rag_eval        # RAG groundedness/abstention score report
python -m backend.tests.load.load_test   # basic load test (requires the API running)
```

Lint: `ruff check .` (backend) and `npm run lint` inside `frontend/`.

> Some agent-routing and multilingual tests make a live Gemini call and are skipped rather than failed if the free-tier daily quota is exhausted — that's an external quota limit, not a code defect.

## Environment Variables

Set these in `.env` (backend) — see `.env.example` for the full annotated list:

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Google Gemini API key (required) |
| `GEMINI_MODEL_NAME` | Chat model, e.g. `gemini-flash-latest` |
| `GEMINI_EMBEDDING_MODEL` | Multilingual embedding model for RAG |
| `DATABASE_URL` | PostgreSQL connection string (`postgresql+asyncpg://...`) |
| `REDIS_URL` | Redis connection string |
| `QDRANT_URL` / `QDRANT_API_KEY` | Qdrant endpoint and API key |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | Escalation email notifications |
| `SLACK_WEBHOOK_URL` | Escalation Slack notifications |
| `RATE_LIMIT_PER_SESSION_PER_MINUTE` / `RATE_LIMIT_PER_IP_PER_MINUTE` | Rate limiting thresholds |
| `TENANT_ID` | Light tenant isolation tag |

Frontend (`frontend/.env.local`): `NEXT_PUBLIC_WS_URL` — the backend's WebSocket URL (e.g. `wss://your-backend-domain/ws/chat` in production).

## Project Structure

```
backend/
  agents/        Triage, RAG, Action, Escalation agent definitions
  tools/         Order lookup, refund status, ticket creation (@function_tool)
  guardrails/    Input / output / tool guardrails, orchestration runner
  rag/           Chunking, embeddings, ingestion, retrieval
  auth/          Authentication and authorization checks
  db/            SQLAlchemy models, repository layer, connection setup
  services/      Session, conversation, escalation, rate-limit services
  websocket/     WebSocket handler, connection manager, event protocol
  api/           REST endpoints (health, tickets)
  tests/         Unit, integration, agent, guardrail, RAG, and load tests
frontend/
  components/    ChatWidget, ChatWindow, MessageList, ChatInput
  lib/           WebSocket client, session handling
knowledge_base/  Source FAQ / policy / product documents for RAG
evaluation/      Fixed evaluation datasets (RAG, routing, multilingual)
docker/          Local infrastructure (Postgres, Redis, Qdrant)
```

## Deployment

Recommended split:

| Component | Platform |
|---|---|
| Frontend | Vercel |
| Backend | Render or Railway (deploys the included `Dockerfile`) |
| Postgres | Neon (or Supabase/Railway Postgres) |
| Redis | Upstash |
| Qdrant | Qdrant Cloud (or a Docker deployment) |

1. Provision Neon, Upstash, and Qdrant Cloud, and get a Gemini API key from Google AI Studio.
2. Deploy the backend from `render.yaml` (a Render Blueprint) or `Procfile` (buildpack platforms), setting every env var from `.env.example` in the platform dashboard — never commit real secrets.
3. Run `python -m backend.scripts.init_db` and `python -m backend.rag.ingestion` once against the production database/Qdrant.
4. Deploy `frontend/` to Vercel, setting `NEXT_PUBLIC_WS_URL` to `wss://<your-backend-domain>/ws/chat`.
5. `.github/workflows/ci.yml` runs backend tests, lint, and frontend lint/build on every push — add a `GEMINI_API_KEY` repository secret so the RAG tests run for real.

Both platforms terminate TLS automatically, so the API is reachable over HTTPS and the WebSocket endpoint over WSS.

## Current Status / MVP Scope

All ten build phases are complete: foundation, RAG pipeline, multi-agent routing, guardrails, persistence, live WebSocket chat, human escalation, production hardening (rate limiting, retries, redaction), testing/evaluation, and deployment configuration.

**Intentionally out of scope for this MVP:**
- Live human takeover inside the chat (escalation always hands off *outside* the chat, by design)
- Voice channels, WhatsApp/SMS as chat channels
- A full CRM or agent dashboard (only a minimal ticket-listing endpoint exists)
- Kubernetes / enterprise SSO / custom model training
- Multi-tenant billing or a self-serve client onboarding flow (a single lightweight `TENANT_ID` tag exists, not full multi-tenant isolation)

---

This is a real, working multilingual support agent, not a prototype — it detects what a customer needs, answers from your actual knowledge base instead of guessing, and knows exactly when to step back and bring in a human, so you can drop it into a website and start handling support conversations in any language from day one.
