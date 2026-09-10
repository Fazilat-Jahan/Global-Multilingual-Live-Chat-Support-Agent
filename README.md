# Global Multilingual Live Chat Support Agent

A production-grade, embeddable AI customer support chat system. A visitor opens the widget on any website, writes in their own language without creating an account, and a multi-agent AI system understands the request, answers from the business's own knowledge base, performs authorized account actions, verifies identity mid-conversation before revealing protected data, and escalates to a human when it should — all in real time over WebSocket, inside a sandboxed iframe that drops into any site with one script tag.

This repo is a complete, working implementation: a FastAPI backend, native multi-agent orchestration via the OpenAI Agents SDK (backed by Google Gemini), a Next.js chat widget with an embeddable loader script, retrieval-augmented answers grounded in Qdrant, Alembic-managed PostgreSQL persistence, Redis-backed sessions/rate-limiting/verification state, and the guardrails, tenant isolation, CI, and deployment configuration needed to run it for real.

## Table of Contents

- [What It Does](#what-it-does)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [Installation / Setup](#installation--setup)
- [Environment Variables](#environment-variables)
- [Usage](#usage)
- [API Documentation](#api-documentation)
- [Database Schema](#database-schema)
- [Scripts](#scripts)
- [Testing](#testing)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [Known Issues / Limitations](#known-issues--limitations)
- [License](#license)

## What It Does

1. A customer opens the chat widget on a website (no login required) and writes a message in any language.
2. A **Triage Agent** detects the language and intent, then natively hands the conversation off — via the OpenAI Agents SDK's built-in `handoffs`, not custom if/else routing — to the right specialist:
   - **RAG Agent** — answers FAQ, policy, and product questions, grounded only in the client's knowledge base (Qdrant), and says so when it doesn't know rather than guessing.
   - **Action Agent** — looks up order status and refund status, and creates support tickets, through authorized tools; protected order data requires mid-conversation identity verification first.
   - **Escalation Agent** — takes over when the customer asks for a human, or when nothing else can resolve the request.
3. Every reply comes back in the customer's own language, even after a handoff between agents — each agent independently repeats the multilingual instruction so language never drifts.
4. If escalated, the system saves a structured summary, opens a ticket, notifies the human team by Email, and tells the customer — in their language — that someone will follow up outside the chat (there is **no live human takeover** inside the widget, by design).
5. The conversation persists across reconnects: closing the tab and reopening it resumes the same conversation with the same agent context.
6. The widget embeds anywhere with a single `<script>` tag, running inside a sandboxed, CSP-restricted iframe so no client site can pull session data out of it.

## Features

**Conversational AI**
- Native multi-agent routing (Triage → RAG / Action / Escalation) via the OpenAI Agents SDK's `handoffs` mechanism
- Cross-lingual retrieval-augmented generation grounded in a Qdrant knowledge base — a query in Urdu, Roman Urdu, Arabic, or Spanish retrieves correctly against English-source documents via multilingual embeddings
- Grounded, non-hallucinating answers — the RAG agent abstains ("I don't have enough information to answer that accurately") instead of inventing policy when retrieval is low-confidence
- Every customer-facing agent repeats the "respond in the customer's language" instruction independently, so a handoff never causes language drift
- Automatic continuation of responses that get cut off mid-sentence by upstream streaming issues (heuristic sentence-boundary check + one corrective LLM call)

**Guardrails & Security**
- **Input guardrails**: prompt-injection detection, abusive-content filtering, excessive-length rejection, off-topic/unsupported-request detection — all run before Triage ever sees the message
- **Output guardrails**: leaked-internals detection (tracebacks, API keys, DB URLs, system prompts), unsafe-content check, language-consistency check with one automatic corrective retry
- **Tool guardrails**: every sensitive tool call passes through authorization + business-rule validation *before* the tool body runs (`LLM → Tool Request → Tool Guardrail → Authorization Check → Business Rule Validation → actual operation`) — the LLM only ever requests an action, never executes one directly
- **Mid-conversation customer verification**: protected order/refund lookups are gated behind an order-ID + email match; verified customers are tracked per-session in Redis (24h TTL), attempts are rate-limited (5 per 10 minutes), and 3 failed attempts trigger an escalation offer
- **Streaming guardrail retraction**: if an output guardrail trips *after* a response has already started streaming to the client, a `response_retracted` event swaps the partial content for safe replacement text — the blocked content is logged server-side but never persisted
- Deterministic, pattern-based security checks (not another LLM call) — heuristic regex matching for prompt injection, abuse, and internal-detail leakage
- PII masking (email/phone/card-like patterns) applied to log output; email addresses are also stripped from persisted conversation history after verification

**Human Escalation**
- Structured conversation summaries, real support tickets, and real Email + Slack notifications to the human team
- No code path exists for a human to inject a message back into a live customer session — escalation is architecturally one-way

**Sessions & Persistence**
- Anonymous, session-based chat — no login required; a `session_id` is minted by the server and persisted client-side
- PostgreSQL durable storage for conversations, messages, and tickets, with a full conversation state machine (`ACTIVE` → `WAITING_FOR_USER` → `WAITING_FOR_HUMAN` → `ESCALATED` → `RESOLVED` → `CLOSED`)
- Redis-backed fast session cache in front of Postgres (cache miss/outage falls through to Postgres, never loses data)
- Reconnecting with the same `session_id` reloads prior message history and resumes with whichever agent last responded

**Real-Time Chat**
- WebSocket protocol with a stable, documented event contract (`connected`, `agent_started`, `agent_handoff`, `tool_started`/`tool_completed`, `response_delta`/`response_completed`, `response_retracted`, `escalation`, `error`, heartbeat `ping`/`pong`)
- Per-session single-active-request queue: extra messages sent while one is in flight are queued (max 2) and acknowledged with `message_queued`; a client can `cancel_request` to discard an in-flight response
- Connection manager with heartbeat/idle-timeout detection and duplicate-message-id protection
- Auto-reconnect with exponential backoff on the frontend, replaying any message that was sent but never acknowledged

**Embeddable Widget**
- One-script loader (`widget-loader.js`) that injects a floating launcher button and a sandboxed `<iframe>` pointing at the `/widget` route, with a `postMessage`-based open/close protocol and mobile full-screen mode
- `frame-ancestors` CSP header restricts which sites may embed the widget; a server-side `OriginPolicyMiddleware` additionally rejects disallowed origins for both HTTP and WebSocket upgrades (not just a browser-side CORS block)
- Public `window.SupportChat.open()/close()/toggle()` JS API for host-page integration

**Knowledge Base Management**
- SHA-256 checksum-based incremental re-ingestion — only new/modified documents are re-embedded; removed documents have their chunks deleted
- Full re-ingestion mode for a clean rebuild
- Redis lock (`reingest_lock`) prevents concurrent ingestion runs; atomic per-document chunk replacement (delete-then-insert) for zero-downtime updates
- Admin REST endpoint (API-key protected) to trigger re-ingestion without shell access

**Production Hardening**
- Redis-backed fixed-window rate limiting, per session and per IP
- Retry policies (network errors, 5xx, 429) applied uniformly to every Gemini call via the Agents SDK's `RunConfig`
- Qdrant search retried with a bounded timeout, converting an outage into a distinct "temporarily unavailable" signal the RAG agent can talk about honestly
- Deep `/health` endpoint checking real connectivity to Postgres, Redis, Qdrant, and the model provider individually (not just process liveness)
- Every data store scoped by `tenant_id` (Postgres rows, `{tenant_id}:`-prefixed Redis keys, per-tenant Qdrant collections) for light multi-client isolation
- No tracebacks, API keys, DB errors, internal URLs, or system prompts are ever returned to a customer — converted to safe fallback messages, with full detail only in server logs

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 (App Router) + TypeScript + React 18, Tailwind CSS |
| Backend | FastAPI (Python 3.11+), native WebSocket for real-time chat |
| Agent orchestration | OpenAI Agents SDK (`openai-agents`) — native handoffs, guardrails, tool-calling |
| LLM | Google Gemini (`gemini-flash-latest`), via its OpenAI-compatible Chat Completions endpoint |
| Embeddings | Google `gemini-embedding-001` (3072-dim, multilingual) |
| Vector database | Qdrant — per-tenant collections, cosine similarity |
| Relational database | PostgreSQL, via SQLAlchemy 2.0 (async) + `asyncpg`, schema managed by Alembic |
| Cache / sessions | Redis (`redis.asyncio`) — session cache, rate limiting, verification state, ingestion locks |
| Validation / config | Pydantic v2 + `pydantic-settings` |
| Testing | pytest + pytest-asyncio, `pytest-cov` |
| Linting / types | Ruff (lint + format), Pyright |
| Security scanning | `pip-audit` |
| Deployment | Docker, Railway (backend), Vercel (frontend), GitHub Actions CI |

## Architecture Overview

```
Customer (any language)
        │
        ▼
  Chat Widget (Next.js, sandboxed iframe) ──WebSocket──▶ FastAPI backend
                                                              │
                                                    OriginPolicyMiddleware
                                                    (origin allowlist)
                                                              │
                                                     Per-session message queue
                                                     (single active request)
                                                              │
                                                       Input Guardrails
                                             (injection · abuse · length · scope)
                                                              │
                                                         Triage Agent
                                                (detect language + intent)
                                                              │
                                 ┌────────────────────────────┼────────────────────────────┐
                                 ▼                             ▼                             ▼
                            RAG Agent                    Action Agent                 Escalation Agent
                        (search_knowledge_base       (lookup_order_status,          (create_support_ticket,
                         → Qdrant, cross-lingual)     check_refund_status,           notify_human_team →
                                                       create_support_ticket,         Email + Slack, no
                                                       verify_customer →              live takeover)
                                                       Tool Guardrail →
                                                       Authorization Check)
                                 │                             │                             │
                                 └────────────────────────────┼────────────────────────────┘
                                                              ▼
                                                       Output Guardrails
                                            (leakage · safety · language consistency)
                                                              │
                                                              ▼
                                        response_delta / response_completed / response_retracted
                                                              │
                                                              ▼
                                          Persisted to Postgres (Conversation + Message rows)
```

Every specialist agent's system prompt independently repeats the multilingual instruction. Every sensitive tool call passes through a `tool_input_guardrail` that checks authorization and business rules *before* the tool body runs — the LLM only ever requests an action, it never executes one directly.

## Project Structure

```
Global Multilingual Live Chat Support Agent/
├── backend/
│   ├── agents/                 # Triage, RAG, Action, Escalation agent definitions
│   │   ├── triage.py
│   │   ├── rag.py
│   │   ├── action.py
│   │   └── escalation.py
│   ├── tools/                  # @function_tool definitions the agents call
│   │   ├── knowledge_search.py     # search_knowledge_base (RAG agent)
│   │   ├── order_tools.py          # lookup_order_status, check_refund_status
│   │   ├── support_tools.py        # create_support_ticket, notify_human_team
│   │   └── verification_tools.py   # verify_customer (spec 4.1)
│   ├── guardrails/              # Input / output / tool guardrails + orchestration
│   │   ├── input.py                # validate_customer_input
│   │   ├── output.py               # validate_agent_output
│   │   ├── tools.py                # authorize_order_access, validate_ticket_input
│   │   ├── security.py             # shared regex checks, PII masking, language detection
│   │   ├── context.py              # SupportContext (per-run context object)
│   │   └── runner.py               # run_turn / stream_turn — the guardrail-wrapped Runner wrapper
│   ├── rag/                     # Retrieval-augmented generation pipeline
│   │   ├── chunking.py              # clean_text, chunk_text
│   │   ├── embeddings.py            # embed_texts / embed_query (Gemini)
│   │   ├── ingestion.py             # full/incremental ingestion CLI + admin entrypoint
│   │   └── retrieval.py             # cross-lingual Qdrant search + abstention threshold
│   ├── auth/                    # Authentication and authorization
│   │   ├── authentication.py        # mock token → customer_id resolution
│   │   ├── authorization.py         # order-ownership checks
│   │   └── verification.py          # pluggable CustomerVerificationProvider
│   ├── services/                 # Business-logic orchestration
│   │   ├── conversation_service.py  # load_or_create, handle_message, stream_message
│   │   ├── session_service.py       # Redis session_id → conversation_id cache
│   │   ├── escalation_service.py    # ticket creation + Email/Slack notification
│   │   ├── rate_limit_service.py    # Redis fixed-window rate limiting
│   │   └── verification_service.py  # Redis verification state/rate-limit bookkeeping
│   ├── db/                       # Persistence layer
│   │   ├── models.py                 # SQLAlchemy models (Conversation, Message, Ticket, KnowledgeDocument)
│   │   ├── repository.py             # DB read/write functions
│   │   ├── connection.py             # async engine + session factory
│   │   └── migrations/               # Alembic environment + versioned migrations
│   ├── websocket/                # Real-time chat transport
│   │   ├── handler.py                # /ws/chat endpoint, receive loop + queue processor
│   │   ├── events.py                 # the stable event-type protocol
│   │   ├── connection_manager.py     # heartbeat, idle timeout, dedup
│   │   └── message_queue.py          # per-session single-active-request queue
│   ├── middleware/
│   │   └── origin_policy.py          # server-side Origin allowlist enforcement
│   ├── api/                      # REST endpoints
│   │   ├── health.py                  # GET /health
│   │   ├── tickets.py                 # GET /tickets, GET /tickets/{id}
│   │   └── admin.py                   # POST /api/admin/knowledge-base/reingest
│   ├── scripts/                  # One-off harnesses and CLIs (see Scripts section)
│   ├── tests/                    # unit / integration / agents / guardrails / rag / load
│   ├── config.py                 # Settings (pydantic-settings, env-driven)
│   ├── model_provider.py         # Gemini + OpenAI Agents SDK wiring (single source of truth)
│   ├── main.py                   # FastAPI app assembly
│   └── alembic.ini
├── frontend/
│   ├── app/
│   │   ├── page.tsx                  # demo "client website" with the floating launcher widget
│   │   ├── widget/page.tsx           # chrome-less route embedded via <iframe> (/widget)
│   │   └── layout.tsx, globals.css
│   ├── components/
│   │   ├── ChatWidget.tsx            # top-level state machine, WebSocket event handling
│   │   ├── ChatWindow.tsx            # header + message list + input, connection status
│   │   ├── MessageList.tsx           # message bubbles, streaming/status line
│   │   └── ChatInput.tsx             # textarea + send button
│   ├── lib/
│   │   ├── websocket.ts              # ChatSocket client (reconnect, heartbeat, event bus)
│   │   └── session.ts                # localStorage session_id persistence
│   ├── public/
│   │   ├── widget-loader.js          # distributable one-script embed loader
│   │   ├── loader-demo.html          # demo page using widget-loader.js
│   │   └── test-embed.html
│   └── next.config.mjs               # CSP frame-ancestors header for /widget
├── knowledge_base/               # Source FAQ / policy / product documents (RAG source of truth)
│   ├── faq/            (shipping.md, returns.md, payment.md)
│   ├── policies/        (refund_policy.md, privacy_policy.md)
│   └── products/         (smart_watch.md, wireless_headphones.md)
├── evaluation/                    # Fixed evaluation datasets + RAG eval runner
│   ├── rag_cases.json
│   ├── routing_cases.json
│   ├── multilingual_cases.json
│   └── run_rag_eval.py
├── docker-compose.yml             # Postgres + Redis + Qdrant (+ optional app service)
├── Dockerfile                     # Backend container image (runs Alembic, then uvicorn)
├── Procfile                       # release/web process types (buildpack platforms)
├── railway.toml                   # Railway config-as-code for the backend
├── pyproject.toml                 # Python package, dependencies, ruff/pytest/coverage config
├── pyrightconfig.json
├── .env.example
├── CLAUDE.md                      # Full build-phase spec and standing engineering rules
└── Global_Multilingual_Live_Chat_Support_Agent.md   # Source-of-truth product/technical spec
```

## Installation / Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker + Docker Compose (for local Postgres/Redis/Qdrant)
- A [Google Gemini API key](https://aistudio.google.com/) (free tier works for local development)

### 1. Clone and configure

```bash
git clone <this-repo-url>
cd "Global Multilingual Live Chat Support Agent"
cp .env.example .env
# edit .env — at minimum set GEMINI_API_KEY
```

### 2. Backend: Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 3. Start local infrastructure and prepare data

```bash
docker compose up -d postgres redis qdrant
python -m backend.scripts.init_db      # creates all Postgres tables from the current models
python -m backend.rag.ingestion        # embeds knowledge_base/ into Qdrant (incremental mode by default)
```

> The project ships Alembic migrations for tracked schema changes against an *existing* database (see [Database Schema](#database-schema)). For a brand-new local database, `init_db.py` creates the full current schema directly from the SQLAlchemy models in one step — that's the supported local bootstrap path.

### 4. Run the backend API

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Verify: `GET http://localhost:8000/health` should report `{"status": "ok", ...}` with every dependency `ok`.

### 5. Run the frontend widget

```bash
cd frontend
npm install
cp .env.local.example .env.local   # set NEXT_PUBLIC_WS_URL if the backend isn't on localhost:8000
npm run dev
```

Open `http://localhost:3000` — a demo "client website" page with the chat widget floating in the bottom-right corner.

### 6. (Optional) Full stack via Docker Compose

```bash
docker compose up -d --build
```

This also builds and starts the backend `app` service (runs `alembic upgrade head` then `uvicorn`) alongside Postgres/Redis/Qdrant — requires `GEMINI_API_KEY` set in a local `.env` file first, and an already-initialized database schema (see the note in step 3).

## Environment Variables

Backend (`.env`, loaded via `pydantic-settings` — see `.env.example` for the annotated full list):

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | *(required)* | Google Gemini API key |
| `GEMINI_MODEL_NAME` | `gemini-flash-latest` | Chat completion model |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Multilingual embedding model for RAG |
| `APP_ENV` | `development` | Environment tag |
| `APP_HOST` | `0.0.0.0` | Bind host |
| `APP_PORT` | `8000` | Bind port |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `DATABASE_URL` | `postgresql+asyncpg://support_user:support_pass@localhost:5432/support_agent` | PostgreSQL connection string (must keep `+asyncpg`) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant endpoint |
| `QDRANT_API_KEY` | *(empty)* | Qdrant API key (Qdrant Cloud) |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | *(empty)* | Escalation email notifications; skipped (logged, not sent) if unset |
| `SLACK_WEBHOOK_URL` | *(empty)* | Escalation Slack notifications; skipped if unset |
| `RATE_LIMIT_PER_SESSION_PER_MINUTE` | `20` | Per-session rate limit |
| `RATE_LIMIT_PER_IP_PER_MINUTE` | `60` | Per-IP rate limit |
| `TENANT_ID` | `default` | Tenant discriminator — prefixes Redis keys, Qdrant collection name, and tags every DB row |
| `ADMIN_API_KEY` | *(empty)* | Bearer token for `POST /api/admin/knowledge-base/reingest`; endpoint returns 403 if unset |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated origins allowed to call the API / open WebSocket connections directly |

Frontend (`frontend/.env.local`, see `.env.local.example`):

| Variable | Default | Purpose |
|---|---|---|
| `NEXT_PUBLIC_WS_URL` | `ws://localhost:8000/ws/chat` | Backend WebSocket URL (use `wss://` in production) |
| `WIDGET_ALLOWED_EMBEDDERS` | `http://localhost:3000` | Comma-separated origins allowed to embed `/widget` in an `<iframe>` (build-time CSP `frame-ancestors`) |

Secrets are only ever read from environment variables — nothing is hardcoded, and `.env`/`.env.local` are gitignored.

## Usage

### Talking to the widget

Open the frontend (`http://localhost:3000`), click the chat bubble, and type a message in any language. No account or login is needed. Try:

- *"What's your return policy?"* → routes to the RAG Agent, answered from `knowledge_base/policies/refund_policy.md`
- *"Where is my order 12345?"* → routes to the Action Agent; since order `12345` belongs to `cust_1` and you're anonymous, you'll be asked to verify with the email on the order (`alice@example.com` in the mock data) before it discloses status
- *"I want to talk to a human"* → routes to the Escalation Agent, which creates a ticket and tells you (in your language) that a human will follow up by Email/WhatsApp

### Embedding the widget on another page

Serve the frontend, then embed it anywhere with one script tag:

```html
<script src="https://<your-widget-host>/widget-loader.js"
        data-host="https://<your-widget-host>"
        data-tenant="default"></script>
```

This injects a floating launcher button and a sandboxed `<iframe>` pointing at `/widget`. See `frontend/public/loader-demo.html` and `frontend/public/test-embed.html` for working examples. The host page can also control the widget programmatically:

```js
window.SupportChat.open();
window.SupportChat.close();
window.SupportChat.toggle();
```

### Re-ingesting the knowledge base

```bash
python -m backend.rag.ingestion --mode incremental   # default — only new/changed files
python -m backend.rag.ingestion --mode full           # wipe and re-embed everything
python -m backend.rag.ingestion --source /path/to/other/kb --mode full
```

Or remotely, via the admin API:

```bash
curl -X POST http://localhost:8000/api/admin/knowledge-base/reingest \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"mode": "incremental"}'
```

## API Documentation

### REST endpoints

#### `GET /health`

Deep health check — reports real connectivity to every dependency, not just process liveness.

Response `200` (all healthy) or `503` (one or more dependencies down):

```json
{
  "status": "ok",
  "dependencies": {
    "database": "ok",
    "redis": "ok",
    "qdrant": "ok",
    "model_provider": "ok"
  }
}
```

Each dependency value is `"ok"`, `"degraded"` (model provider reachable but rate-limited), or `"down"`.

#### `GET /tickets`

List support tickets (internal use — no auth on this MVP endpoint; not exposed to the widget).

Query params: `status` (optional) — one of `OPEN`, `ASSIGNED`, `IN_PROGRESS`, `RESOLVED`, `CLOSED`.

Response `200`:
```json
[
  {
    "ticket_id": "TCK-A1B2C3D4",
    "conversation_id": "b3f1...-uuid",
    "priority": "normal",
    "reason": "human requested",
    "summary": "Customer asked about a delayed order and wants a callback.",
    "customer_reference": null,
    "status": "OPEN",
    "created_at": "2026-09-07T10:15:00+00:00",
    "assigned_to": null
  }
]
```

#### `GET /tickets/{ticket_id}`

Single ticket lookup by its human-readable `ticket_id`. `404` if not found.

#### `POST /api/admin/knowledge-base/reingest`

Triggers a full or incremental knowledge-base re-ingestion. Requires `Authorization: Bearer <ADMIN_API_KEY>`.

Request body:
```json
{ "mode": "incremental", "source": null }
```
- `mode`: `"full"` (delete all tenant chunks, re-embed everything) or `"incremental"` (default — SHA-256 checksum comparison, only changed documents)
- `source`: optional path override for the knowledge base directory

Response `200`:
```json
{
  "mode": "incremental",
  "documents_processed": 2,
  "documents_skipped": 5,
  "documents_deleted": 0,
  "chunks_created": 14,
  "duration_seconds": 3.2,
  "errors": null
}
```

Errors: `403` (missing/invalid/unconfigured admin key), `400` (invalid `mode`), `409` (another re-ingestion is already in progress — Redis lock contention).

### WebSocket protocol: `ws(s)://<host>/ws/chat[?session_id=<id>]`

Connect with no `session_id` to start a new anonymous session (the server mints and returns one in `connected`); reconnect with a known `session_id` to resume the same conversation.

**Client → server messages**

| Type | Shape | Purpose |
|---|---|---|
| `user_message` | `{type, message_id, content}` | Send a chat message. `message_id` is a client-generated UUID used for dedup and resend-on-reconnect. |
| `cancel_request` | `{type}` | Discard the current in-flight response once its stream completes (the LLM call itself is not forcibly aborted). |
| `pong` | `{type}` | Heartbeat acknowledgement. |

**Server → client events**

| Type | Shape | When |
|---|---|---|
| `connected` | `{type, session_id}` | Immediately after the socket is accepted. |
| `message_received` | `{type, message_id}` | Acknowledges a `user_message` was accepted. |
| `message_queued` | `{type, position}` | A message arrived while another was still processing (max queue depth 2). |
| `agent_started` | `{type, agent}` | The turn's agent run has begun. |
| `agent_handoff` | `{type, from, to}` | A native SDK handoff occurred mid-turn. |
| `tool_started` | `{type, tool, agent}` | A `@function_tool` call has begun. |
| `tool_completed` | `{type, tool, agent, result}` | The tool call returned (result truncated to 500 chars). |
| `response_delta` | `{type, delta, agent}` | A streamed chunk of the final answer. |
| `response_completed` | `{type, text, agent}` | The full final answer text (also the source of truth for what gets persisted). |
| `response_retracted` | `{type, reason, replacement}` | An output guardrail tripped after streaming had already started — the client must discard/replace the partial text with `replacement`. |
| `request_cancelled` | `{type}` | Acknowledges a `cancel_request` took effect. |
| `escalation` | `{type, agent}` | The turn ended with the Escalation Agent. |
| `error` | `{type, message, code?}` | A safe, customer-facing error (e.g. `code: "QUEUE_FULL"` when the per-session queue is full, or a rate-limit message). Never contains internal detail. |
| `ping` | `{type}` | Heartbeat, every 30s; the connection is closed after 300s of no client activity. |

The frontend only ever needs to know this event contract — it has no knowledge of which agents or tools exist internally.

## Database Schema

PostgreSQL, managed by SQLAlchemy 2.0 models (`backend/db/models.py`) with Alembic-tracked migrations (`backend/db/migrations/`).

### `conversations`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `session_id` | string(64), unique, indexed | The anonymous session identifier the widget/WebSocket uses |
| `customer_id` | string(64), nullable | Set only once a customer authenticates (mock token) or verifies |
| `tenant_id` | string(64), indexed, default `"default"` | Tenant discriminator |
| `status` | enum: `ACTIVE`, `WAITING_FOR_USER`, `WAITING_FOR_HUMAN`, `ESCALATED`, `RESOLVED`, `CLOSED` | State machine |
| `detected_language` | string(8), nullable | Best-effort ISO 639-1 code from the latest turn |
| `created_at` / `updated_at` | timestamptz | |
| `escalated_at` | timestamptz, nullable | Set when the conversation transitions to `ESCALATED` |

### `messages`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `conversation_id` | UUID (FK → conversations.id), indexed | |
| `tenant_id` | string(64), indexed, default `"default"` | |
| `role` | string(16) | `"user"` or `"assistant"` |
| `content` | text | Email addresses are masked out before persistence |
| `agent` | string(64), nullable | Which agent produced this message (assistant rows only) |
| `created_at` | timestamptz | |
| `metadata` (mapped as `metadata_`) | JSON, nullable | e.g. `{"blocked": bool, "block_reason": str}` |

### `tickets`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `ticket_id` | string(32), unique, indexed | Human-readable ID, format `TCK-XXXXXXXX` |
| `tenant_id` | string(64), indexed, default `"default"` | |
| `conversation_id` | UUID (FK → conversations.id), nullable, indexed | |
| `priority` | string(16), default `"normal"` | `"low"` \| `"normal"` \| `"high"` |
| `reason` | string(256) | Short category |
| `summary` | text | Structured conversation summary |
| `customer_reference` | string(64), nullable | |
| `status` | enum: `OPEN`, `ASSIGNED`, `IN_PROGRESS`, `RESOLVED`, `CLOSED` | |
| `created_at` | timestamptz | |
| `assigned_to` | string(64), nullable | |

### `knowledge_documents`

Tracks ingested source files for incremental re-ingestion (not customer-facing data).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `document_id` | string(128), indexed | The source file's stem, e.g. `refund_policy` |
| `tenant_id` | string(64), indexed, default `"default"` | |
| `file_path` | string(512) | Path relative to `knowledge_base/` |
| `checksum` | string(64) | SHA-256 hex digest of the file content |
| `chunk_count` | integer | Number of chunks produced from this document |
| `last_ingested_at` | timestamptz | |

### Qdrant

One collection per tenant, named `{tenant_id}_knowledge_base`, cosine similarity, 3072-dim vectors (`gemini-embedding-001`). Each point's payload carries `tenant_id`, `document_id`, `source`, `title`, `category`, `product`, `language`, `version`, `chunk_index`, `text`, `created_at`, `updated_at`. Point IDs are deterministic (MD5 of `{document_id}:{chunk_index}`) so re-ingestion upserts in place.

### Migrations

```bash
cd backend
alembic current             # show the applied revision
alembic upgrade head        # apply pending migrations
alembic revision --autogenerate -m "description"   # generate a new migration from model changes
alembic check                # verify no un-migrated model changes exist
```

The chain: `6cc4ab724fa6` (baseline, stamps the schema `init_db.py` creates) → `648a152d1ff9` (adds `tenant_id` to `messages`) → `903a7a279ae3` (adds `knowledge_documents`). See [Known Issues](#known-issues--limitations) for the baseline's scope.

## Scripts

### Python (`backend/scripts/`, run as `python -m backend.scripts.<name>`)

| Script | Purpose |
|---|---|
| `init_db` | Creates all Postgres tables from the current SQLAlchemy models — the local bootstrap path |
| `test_gemini_connection` | One-off check that `model_provider.py` can reach Gemini and get a real completion |
| `routing_harness` | Exercises the Triage → RAG/Action/Escalation handoff graph directly via `Runner.run()`, no WebSocket/DB |
| `language_switch_case` | Isolated re-run of the mid-conversation language-switch routing case |
| `guardrail_harness` / `guardrail_harness_remaining` | Exercises input/output/tool guardrails via the orchestration runner |
| `output_guardrail_unit_test` | Direct, no-LLM-call unit check of the language-consistency guardrail |
| `persistence_harness` / `persistence_harness_remaining` | Exercises `conversation_service` across simulated reconnects |
| `redis_fallback_check` | Confirms Postgres remains the source of truth when the Redis session cache is empty |
| `websocket_client_check` / `_remaining`, `websocket_escalation_check` | Scripted WebSocket client against a running `uvicorn` instance — session creation, streaming, reconnect, escalation |
| `escalation_harness` | Drives a real escalation over the live WebSocket and checks the resulting `Ticket` row + `/tickets` API |
| `verification_harness` | Live-LLM check of the mid-conversation verification flow (challenge → verify → retry) |

### RAG / knowledge base

```bash
python -m backend.rag.ingestion [--mode full|incremental] [--source PATH]
python -m evaluation.run_rag_eval        # RAG groundedness/abstention score report against evaluation/rag_cases.json
```

### Frontend (`frontend/package.json`)

| Script | Command | Purpose |
|---|---|---|
| `dev` | `next dev` | Local dev server with hot reload |
| `build` | `next build` | Production build |
| `start` | `next start` | Serve the production build |
| `lint` | `next lint` | ESLint |

### Load testing

```bash
python -m backend.tests.load.load_test   # basic concurrent-user load test (requires the API running)
```

## Testing

```bash
# Full backend suite
pytest backend/tests/ -v

# By category
pytest backend/tests/unit/ -v          # tools, auth, chunking, rate limiting, message queue, tenant scoping, etc.
pytest backend/tests/guardrails/ -v    # input/output/tool guardrail pattern-matching (no LLM)
pytest backend/tests/integration/ -v   # FastAPI → DB, Alembic, origin policy, conversation flow, verification persistence
pytest backend/tests/agents/ -v        # live-LLM routing + multilingual handoff tests
pytest backend/tests/rag/ -v           # live retrieval against an ingested Qdrant collection

# Coverage (matches the CI gate — unit + guardrail tests, 80% minimum)
pytest backend/tests/unit/ backend/tests/guardrails/ -v --cov --cov-report=term-missing --cov-fail-under=80

# RAG evaluation (groundedness / relevance / abstention / multilingual retrieval)
python -m evaluation.run_rag_eval

# Load test (needs the API running separately)
python -m backend.tests.load.load_test
```

Lint / types:
```bash
ruff check backend/
ruff format --check backend/
pyright backend/
pip-audit
```

Frontend:
```bash
cd frontend && npm run lint && npm run build
```

**Coverage scope**: unit + guardrail tests (pure logic, no external services) are measured against an 80% floor (actual: ~97%). Modules that require a live Postgres/Redis/Qdrant/Gemini connection (agents, RAG retrieval/ingestion/embeddings, the guardrail runner, most services, the WebSocket handler, DB repository/connection) are exercised by the separate integration/agent/RAG suites instead, without a coverage gate, since those depend on external service and LLM-quota availability.

> Some agent-routing, multilingual, and RAG tests make a live Gemini call and are **skipped** (via `skip_if_quota_exhausted` in `backend/tests/conftest.py`) rather than failed if the free-tier daily quota is exhausted — that's an external quota limit, not a code defect.

## Deployment

Recommended split:

| Component | Platform |
|---|---|
| Frontend | Vercel |
| Backend | Railway (deploys the included `Dockerfile`, config in `railway.toml`) |
| Postgres | Neon (or Railway Postgres) |
| Redis | Upstash (or Railway Redis) |
| Qdrant | Qdrant Cloud (or a self-hosted Docker deployment) |

1. Provision Neon, Upstash, and Qdrant Cloud, and get a Gemini API key from Google AI Studio.
2. Create a new Railway project and connect this GitHub repo — Railway auto-detects `railway.toml` and builds the included `Dockerfile`. Set every env var from `.env.example` in the Railway dashboard (Project → Service → Variables) or via `railway variables set` — never commit real secrets. `railway.toml`'s `releaseCommand` runs `alembic upgrade head` as its own deploy phase before `startCommand` launches `uvicorn` (Railway's equivalent of a Render/Heroku release phase); the `Dockerfile`'s own `CMD` and the `Procfile`'s `release` phase do the same combined migrate-then-start sequence for a plain `docker run` or a buildpack-based platform.
3. Ensure the target database already has the base schema (see [Known Issues](#known-issues--limitations)) — run `python -m backend.scripts.init_db` against it once if it's brand new, then let the deploy's `alembic upgrade head` step apply everything after the baseline.
4. Run `python -m backend.rag.ingestion --mode full` once against the production Qdrant instance to seed the knowledge base.
5. Deploy `frontend/` to Vercel, setting `NEXT_PUBLIC_WS_URL` to `wss://<your-backend-domain>/ws/chat` and `WIDGET_ALLOWED_EMBEDDERS` to the client site domain(s) that are allowed to embed `/widget`.
6. On the backend, set `ALLOWED_ORIGINS` to the same client site domain(s) plus the widget host's own origin.
7. `.github/workflows/ci.yml` runs five jobs on every push to `main`/PR — `lint`, `typecheck`, `test` (against real Postgres/Redis/Qdrant service containers), `frontend` (lint + build), and `security` (`pip-audit`). Add a `GEMINI_API_KEY` repository secret so the live-LLM tests in the `test` job run for real. CI is a required-checks gate on `main`, separate from Railway's own auto-deploy-on-push — configure branch protection in GitHub so a failing CI run blocks the merge that would otherwise trigger Railway's deploy.

Both Railway and Vercel terminate TLS automatically, so the API is reachable over HTTPS and the WebSocket endpoint over WSS.

## Contributing

This is a single-owner project built phase-by-phase against the specification in `CLAUDE.md` / `Global_Multilingual_Live_Chat_Support_Agent.md`. If you're picking up work on it:

1. **Read `CLAUDE.md` first** — it defines the phase structure, the non-negotiable technical rules (Gemini setup, native handoffs only, the multilingual instruction, guardrail boundaries, tool patterns), and which phases are done vs. open.
2. **Don't regenerate or re-scaffold completed phases.** Phases 1–18 are all marked complete as of this writing — new work adds new files/code paths rather than rewriting existing ones.
3. **Match the existing style**: async-first FastAPI/SQLAlchemy, Pydantic settings (never hardcoded config/secrets), `@function_tool` for every agent-callable action with a precise docstring, guardrails wired through the Agents SDK's own guardrail mechanism (not ad-hoc pre/post-processing).
4. **Before opening a PR**: `ruff check backend/ && ruff format --check backend/ && pyright backend/ && pytest backend/tests/ -v` on the backend, and `npm run lint && npm run build` on the frontend. CI enforces the same gates.
5. Keep commits scoped — a bug fix shouldn't carry an unrelated refactor. No speculative abstractions or dead configuration for features that don't exist yet.

## Known Issues / Limitations

**Intentionally out of scope for this MVP** (see `CLAUDE.md` section 20):
- Live human takeover inside the chat — escalation always hands off *outside* the chat, by design, not as a missing feature
- Voice channels, WhatsApp/SMS as chat *channels* (WhatsApp is only ever mentioned as an escalation follow-up channel, not integrated)
- A full CRM or agent dashboard — only a minimal read-only `/tickets` listing endpoint exists
- Kubernetes, enterprise SSO, custom model training
- Multi-tenant billing or self-serve client onboarding — a single `TENANT_ID` discriminator provides data isolation, not a management plane

**Other known limitations:**
- **Mock authentication/authorization data**: `backend/auth/authentication.py` (token → customer_id) and `backend/auth/authorization.py` / `backend/auth/verification.py` (order → owner/email) use small in-memory dictionaries, not a real identity provider or orders database. The interfaces (`CustomerVerificationProvider` protocol, single-sourced `get_order_owner`) are deliberately designed to be swapped for real backends without touching the agent/tool layer.
- **Fresh-database migration gap**: the baseline Alembic migration (`6cc4ab724fa6`) has an intentionally empty `upgrade()` — it assumes the base tables already exist (created by `init_db.py`). Running `alembic upgrade head` alone against a truly empty database will fail on the subsequent `add_tenant_id_to_messages` migration, which alters the (not-yet-existent) `messages` table. Always run `init_db.py` once against a brand-new database before relying on `alembic upgrade head` for later migrations.
- **Guardrails are heuristic, not ML-based**: prompt-injection/abuse/leakage detection uses deterministic regex pattern matching rather than a moderation model or classifier. This is a documented architectural choice (backend enforcement over LLM self-policing) but means novel phrasing can evade a pattern that hasn't been added yet.
- **Ticket listing endpoint has no auth**: `GET /tickets` and `GET /tickets/{id}` are unauthenticated, intended for internal/trusted-network use only — do not expose them publicly without adding access control.
- **Rate limiting is fixed-window**, not a sliding log — simpler and O(1) per check, but allows brief bursts around window boundaries.
- **No horizontal-scaling story for in-memory state**: the WebSocket `ConnectionManager` and per-session `MessageQueue` (`backend/websocket/connection_manager.py`, `message_queue.py`) live in single-process memory, so a session's live connection state doesn't survive a process restart or work across multiple backend replicas without sticky sessions or an external coordination layer.
- Some CI/local test runs are gated on Gemini's free-tier daily quota; quota-exhaustion failures are skipped rather than failed, which can mask a real regression landing at the same time.

## License

No license file is currently included in this repository. Until one is added, all rights are reserved by the project author — do not redistribute or reuse this code without permission. If you intend to open-source this project, add a `LICENSE` file (e.g. MIT, Apache-2.0) at the repository root and reference it here.

---

This is a real, working multilingual support agent, not a prototype — it detects what a customer needs, answers from your actual knowledge base instead of guessing, verifies identity before disclosing protected data, and knows exactly when to step back and bring in a human, so you can drop it into a website and start handling support conversations in any language from day one.
