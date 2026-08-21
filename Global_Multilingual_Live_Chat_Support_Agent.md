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

Frontend should not need to understand internal agent implementation.

**Reliability requirements:**
- Reconnect handling
- Session restoration
- Heartbeat
- Duplicate message protection
- Timeout handling

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

Use OpenAI Agents SDK tracing + application-level metrics/logging.

---

## 16. Privacy & Data Retention

- Do not blindly log full conversations
- Mask / redact sensitive fields (email, phone, payment info)
- Define clear retention policy (configurable per client)
- Support data deletion requests

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
- [ ] Tracing + logging + basic metrics available
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
