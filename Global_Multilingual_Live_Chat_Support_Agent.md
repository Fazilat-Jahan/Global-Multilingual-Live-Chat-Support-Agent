# Global Multilingual Live Chat Support Agent

## Production-Grade MVP — Full Build Plan & Technical Specification

**Version:** 1.0  
**Target:** Production-ready MVP (small-scale real usage + strong client demo)  
**Primary Goal:** Build a reusable, embeddable AI customer support system that is secure, multilingual, multi-agent, and genuinely deployable.

---

## 1. Project Overview

### Product

A production-grade, multilingual, AI-powered live customer support agent that can be embedded as a small chat widget on a client's website.

A website visitor opens the chat widget and communicates naturally with the AI support system in their own language.

The system:

- Detects the user's language automatically
- Responds in the user's language
- Understands the user's intent
- Routes the conversation to the appropriate specialist agent
- Retrieves answers from the client's knowledge base (RAG)
- Performs authorized customer/order actions through tools
- Escalates difficult or human-requested cases
- Maintains conversation context
- Applies safety, security and business-rule guardrails
- Provides reliable error handling and observability
- Is deployable as a real small-scale production system

---

## 2. Product Goal

The goal is **not** to build a generic chatbot.

The goal is to build a reusable **AI Customer Support Platform MVP** that can be connected to a business website.

```text
                    CLIENT WEBSITE
                         │
                         ▼
                  ┌─────────────┐
                  │ 💬 Support  │
                  │    Widget   │
                  └──────┬──────┘
                         │
                         ▼
                  AI Support System
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
       FAQ/RAG         Actions       Human
          │              │           Escalation
          ▼              ▼              ▼
       Knowledge       Orders       Support Queue
       Base/API        /Refunds
```

The MVP should be small enough to develop and deploy, but its architecture should **not** need to be thrown away when the client starts receiving real users.

---

## 3. Core User Experience

### Customer Journey

```text
1. Visitor opens website
          ↓
2. Clicks chat widget
          ↓
3. Secure anonymous session is created
          ↓
4. Customer sends message
          ↓
5. Input guardrails validate request
          ↓
6. Triage Agent determines intent
          ↓
7. Native SDK handoff
          ↓
   ┌──────┼──────────┐
   ↓      ↓          ↓
  RAG   Action   Escalation
   │      │          │
   └──────┼──────────┘
          ↓
8. Specialist handles request
          ↓
9. Output validation
          ↓
10. Response streamed to widget
          ↓
11. Conversation/session persisted
          ↓
12. Trace + operational metrics recorded
```

---

## 4. Important Authentication Decision

### Customer login is NOT required for opening chat

This is a public website support widget.

A visitor should be able to:

```text
Open Widget → Start Chat → Ask FAQ
```

without creating an account.

The system creates a **secure anonymous session**.

```text
visitor → secure session_id → WebSocket → conversation
```

### When authentication/authorization becomes necessary

Authentication is required only when the user requests access to private/customer-specific information or actions.

| Request Type                     | Auth Required? |
|----------------------------------|----------------|
| "What is your return policy?"    | No             |
| "Where is order #12345?"         | Yes (verification) |
| "Cancel my order"                | Yes + Authorization |
| "Process my refund"              | Yes + Business rules + possibly human approval |

**MVP Support:**

- Guest (anonymous) sessions
- Optional authenticated customer context
- Authorization checks for protected actions

Do **not** build a complete customer account/authentication platform from scratch unless the client requires it.

### 4.1 Mid-Conversation Verification Flow

When an anonymous user requests a protected action (e.g., "Where is my order #12345?"), the Action Agent triggers a **verification challenge** before executing the tool.

**MVP verification mechanism: Order ID + email match.**

```text
1. User requests protected action
         ↓
2. Action Agent detects auth required
         ↓
3. Agent asks user for verification:
   "To look up your order, please provide the email address
    associated with order #12345."
         ↓
4. User provides email
         ↓
5. Backend verification tool checks:
   verify_customer(order_id="12345", email="user@example.com")
         ↓
6a. Match → Session is upgraded to "verified" for this
    customer_id. Subsequent requests for the same customer
    do not require re-verification within the session.
         ↓
6b. No match → Agent responds:
    "The email address doesn't match our records for that order.
     Please double-check and try again."
         ↓
7. After 3 failed attempts → Agent offers escalation.
```

**Verification scope:** Per-session, per-customer. Once verified for customer X, the user can perform any authorized action for customer X within the same session without re-verifying.

**Verification state:** Stored in Redis session data as `verified_customer_ids: ["cust_123"]`.

**Tool-level enforcement:** Every protected tool checks `session.verified_customer_ids` before execution. If the relevant customer is not verified, the tool returns a structured error that triggers the verification challenge.

**Security constraints:**
- Verification attempts are rate-limited: 5 attempts per session per 10-minute window.
- Failed attempts are logged with `trace_id` for abuse monitoring.
- The email is not stored in conversation messages — it's passed to the verification tool and discarded from the message history after verification.

**Future extensibility:** The verification mechanism is behind an interface (`verify_customer(identifier, credential)`) so it can be swapped for OTP or magic-link verification without changing the agent or tool layer.

---

## 5. High-Level Architecture

```text
                         ┌──────────────────────┐
                         │    CLIENT WEBSITE    │
                         │  Next.js / React     │
                         │  Chat Widget         │
                         └──────────┬───────────┘
                                    │
                              WebSocket / HTTPS
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │       FastAPI        │
                         │    API Gateway       │
                         │                      │
                         │ Auth / Rate Limit    │
                         │ Validation           │
                         │ Session Management   │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │ OpenAI Agents SDK    │
                         │    Triage Agent      │
                         └──────────┬───────────┘
                                    │
               ┌────────────────────┼────────────────────┐
               │                    │                    │
               ▼                    ▼                    ▼
       ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
       │  RAG Agent   │     │ Action Agent │     │ Escalation   │
       │              │     │              │     │ Agent        │
       │ Qdrant Tool  │     │ Business     │     │ Human        │
       │              │     │ Tools        │     │ Handoff      │
       └──────┬───────┘     └──────┬───────┘     └──────┬───────┘
              │                    │                    │
              ▼                    ▼                    ▼
          Qdrant             Client APIs/DB        Support Queue
```

### 5.1 Widget Embedding Mechanism

The widget is embedded via an **iframe** pointing to the hosted widget page (`/widget`).

The client website includes a small loader script (`<script>`) that creates and manages the iframe:

```html
<script>
  (function() {
    var iframe = document.createElement('iframe');
    iframe.src = 'https://<widget-host>/widget?tenant=default';
    iframe.style.cssText = 'position:fixed;bottom:20px;right:20px;width:400px;height:600px;border:none;z-index:9999;';
    iframe.setAttribute('allow', 'clipboard-write');
    iframe.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms allow-popups');
    document.body.appendChild(iframe);
  })();
</script>
```

**Why iframe:** Security isolation — the widget runs in its own origin, preventing the host page's JavaScript from accessing widget DOM, session tokens, or conversation data. The sandbox attribute restricts capabilities.

**Session token handoff:** The session is created entirely within the iframe. The iframe's JavaScript calls `POST /api/sessions/create` directly (same origin as the widget). No tokens cross the iframe boundary to the host page.

**CSP implications for the client website:** The client must allow `frame-src https://<widget-host>` in their Content-Security-Policy. The widget backend sets `X-Frame-Options: ALLOWFROM` (or `Content-Security-Policy: frame-ancestors <client-domain>`) to restrict which sites can embed the widget — preventing clickjacking.

**CORS:** Since the iframe is same-origin with the backend, standard WebSocket and API calls from the widget do not trigger CORS. The `ALLOWED_ORIGINS` configuration (Section 12.3) applies only to direct API access from non-widget clients.

**Responsive behavior:** The loader script detects mobile viewports (width < 768px) and expands the iframe to full-screen with a close button overlay.

**Communication between host page and widget (optional):** The loader script can listen for `postMessage` events from the widget for open/close/minimize commands. Messages are validated against the widget origin. No sensitive data (tokens, conversation content) is passed via `postMessage`.

---

## 6. Technology Stack

### Frontend
- Next.js + TypeScript
- Tailwind CSS
- WebSocket client
- Embeddable chat widget

### Backend
- Python 3.11+
- FastAPI
- WebSockets
- Pydantic
- Uvicorn

### Agent Orchestration
- OpenAI Agents SDK
  - Agents
  - Native handoffs
  - Function tools
  - Input / Output / Tool guardrails
  - Sessions
  - Human-in-the-loop
  - Tracing

### LLM
- Gemini API (gemini-2.0-flash or gemini-2.5-flash recommended for MVP)
- Model provider must be isolated behind a configuration layer

### Embeddings
- Multilingual embedding model (`gemini-embedding-001` or current equivalent)

### Vector Database
- Qdrant (Cloud free tier or self-hosted)

### Persistent Data
- PostgreSQL → durable application data
- Redis → session state, rate limiting, caching

### Deployment (Recommended for MVP)
- Frontend: Vercel
- Backend: Railway or Render
- PostgreSQL: Railway / Supabase / Neon
- Redis: Upstash
- Qdrant: Qdrant Cloud free tier or Docker

---

## 6.1 Model Provider Setup (Gemini + OpenAI Agents SDK)

**Important:** Gemini does not have a native OpenAI platform key. To use Gemini with the OpenAI Agents SDK, we must use Gemini’s OpenAI-compatible endpoint.

### Recommended Implementation (`model_provider.py`)

```python
import os
from dotenv import load_dotenv
from agents import (
    Agent,
    Runner,
    AsyncOpenAI,
    OpenAIChatCompletionsModel,
    set_tracing_disabled
)

load_dotenv()

# Disable tracing because we are not using OpenAI platform keys
set_tracing_disabled(True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-2.0-flash"   # or "gemini-2.5-flash"

# Create OpenAI-compatible client pointing to Gemini
external_client = AsyncOpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

# Wrap it as a Chat Completions model
# Note: Use OpenAIChatCompletionsModel (not the default Responses API model)
gemini_model = OpenAIChatCompletionsModel(
    model=MODEL_NAME,
    openai_client=external_client,
)
```

### Key Rules:

1. **Always use `OpenAIChatCompletionsModel`** — Gemini’s OpenAI-compatible layer only supports Chat Completions, not the Responses API.
2. **Always call `set_tracing_disabled(True)`** — otherwise the SDK tries to send traces to OpenAI and fails.
3. Define `gemini_model` **only once** in `model_provider.py` and import it everywhere.
4. Pass `model=gemini_model` to every `Agent(...)`.
5. Use `Runner.run()` (async) inside FastAPI WebSocket handlers. Avoid `Runner.run_sync()` in async contexts.

### Example Agent Usage:

```python
from model_provider import gemini_model
from agents import Agent

rag_agent = Agent(
    name="RAG Agent",
    instructions="...",
    model=gemini_model,
    tools=[search_knowledge_base],
)
```

### 6.1.1 LLM Fallback Strategy

When the Gemini API is unavailable or rate-limited, the system applies the following resilience strategy:

**Retry with exponential backoff:**
- Base delay: 1 second
- Maximum delay: 30 seconds
- Maximum attempts: 3
- Jitter applied to each delay to prevent thundering herd.

**Circuit breaker:**
- Opens after 5 consecutive failures within a 60-second sliding window.
- Half-open probe after 30 seconds of open state.
- When open, requests fail fast without calling the LLM.

**Graceful degradation:**
- When circuit breaker is open or all retries fail, the user receives:

```text
"I'm experiencing temporary difficulties. Please try again in a few moments, or I can connect you with a support agent."
```

**Secondary model endpoint (optional):**
- Configure `FALLBACK_MODEL_NAME` env var to point to an alternative model endpoint.
- If primary model fails after retries, system attempts the fallback model before triggering degradation.

### 6.1.2 Tracing Contradiction Resolution

**Problem:** Section 6.1 disables OpenAI SDK tracing (`set_tracing_disabled(True)`) because Gemini does not use OpenAI platform keys. However, observability requirements (Sections 15 and 23) list "Tracing" as required.

**Resolution:** Application-level structured logging with correlation IDs is the tracing mechanism for this system. OpenAI SDK tracing is replaced entirely.

**Implementation:**
- Each inbound request receives a `trace_id` (UUID4) generated at the WebSocket handler or HTTP middleware layer.
- The `trace_id` is propagated through all layers: service methods, agent invocations, tool calls, guardrail evaluations, and database queries.
- Logging uses Python `structlog` with JSON output in production, console renderer in development.
- Every structured log entry includes the `trace_id`, enabling full request reconstruction from logs.
- See Section 15.1 for the complete observability specification.

### 6.2 Database Migration Strategy

**Tool: Alembic** (SQLAlchemy's migration framework).

All schema changes are managed via versioned migration scripts in `backend/db/migrations/`.

Alembic configuration file: `backend/alembic.ini`.

Migration environment: `backend/db/migrations/env.py`.

**Workflow:**

```text
1. Developer modifies SQLAlchemy models in backend/db/models.py
         ↓
2. Generate migration:
   alembic revision --autogenerate -m "description"
         ↓
3. Review generated migration script in migrations/versions/
         ↓
4. Apply locally:
   alembic upgrade head
         ↓
5. Commit migration file with the code change
         ↓
6. CI runs: alembic upgrade head (against test database)
         ↓
7. Production deployment runs: alembic upgrade head (before app startup)
```

**CI/CD integration (extends Section 22.1):** Add a `migrate` step to the CI `test` job that runs `alembic upgrade head` against the test PostgreSQL service before running integration tests. Production deployments run `alembic upgrade head` as a pre-start command (Render/Railway pre-deploy hook or Procfile `release` command).

**Rollback:** Each migration includes a `downgrade()` function. Rollback via `alembic downgrade -1`. For MVP, rollback is a manual operation — automated rollback on deployment failure is out of scope.

**Conventions:**
- One migration per logical change.
- Migration filenames include a human-readable description.
- Destructive migrations (drop column, drop table) require explicit confirmation in the migration script docstring.
- All migrations are idempotent where possible.

**Folder structure note:** Add `backend/db/migrations/` to the folder structure (Section 21) — contains Alembic migration scripts.

---

## 7. Agent Architecture

### 7.1 Triage Agent (Entry Point)

**Responsibility:**
- Detect user's language
- Classify intent
- Decide which specialist agent should handle the request
- Detect explicit human requests or low-confidence cases

**Routing:**

```text
FAQ / Policy / Product     → RAG Agent
Order / Account / Action   → Action Agent
Human request / unresolved → Escalation Agent
```

Use the Agents SDK's native `handoffs` mechanism. Do **not** build custom if-else routing.

---

### 7.2 RAG Agent

**Responsibility:** Answer questions using the business knowledge base only.

**Critical Rule:**  
The RAG Agent must **never invent** company policy.

If retrieved information is insufficient:

```text
"I don't have enough information to answer that accurately."
```

Then either clarify or escalate.

---

### 7.3 Action Agent

**Responsibility:** Perform customer-specific operations through controlled tools.

**Initial Tools:**
- `lookup_order_status()`
- `check_refund_status()`
- `create_support_ticket()`

**Future Tools (with strict controls):**
- `request_refund()`
- `cancel_order()`
- `update_shipping_address()`

### Tool Definition Pattern

Always use the `@function_tool` decorator from the Agents SDK:

```python
from agents import function_tool

@function_tool
def lookup_order_status(order_id: str) -> str:
    """Look up the current status of a customer's order.

    Args:
        order_id: The order ID provided by the customer.
    """
    # Mock or real DB/API call
    mock_orders = {"12345": "Shipped, arriving in 2 days", "67890": "Processing"}
    return mock_orders.get(order_id, "Order ID not found. Please double-check the order number.")
```

**Rules:**
- The docstring (especially the Args section) is what the LLM sees — write it clearly.
- Return plain strings or simple serializable data.
- Define tools **before** the Agent definitions that use them.
- Sensitive tools must have Tool Guardrails + Authorization checks.

---

### 7.4 Escalation Agent

Handles:
- Explicit human requests
- Unresolved questions
- Low-confidence situations
- Sensitive cases
- Actions requiring human approval

**Flow:**
1. Generate structured summary of the conversation
2. Save conversation
3. Create support ticket / queue item
4. Mark session as `ESCALATED`
5. Send notification to human support team (Email + Slack) with ticket details and conversation summary
6. Inform the customer with this message (in the user's language):

> “Aapki request human support team ko forward kar di gayi hai. Hamari team jald aapse email/WhatsApp par contact karegi.”

**Important:**  
There is **no live human takeover** inside the chat widget in this MVP.  
Human agents will contact the user **outside the chat** via Email or WhatsApp.

---

## 8. Action Security Model (Very Important)

The LLM must **never** directly control sensitive business operations.

Correct flow:

```text
LLM → Tool Request → Tool Guardrail → Authorization Check → 
Business Rule Validation → Optional Human Approval → Actual API/DB operation
```

**Example:**

```text
User: Cancel my order
      ↓
Action Agent calls cancel_order(order_id)
      ↓
Authorization: Does this order belong to the customer?
      ↓
Business Rule: Is cancellation allowed at this stage?
      ↓
Human approval required? → Yes/No
      ↓
Execute only if all checks pass
```

---

## 9. Guardrails Architecture

Use the Agents SDK guardrails at the correct boundaries:

- **Input Guardrails** → Run at the start of the workflow
- **Output Guardrails** → Run on the final agent output
- **Tool Guardrails** → Run around each function-tool invocation

### Input Guardrail checks:
- Prompt injection attempts
- Abuse / malicious content
- Excessive input length
- Unsupported requests

### Output Guardrail checks:
- Safety
- Language consistency
- Policy compliance
- Accidental leakage of sensitive information

### Tool Guardrail checks:
- Authorization
- Business rule validation
- Input validation for every sensitive tool

### 9.1 Input Length / Size Limits

| Parameter | Limit | Action on Exceed |
|-----------|-------|------------------|
| Single message length | 2,000 characters | Reject with friendly error |
| Message payload size | 8 KB | WebSocket frame rejected |
| Messages per conversation | 200 | Auto-close with summary, suggest new conversation |
| Conversation history sent to LLM | 50 most recent messages | Older messages truncated (FIFO) |
| File attachments | Not supported in MVP | Rejected with explanation |

Limits are enforced at the WebSocket handler layer before any LLM processing.

### 9.2 Streaming Response and Output Guardrail Interaction

**Strategy: Post-completion guardrail with buffered streaming.**

The LLM response is streamed from the model, and `response_delta` events are sent to the frontend in real-time for UX responsiveness.

The output guardrail runs on the **complete accumulated response** after the final delta is received (i.e., when the SDK's `Runner.run()` completes).

**If the output guardrail passes:** A `response_completed` event is sent. No further action needed — the user has already seen the streamed content.

**If the output guardrail fails (blocks the response):**
1. A `response_retracted` event is sent to the frontend:
   ```json
   {
     "type": "response_retracted",
     "reason": "safety",
     "replacement": "I'm sorry, I'm unable to provide that information. Can I help you with something else?"
   }
   ```
2. The frontend replaces the streamed message content with the `replacement` text.
3. The blocked response is logged server-side with `trace_id` and guardrail violation details, but NOT stored in the conversation history. The replacement message is stored instead.

**Why post-completion (not mid-stream):** Running guardrails on partial text produces unreliable results (incomplete sentences may false-positive). Post-completion is simpler, more accurate, and acceptable for MVP because the guardrail checks (safety, PII, policy) rarely trigger on well-prompted agents. The risk window (unsafe content visible during streaming before retraction) is mitigated by strong agent system prompts and input guardrails that filter malicious triggers upstream.

**Frontend implementation:** The frontend must track the current streaming message ID. On receiving `response_retracted`, it replaces the content of that message in the UI. The `MessageList` component must support content replacement for the most recent assistant message.

---

## 10. Multilingual Strategy

No separate translation agent is required.

**Rule for every customer-facing agent:**

> Always respond in the same language the user wrote in, unless the user explicitly requests another language.

**Important Implementation Note:**  
This instruction must be repeated in **every specialist agent’s** system prompt (Triage, RAG, Action, Escalation).  
When a handoff happens, the new agent’s instructions become active. Relying only on the Triage Agent’s instruction is not enough.

Use multilingual embeddings so that:
- Knowledge base can be primarily in English (or business source language)
- Users can ask in Urdu, Roman Urdu, Arabic, Spanish, French, etc.
- Correct documents are still retrieved (cross-lingual retrieval)

Recommended embedding model: `gemini-embedding-001` (or current equivalent)

---

## 11. Session Architecture

Every widget conversation receives a secure session.

**Conversation States:**
```text
ACTIVE
WAITING_FOR_USER
WAITING_FOR_HUMAN
ESCALATED
RESOLVED
CLOSED
```

**Recommended Data Models:**

**Conversation**
- id
- session_id
- customer_id (nullable)
- status
- detected_language
- created_at
- updated_at
- escalated_at

**Message**
- id
- conversation_id
- role
- content
- agent
- created_at
- metadata

### 11.1 Session Expiry & Cleanup

| Session Type | Inactivity Expiry | Max Lifetime |
|--------------|-------------------|--------------|
| Anonymous | 24 hours | 30 days |
| Authenticated | 7 days | 30 days |

- Redis TTL is set on every interaction (sliding expiry).
- Expired sessions: conversation state is retained in PostgreSQL (for audit), Redis keys are evicted automatically via TTL.
- A background cleanup task runs every 6 hours to mark stale `ACTIVE` conversations as `CLOSED` if last interaction exceeds the inactivity threshold.
- Cleanup is implemented as a FastAPI background task using `asyncio.create_task` on startup.

### 11.2 Redis Failure / Fallback

If Redis is unavailable, the system degrades gracefully:

| Component | Fallback Behavior |
|-----------|-------------------|
| Sessions | Fall back to in-memory dictionary (LRU, max 1000 entries). Data is non-durable — acceptable for short outages. |
| Rate limiting | Falls back to in-memory sliding window per-process. Limits are approximate in multi-process deployments during outage. |
| Caching | Disabled; requests go directly to source. |

- Health check endpoint reports `redis: degraded`.
- System logs a WARNING on every Redis connection failure.
- Auto-reconnect attempts every 5 seconds.
- Once Redis recovers, new sessions use Redis; in-memory sessions drain naturally.

---

## 12. WebSocket Architecture

**Backend Events (stable protocol for frontend):**

```text
connected
message_received
agent_started
agent_handoff
tool_started
tool_completed
response_delta
response_completed
escalation
error
```

Note: `response_retracted` is also part of the protocol — see Section 9.2 for details.

Frontend should not need to understand internal agent implementation.

**Reliability requirements:**
- Reconnect handling
- Session restoration
- Heartbeat
- Duplicate message protection
- Timeout handling

### 12.1 WebSocket Authentication

**Anonymous session flow:**
1. Client makes initial HTTP handshake via `POST /api/sessions/create`.
2. Server returns a signed session token (HMAC-SHA256): `{ session_id, token, expires_at }`.
3. Client passes the token as a query parameter `?token=<value>` on WebSocket upgrade.
4. Server validates HMAC signature and expiry before accepting the upgrade.

**Authenticated sessions (for protected actions):**
- Require a separate JWT bearer token passed via `Sec-WebSocket-Protocol` header.

**Token expiry:**
- Anonymous sessions: 24 hours.
- Authenticated sessions: configurable.

### 12.2 WebSocket Heartbeat Protocol

**Server-side:**
- Sends `ping` frame every 30 seconds.
- Client must respond with `pong` within 10 seconds.
- If 3 consecutive pongs are missed, server closes the connection with code `1001`.

**Client-side reconnect:**
- Immediate first attempt, then exponential backoff: 1s, 2s, 4s, 8s, max 30s.
- Maximum 10 reconnection attempts.
- On reconnect, client sends:

```json
{
  "type": "session_restore",
  "session_id": "<session_id>",
  "last_message_id": "<last_message_id>"
}
```

- Server replays missed messages from `last_message_id`.

### 12.3 CORS & Origin Policy

- Allowed origins configured via `ALLOWED_ORIGINS` env var (comma-separated list).
- Default (development): `http://localhost:3000`.
- Production: must be explicitly set to the client's website domain(s).
- WebSocket upgrade requests are validated against the same origin list via the `Origin` header.

**CORS headers:**
- `Access-Control-Allow-Origin`: from allowed list, not `*`
- `Access-Control-Allow-Methods`: `GET, POST, OPTIONS`
- `Access-Control-Allow-Headers`: `Content-Type, Authorization`
- `Access-Control-Max-Age`: `86400`

Requests from non-allowed origins receive HTTP `403`.

### 12.4 Concurrent Message Handling

**Strategy: Server-side queuing with single-active-request per session.**

Each session processes **one user message at a time**. If the server receives a new `user_message` while a prior message is still being processed (LLM call in-flight), the behavior is:

```text
Message arrives while processing
         ↓
Server enqueues the new message
         ↓
Server sends acknowledgment:
{ "type": "message_queued", "position": 1 }
         ↓
When current processing completes
         ↓
Server dequeues and processes the next message
```

**Queue limit:** Maximum 2 messages queued per session. If the queue is full, the server responds with `{ "type": "error", "code": "QUEUE_FULL", "message": "Please wait for the current response to complete." }`.

**Cancellation:** The frontend MAY send a `{ "type": "cancel_request" }` message. On receipt, the server:
1. Sets a cancellation flag on the in-flight processing task.
2. The LLM call is NOT forcibly aborted (to avoid partial state corruption), but the response is discarded once complete.
3. Server sends `{ "type": "request_cancelled" }` and processes the next queued message.

**Frontend behavior:** The `ChatInput` component disables the send button and shows a "thinking" indicator while a response is streaming. The input field remains editable so the user can compose their next message, but submission is throttled — the frontend queues at most 1 pending message locally and displays a subtle "message queued" indicator.

**Why not cancellation-first:** Forcibly aborting LLM calls mid-execution risks orphaned tool calls, partial state writes, or inconsistent conversation history. The queue-and-drain approach is safer for MVP.

---

## 13. Rate Limiting

Apply rate limiting at the API layer:

- Per IP
- Per session
- Per customer (if authenticated)

Protect:
- Gemini / LLM quota
- Server resources
- Qdrant
- Database
- Abuse surface

### 13.1 Rate Limiting Specifics

| Scope | Limit | Window | Algorithm |
|-------|-------|--------|----------|
| Per IP | 60 requests | 1 minute | Sliding window (Redis) |
| Per session | 20 messages | 1 minute | Token bucket |
| Per session | 200 messages | 1 hour | Fixed window |
| Per authenticated customer | 30 messages | 1 minute | Token bucket |
| WebSocket connections per IP | 5 concurrent | — | Counter |
| LLM calls (global) | 100 requests | 1 minute | Sliding window |

**Response when rate-limited:**
- HTTP: `429` with `Retry-After` header (seconds).
- WebSocket: send `{ "type": "error", "code": "RATE_LIMITED", "retry_after": <seconds> }`.

**Storage:** Redis with key pattern `ratelimit:{scope}:{identifier}:{window}`.

---

## 14. Error Handling Principles

Never expose to the user:
- Tracebacks
- API keys
- Database errors
- Internal URLs
- System prompts

Convert technical failures into safe customer-facing messages.

**Example:**
```text
Internal: Qdrant connection timeout
Customer: "I'm temporarily unable to access the support knowledge base. 
Please try again or I can connect you with a support agent."
```

### 14.1 Retry & Timeout Strategy

| Operation | Timeout | Retries | Backoff |
|-----------|---------|---------|----------|
| LLM API call | 30 seconds | 3 | Exponential (1s, 2s, 4s) + jitter |
| Qdrant query | 5 seconds | 2 | Fixed 500ms |
| PostgreSQL query | 10 seconds | 1 | None (fail fast) |
| Redis operation | 2 seconds | 2 | Fixed 200ms |
| External notification (Email/Slack) | 10 seconds | 3 | Exponential (2s, 4s, 8s) |
| WebSocket message delivery | 5 seconds | 0 | None (client handles via reconnect) |

**Rules:**
- All retries use idempotency checks where applicable.
- Non-retryable errors (4xx from LLM, auth failures) are never retried.
- Circuit breaker wraps LLM calls (see Section 6.1.1).

---

## 15. Observability

Track at minimum:

**Operational:**
- Total / Active / Resolved / Escalated conversations
- Average response latency
- LLM errors
- Tool errors
- RAG failures
- Guardrail triggers
- Rate-limit events
- WebSocket disconnects

**AI-specific:**
- Handoff rate
- Tool-call rate
- RAG retrieval success rate
- RAG abstention rate
- Human escalation rate

Use application-level structured logging with trace correlation IDs (see Section 6.1.2 and 15.1) + Prometheus metrics. OpenAI SDK tracing is disabled as Gemini uses the Chat Completions compatibility layer (see Section 6.1).

### 15.1 Observability Implementation

This section specifies the application-level observability stack that replaces OpenAI SDK tracing.

**Structured logging:**
- Library: `structlog` with JSON formatter in production, console renderer in development.
- Every log entry includes: `trace_id`, `session_id`, `timestamp`, `level`, `event`, `agent_name` (when applicable).

**Metrics:**
- Expose Prometheus-compatible metrics at `GET /metrics`.
- Key metrics:

| Metric | Type | Labels |
|--------|------|--------|
| `conversations_total` | counter | `status` |
| `message_latency_seconds` | histogram | `agent` |
| `llm_requests_total` | counter | `model`, `status` |
| `llm_request_duration_seconds` | histogram | — |
| `guardrail_triggers_total` | counter | `type`, `rule` |
| `rag_retrieval_score` | histogram | — |
| `escalations_total` | counter | `reason` |
| `websocket_connections_active` | gauge | — |
| `rate_limit_hits_total` | counter | `scope` |

**Trace correlation:**
- Every inbound WebSocket message generates a `trace_id` (UUID4).
- This ID is passed to all service methods, agent invocations, tool calls, and DB queries.
- Logged with every structured log entry.
- Returned to frontend in message metadata for end-to-end correlation.

**Health endpoint** (`GET /health`):

```json
{
  "status": "ok",
  "version": "1.0.0",
  "uptime": 86400,
  "dependencies": {
    "postgres": "ok",
    "redis": "ok",
    "qdrant": "ok",
    "llm": "ok"
  }
}
```

Per-dependency status values: `ok` | `degraded` | `down`.

---

## 16. Privacy & Data Retention

- Do not blindly log full conversations
- Mask / redact sensitive fields (email, phone, payment info)
- Define clear retention policy (configurable per client)
- Support data deletion requests

### 16.1 Data Retention Policy Defaults

| Data Type | Retention Period | Action at Boundary |
|-----------|-----------------|--------------------|
| Conversation messages | 90 days | Soft-deleted (`is_deleted=true`, content nullified, metadata retained for analytics) |
| Support tickets | 1 year | Archived then hard-deleted |
| Session data (Redis) | Per TTL (see Section 11.1) | Auto-expires via Redis TTL |
| Audit logs | 1 year | Hard-deleted |

**PII handling:**
- PII fields (email, phone, name in messages) are redacted at retention boundary using a regex-based scrubber.

**Data deletion requests:**
- Process within 72 hours.
- Deletes all conversation content, nullifies PII in tickets, removes embeddings containing customer data from Qdrant.

**Configuration:** Retention periods are environment variables:
- `RETENTION_MESSAGES_DAYS=90`
- `RETENTION_TICKETS_DAYS=365`
- `RETENTION_AUDIT_DAYS=365`

---

## 17. Human Support Queue (Minimum MVP)

```text
Escalation → Support Ticket Created → Notification (Email + Slack) → Human Agent contacts user via Email / WhatsApp
```

### What happens on Escalation:

1. AI generates a structured summary
2. A support ticket is created in the database
3. Session status is marked as `ESCALATED`
4. Human support team receives notification via:
   - Email
   - Slack (recommended)
5. Customer sees this message in the chat (in their language):

> “Aapki request human support team ko forward kar di gayi hai. Hamari team jald aapse email/WhatsApp par contact karegi.”

6. Human agent then contacts the user **outside the chat widget** (via Email or WhatsApp)

### Ticket fields:
- ticket_id
- conversation_id
- priority
- reason
- summary
- customer_reference (email / phone if available)
- status (`OPEN`, `ASSIGNED`, `IN_PROGRESS`, `RESOLVED`, `CLOSED`)
- created_at
- assigned_to

### Notes:
- There is **no live human chat takeover** inside the widget in this MVP.
- A full enterprise support dashboard is **out of scope** for v1.
- Basic ticket listing (for internal use) can be added later if needed.

### 17.1 Escalation Notification Implementation

**Email:**
- Send via SMTP (configurable via environment variables: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ESCALATION_EMAIL_TO`).
- Template includes: `ticket_id`, priority, reason, summary, `customer_reference`, conversation link.
- Sent asynchronously (fire-and-forget with retry per Section 14.1).

**Slack:**
- Send via Slack Incoming Webhook (`SLACK_WEBHOOK_URL` env var).
- Payload: structured message block with `ticket_id`, priority, reason, summary, `customer_reference`.
- Format as Slack Block Kit message.

**Failure handling:**
- If notification delivery fails after all retries, log ERROR with full context and set ticket field `notification_status = "FAILED"`.
- Do NOT block escalation flow — the ticket is still created and visible in the database.
- A periodic reconciliation task (every 15 minutes) retries failed notifications up to 3 additional times.

---

## 18. Knowledge Base & RAG Quality

**Pipeline:**
```text
Business Documents → Loader → Cleaning → Chunking → 
Metadata → Multilingual Embedding → Qdrant
```

**Metadata should include:**
- document_id, source, title, category, product, language, version, created_at, updated_at

**RAG must be evaluated for:**
- Retrieval quality
- Groundedness
- Relevance
- Abstention behavior
- Multilingual retrieval accuracy

Create a fixed evaluation dataset before calling the system production-ready.

### 18.1 RAG Chunking Strategy

**Chunking method:** Recursive character text splitter.

| Parameter | Value |
|-----------|-------|
| Chunk size | 512 tokens (measured by tiktoken `cl100k_base` tokenizer) |
| Chunk overlap | 64 tokens |
| Separators (priority order) | `\n\n`, `\n`, `. `, ` ` |

**Metadata preserved per chunk:**
- `document_id`, `chunk_index`, `total_chunks`, `source`, `title`, `category`, `language`

**Qdrant collection configuration:**

| Setting | Value |
|---------|-------|
| Collection name | `knowledge_base` |
| Vector size | 768 (gemini-embedding-001 output dimension) |
| Distance metric | `Cosine` |
| HNSW index | `m=16`, `ef_construct=100` |

**Retrieval parameters:**
- Top-k: 5
- Score threshold: 0.70 (chunks below this cosine similarity are discarded)

### 18.2 Knowledge Base Update & Re-ingestion

**Trigger:** Re-ingestion is **manually triggered** via a CLI command or admin API endpoint. There is no automatic file-watching in the MVP.

```bash
# CLI command
python -m backend.rag.ingestion --source knowledge_base/ --mode incremental

# Admin API (protected, requires admin auth)
POST /api/admin/knowledge-base/reingest
{ "mode": "incremental", "source": "knowledge_base/" }
```

**Modes:**

| Mode | Behavior | When to use |
|------|----------|-------------|
| `full` | Deletes all existing chunks for the tenant, re-embeds and re-indexes all documents. | Major content restructuring, initial setup, or recovery from corruption. |
| `incremental` | Compares document checksums (SHA-256 of file content) against stored metadata. Only processes new or modified documents. Deletes chunks for removed documents. | Routine content updates (new FAQs, policy changes). |

**Atomicity:** Chunk replacement for a single document is atomic — old chunks are deleted and new chunks are inserted within a single Qdrant batch operation. During re-indexing, the old chunks remain queryable until the new chunks are committed. There is **no downtime** — the knowledge base is always available.

**Checksum tracking:** Each document's SHA-256 checksum is stored in PostgreSQL (`knowledge_document` table: `document_id`, `file_path`, `checksum`, `chunk_count`, `last_ingested_at`, `tenant_id`). The incremental mode queries this table to determine which documents have changed.

**Concurrency protection:** A distributed lock (Redis key `reingest_lock:{tenant_id}`, TTL 30 minutes) prevents concurrent re-ingestion runs. If a lock is held, the new request is rejected with a clear error message.

**Logging:** Each re-ingestion run logs: documents processed, documents skipped (unchanged), documents deleted, chunks created, total duration, and any errors. Logged at INFO level with `trace_id`.

**Post-ingestion validation (recommended):** After re-ingestion, run a quick smoke test: embed a known query and verify that expected documents appear in the top-k results. This is a manual step for MVP; automation is deferred.

---

## 19. Testing Strategy

### Must Have Tests:
- Unit tests (tools, auth, rate limiting, chunking, etc.)
- Integration tests (FastAPI → Agent → Tool → DB)
- Agent routing tests (FAQ → RAG, Order → Action, Human → Escalation)
- Guardrail tests (prompt injection, unauthorized actions, etc.)
- Multilingual tests (English, Urdu, Roman Urdu, Arabic, Spanish...)
- RAG evaluation suite
- Basic load testing (10 → 25 → 50 concurrent users)

---

## 20. Production MVP Scope

### MUST HAVE

**AI**
- Triage + RAG + Action + Escalation agents
- Native handoffs
- Function tools
- Input / Output / Tool guardrails
- Multilingual responses
- RAG grounding + abstention
- Session memory

**Backend**
- FastAPI + WebSocket
- Persistent conversation state
- Authorization for protected actions
- Rate limiting
- Retries / timeouts
- Structured errors
- Health checks

**Data**
- PostgreSQL
- Qdrant
- Redis (sessions + rate limiting)

**Frontend**
- Embeddable chat widget
- Streaming responses
- Reconnect handling
- Error & escalation states
- Mobile responsive

**Security**
- HTTPS / WSS
- Secure secrets management
- Tenant isolation (light)
- Authorization
- Input validation
- Privacy-aware logging

**Quality & Operations**
- Unit + Integration + Agent + Guardrail + RAG tests
- Basic load testing
- Tracing + metrics + logging
- Deployment + CI checks

---

### OUT OF SCOPE (v1)

- Full Zendesk / CRM clone
- Voice support
- WhatsApp / SMS / Email channels
- Complex multi-tenant billing
- Kubernetes / microservices
- Enterprise SSO
- Custom model training
- Advanced analytics platform
- Multi-region infrastructure

### 20.1 Environment Variable Inventory

All runtime configuration is provided via environment variables.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | Yes | — | Gemini API key |
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `REDIS_URL` | Yes | — | Redis connection string |
| `QDRANT_URL` | Yes | — | Qdrant server URL |
| `QDRANT_API_KEY` | No | — | Qdrant Cloud API key |
| `SESSION_SECRET` | Yes | — | HMAC secret for session tokens (min 32 chars) |
| `ALLOWED_ORIGINS` | Yes | `http://localhost:3000` | Comma-separated allowed CORS origins |
| `SMTP_HOST` | No | — | SMTP server for escalation emails |
| `SMTP_PORT` | No | `587` | SMTP port |
| `SMTP_USER` | No | — | SMTP username |
| `SMTP_PASSWORD` | No | — | SMTP password |
| `ESCALATION_EMAIL_TO` | No | — | Recipient for escalation emails |
| `SLACK_WEBHOOK_URL` | No | — | Slack webhook for escalation notifications |
| `MODEL_NAME` | No | `gemini-2.0-flash` | LLM model identifier |
| `FALLBACK_MODEL_NAME` | No | — | Secondary model endpoint (see 6.1.1) |
| `LOG_LEVEL` | No | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `RETENTION_MESSAGES_DAYS` | No | `90` | Message retention period |
| `RETENTION_TICKETS_DAYS` | No | `365` | Ticket retention period |
| `RETENTION_AUDIT_DAYS` | No | `365` | Audit log retention period |
| `RATE_LIMIT_ENABLED` | No | `true` | Enable/disable rate limiting |
| `MAX_CONCURRENT_WS` | No | `1000` | Max concurrent WebSocket connections |
| `ENVIRONMENT` | No | `development` | Runtime environment (development, staging, production) |

### 20.2 Secrets Management

- All secrets are provided via environment variables — never committed to source control.
- `.env` file used for local development only; `.env.example` contains placeholder keys with no real values.
- Production: secrets injected via deployment platform's secret management (Render Environment Groups, Railway Variables, or Vercel Environment Variables).
- `SESSION_SECRET` must be at least 32 characters, generated via `openssl rand -hex 32`.
- API keys (`GEMINI_API_KEY`, `QDRANT_API_KEY`) are validated on startup — application refuses to start if required secrets are missing or malformed.
- Secrets are never logged, never included in error responses, never exposed via health check endpoints.
- Rotation: API keys can be rotated by updating the environment variable and restarting the service. No downtime rotation is not required for MVP.

### 20.3 Tenant Isolation (Light)

The MVP is designed as a **single-tenant deployment per client**. Each client gets their own deployed instance of the system (separate backend, database, Redis, Qdrant collection). This is the simplest isolation model and avoids cross-tenant data leakage by design.

However, all data models include a `tenant_id` field (default: `"default"`) to enable future multi-tenant migration without schema changes.

**PostgreSQL:** Every table includes a `tenant_id` column. All queries include `WHERE tenant_id = :tenant_id`. A database-level row security policy is recommended but not required for MVP.

**Qdrant:** The collection is scoped per tenant via the collection name pattern `{tenant_id}_knowledge_base`. MVP uses `default_knowledge_base`.

**Redis:** All keys are prefixed with `{tenant_id}:` (e.g., `default:session:{session_id}`, `default:ratelimit:{scope}:{id}:{window}`).

**RAG queries:** Always include a `tenant_id` metadata filter to prevent cross-tenant retrieval.

**Configuration:** The `tenant_id` is derived from the `TENANT_ID` environment variable (default: `"default"`).

**Environment variable inventory note:** See Section 20.1 for the full environment variable inventory. Add `TENANT_ID` (optional, default `default`) — tenant identifier for data scoping.

---

## 21. Recommended Folder Structure

```text
global-support-agent/
│
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── model_provider.py
│   │
│   ├── api/
│   │   ├── health.py
│   │   ├── sessions.py
│   │   └── tickets.py
│   │
│   ├── websocket/
│   │   ├── handler.py
│   │   ├── events.py
│   │   └── connection_manager.py
│   │
│   ├── agents/
│   │   ├── triage.py
│   │   ├── rag.py
│   │   ├── action.py
│   │   └── escalation.py
│   │
│   ├── tools/
│   │   ├── knowledge_search.py
│   │   ├── order_tools.py
│   │   └── support_tools.py
│   │
│   ├── guardrails/
│   │   ├── input.py
│   │   ├── output.py
│   │   ├── tools.py
│   │   └── security.py
│   │
│   ├── auth/
│   │   ├── authentication.py
│   │   └── authorization.py
│   │
│   ├── services/
│   │   ├── session_service.py
│   │   ├── conversation_service.py
│   │   ├── escalation_service.py
│   │   └── rate_limit_service.py
│   │
│   ├── db/
│   │   ├── models.py
│   │   ├── repository.py
│   │   └── connection.py
│   │
│   ├── rag/
│   │   ├── embeddings.py
│   │   ├── retrieval.py
│   │   ├── chunking.py
│   │   └── ingestion.py
│   │
│   └── tests/
│       ├── unit/
│       ├── integration/
│       ├── agents/
│       ├── guardrails/
│       └── rag/
│
├── frontend/
│   ├── components/
│   │   ├── ChatWidget.tsx
│   │   ├── ChatWindow.tsx
│   │   ├── MessageList.tsx
│   │   └── ChatInput.tsx
│   ├── lib/
│   │   ├── websocket.ts
│   │   └── session.ts
│   └── ...
│
├── knowledge_base/
│   ├── faq/
│   ├── policies/
│   └── products/
│
├── evaluation/
│   ├── rag_cases.json
│   ├── routing_cases.json
│   └── multilingual_cases.json
│
├── docker/
├── .env.example
├── docker-compose.yml
├── README.md
└── pyproject.toml
```

---

## 22. Development Phases

| Phase | Focus                              | Deliverable                                      |
|-------|------------------------------------|--------------------------------------------------|
| 1     | Foundation                         | Project runs locally                             |
| 2     | RAG Pipeline                       | Grounded answers from knowledge base             |
| 3     | Multi-Agent System                 | Correct routing via native handoffs              |
| 4     | Guardrails                         | Unsafe requests blocked safely                   |
| 5     | Sessions + Persistence             | Conversation survives reconnects                 |
| 6     | Live Chat (WebSocket + Widget)     | Real-time chat experience                        |
| 7     | Human Escalation                   | AI can hand off real cases                       |
| 8     | Production Hardening               | Rate limiting, retries, secrets, tenant isolation|
| 9     | Testing & Evaluation              | Known quality baseline                           |
| 10    | Deployment                         | Publicly accessible production MVP               |

### 22.1 CI/CD Pipeline Specification

The CI pipeline runs on GitHub Actions and must pass before any merge to `main`.

**Trigger:**

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```

**Jobs:**

| Job | Steps |
|-----|-------|
| `lint` | `ruff check backend/` · `ruff format --check backend/` |
| `typecheck` | `pyright backend/` (or `mypy`) |
| `test` | `pytest backend/tests/unit/ --cov=backend --cov-fail-under=80` · `pytest backend/tests/integration/` (with test PostgreSQL + Redis via services) · `pytest backend/tests/guardrails/` · `pytest backend/tests/agents/` |
| `frontend` | `npm run lint` (ESLint) · `npm run build` (Next.js production build) |
| `security` | `pip-audit` (Python dependency vulnerability scan) |

**Branch protection:** Require 1 approval + all CI jobs passing before merge to `main`.

**Deployment:** Triggered automatically on push to `main` via platform hooks (Render/Railway auto-deploy from GitHub). No manual deployment step required.

---

## 23. Definition of Done

The project is considered complete when all items below are checked:

### Customer Experience
- [ ] Can open chat widget without creating an account
- [ ] Can communicate in multiple languages
- [ ] Receives answers in the user's language
- [ ] Can ask FAQ / product / policy questions
- [ ] Can request order information
- [ ] Can request human support
- [ ] On escalation, receives clear message that human team will contact via Email/WhatsApp
- [ ] Conversation survives reconnects

### Agents
- [ ] Triage, RAG, Action, Escalation agents work
- [ ] Native handoffs work correctly
- [ ] Tools work
- [ ] Session context is maintained

### Safety
- [ ] Input, Output, and Tool guardrails work
- [ ] Protected actions require authorization
- [ ] Sensitive actions can require human approval
- [ ] Prompt injection scenarios are tested

### RAG
- [ ] Knowledge base ingestion works
- [ ] Multilingual retrieval works
- [ ] Unsupported questions do not generate fabricated answers
- [ ] Evaluation dataset exists

### Infrastructure & Operations
- [ ] PostgreSQL + Qdrant + Redis working
- [ ] Rate limiting working
- [ ] Health checks working
- [ ] Secrets protected
- [ ] HTTPS / WSS working
- [ ] Structured logging with trace IDs + Prometheus metrics endpoint + per-dependency health checks available (see Section 15.1)
- [ ] Basic load test completed
- [ ] Backend + Frontend deployed
- [ ] CI checks passing

---

## 24. Core Build Philosophy

**Build the smallest system that is genuinely deployable — not the smallest demo.**

Do not add features merely because they sound "enterprise."

Every production feature must answer one question:

> **Does this protect the customer, protect the business, improve reliability, or make the AI system trustworthy?**

If yes → include it.  
If not → defer it.

---

## 25. Final Architecture Principle

```text
LLM              = reasoning / language / interpretation
Agents SDK       = orchestration (agents, handoffs, tools, guardrails, sessions)
Backend          = security + business rules + authorization
Database         = durable state
Qdrant           = knowledge retrieval
Frontend         = customer experience
Infrastructure   = reliability + scaling
```

**Never make the LLM responsible for things that deterministic backend code can enforce.**

---

**End of Document**

This specification is ready to be handed to Claude Code (or any strong coding agent) for implementation.
