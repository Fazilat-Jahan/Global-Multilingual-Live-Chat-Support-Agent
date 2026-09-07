# Global Multilingual Live Chat Support Agent — Project Summary

A production-grade, embeddable AI support system that talks to customers in their own language, answers only from real company knowledge, verifies identity before touching protected data, and knows exactly when to bring in a human.

**At a glance:** 4 specialist agents · 3 guardrail layers · mid-conversation identity verification · sandboxed iframe embedding · Alembic-managed schema · 5+ languages tested · 18 build phases complete

---

## 1. Why Was This Project Built?

Any business serving customers globally runs into the same wall: customers write in different languages, questions arrive at all hours, and a human team can't realistically staff every language around the clock.

The usual shortcuts don't hold up:
- A generic chatbot answers confidently and sometimes *wrongly*, because it isn't grounded in the company's actual policies.
- A plain FAQ page can't look up a specific order or refund, and can't tell a genuine customer from anyone who happens to guess an order number.
- Routing every unresolved case to a human queue with no structure just buries the support team instead of helping them.
- A widget that isn't properly sandboxed can leak session data into whatever site embeds it.

This project closes those gaps: a support agent that **understands intent**, **answers from real company knowledge instead of guessing**, can **safely take real actions** (like checking an order) only after **verifying who's asking**, and **hands off to a person cleanly** the moment a case needs one — in whatever language the customer showed up speaking, embeddable on any client site with one script tag.

## 2. What Exactly Does the System Do?

From the customer's side, it's a chat widget on a website (or embedded via an iframe loader script on someone else's site). Underneath, four specialist AI agents share the work, handed off natively between them as the conversation moves:

1. **Customer opens the widget** — no account, no login. A message can be typed in any language.
2. **Triage Agent reads it** — detects the language and the intent, then hands off to the right specialist via the OpenAI Agents SDK's native `handoffs`, not custom if/else routing.
3. **The right specialist answers**:
   - FAQ / policy / product questions → **RAG Agent** (grounded in Qdrant, cross-lingual retrieval)
   - Order / refund / ticket requests → **Action Agent** (tools gated by a tool guardrail; protected order data requires a mid-conversation order-ID + email verification first)
   - Requests for a human → **Escalation Agent**
4. **The reply streams back** in the customer's own language, even though a different agent is now answering.
5. **If escalated** — a ticket and summary are created, the human team is notified by Email and Slack, and the customer is told someone will follow up outside the chat.
6. **The conversation survives a reconnect** — closing and reopening the tab resumes the same conversation, not a blank one, with the correct agent context restored.
7. **If an output guardrail trips mid-stream**, the partially-streamed reply is retracted client-side and swapped for safe replacement text — the customer never sees the blocked content.

## 3. Key Technologies Used

| Layer | Technology & Role |
|---|---|
| Frontend | Next.js 14 + TypeScript embeddable widget, Tailwind CSS, WebSocket client for real-time streaming, a standalone one-script iframe loader for third-party embedding |
| Backend | FastAPI (Python 3.11+), serving both REST endpoints and the chat WebSocket |
| Agent orchestration | OpenAI Agents SDK — native handoffs, guardrails, and tool-calling, not custom routing logic |
| LLM | Google Gemini, accessed through its OpenAI-compatible Chat Completions endpoint, with retry policies for transient 5xx/429 failures |
| Vector database | Qdrant, per-tenant collections holding multilingual embeddings so retrieval works across languages |
| Relational database | PostgreSQL — durable conversations, messages, tickets, and knowledge-base ingestion checksums; schema managed by Alembic migrations |
| Cache / sessions | Redis — fast session lookups, rate-limit counters, verification state, and knowledge-base re-ingestion locks |
| Deployment | Docker, Render/Railway (backend), Vercel (frontend), a 5-job CI pipeline (lint, typecheck, test, frontend, security) on every push |

## 4. Architecture Overview

Every message passes through the same shape: origin check → queue → a guardrail check → a routing decision → a specialist agent (behind its own tool guardrails where relevant) → another guardrail check. The routing itself is the Agents SDK's **native handoff mechanism** — the Triage Agent doesn't call a function to decide; it hands the whole conversation to another agent directly.

```
Customer message (any language, no login)
              │
      Origin policy + per-session queue
   (single active request; extras queued)
              │
      Input Guardrails
   (injection · abuse · length · scope)
              │
        Triage Agent
  (detect language + intent)
              │
   ┌──────────┼──────────────┐
   ▼          ▼              ▼
RAG Agent  Action Agent  Escalation Agent
(search    (order/refund/ (ticket + Email/
 knowledge  ticket tools,  Slack, no live
 base via   gated by       takeover)
 Qdrant)    verification)
   │          │              │
   └──────────┼──────────────┘
              ▼
      Output Guardrails
(leakage · safety · language match)
              │
              ▼
   Reply streamed to widget
  (retracted + replaced if a
   guardrail trips mid-stream)
```

- **RAG Agent** only answers from what it retrieves from the knowledge base — if the retrieved content isn't good enough (below a tuned similarity threshold), it says so instead of guessing, or hands off to Escalation. It also distinguishes "no answer found" from "the knowledge base is temporarily down," so it never invents a policy just because Qdrant timed out.
- **Action Agent**'s tools sit behind a guardrail that checks authorization *and* per-session verification status before anything touches real data. An anonymous visitor asking about someone else's order — or their own order before verifying — gets a `VERIFICATION_REQUIRED` challenge instead of any data; the LLM can only request an action, never execute one directly.
- **Escalation Agent** never turns the chat into a live human channel — it packages the case (ticket, summary, notification) and tells the customer help is coming outside the chat. There is no code path anywhere in the system for a human to inject a message into a live session.

## 5. What Makes It Production-Grade?

The difference between this and a weekend chatbot demo is almost entirely in what happens when something goes wrong, when someone tries to misuse it, or when the widget has to live on someone else's website.

- **Guardrails at every boundary** — input checks catch prompt injection, abuse, and oversized messages before Triage ever sees them; output checks catch unsafe replies, language drift (with one automatic corrective retry), and leaked internals before the customer sees them; a streaming-aware retraction path handles a guardrail tripping mid-response.
- **Authorization and identity verification enforced in code** — sensitive tools (order lookup, refunds) are checked against real authorization rules and a rate-limited, session-scoped verification flow in backend code, never left to the LLM to police itself.
- **Durable sessions** — conversations and messages persist in PostgreSQL with a full state machine; Redis handles fast session lookups, always falling back to Postgres on a cache miss or outage. A dropped connection resumes the same conversation with the same agent context, not a fresh one.
- **Resilient to real failures** — transient LLM or network errors are retried with backoff at the model layer; Qdrant timeouts convert into an honest "temporarily unavailable" message instead of a hallucinated answer; rate limiting protects the system under load; failures return a safe message, never a traceback or an API key.
- **Properly sandboxed, embeddable widget** — a one-script loader drops a sandboxed iframe into any client site, restricted by a CSP `frame-ancestors` allowlist and a server-side origin policy that rejects disallowed origins for both HTTP and WebSocket traffic, not just a browser-side CORS block.
- **Schema managed by migrations** — Alembic tracks every schema change (tenant scoping, knowledge-base checksum tracking) instead of ad-hoc table edits.
- **Tested and evaluated** — unit, integration, routing, guardrail, multilingual, and Alembic test suites (over 170 automated tests), plus a fixed evaluation set scoring RAG groundedness and abstention, with an 80%+ coverage gate on pure-logic modules.
- **Actually deployable** — Dockerized (migrations run before the app starts), CI-gated (lint, types, tests, frontend build, dependency vulnerability scan on every push), HTTPS/WSS end to end, with a documented path to Render/Vercel or equivalent hosts.

## 6. Current Scope

The scope was chosen deliberately — every exclusion below was a decision, not an oversight.

**Built & working:**
- Multilingual chat, no login required
- Native multi-agent handoffs
- Grounded RAG answers, with abstention and outage-vs-no-answer distinction
- Authorized order/refund/ticket actions, gated by mid-conversation customer verification
- Real human escalation (ticket + Email/Slack), with no live-takeover path
- Session persistence across reconnects
- One-script sandboxed iframe embedding on any client site
- Streaming responses with mid-stream guardrail retraction
- Per-session concurrent-message queueing with cancellation
- Incremental, checksum-based knowledge-base re-ingestion
- Per-tenant data isolation across Postgres, Redis, and Qdrant
- Alembic-managed schema migrations and a 5-job CI pipeline

**Intentionally not included:**
- Live human takeover inside the chat
- Voice, WhatsApp, or SMS as chat channels
- A full CRM or agent dashboard (only a minimal read-only ticket-listing endpoint)
- Kubernetes, enterprise SSO, custom model training
- Multi-tenant billing / self-serve onboarding (a `TENANT_ID` discriminator provides isolation, not a management plane)

**Known limitations:** authentication/authorization/order-ownership data is currently mock in-memory data (swappable via defined interfaces, not a real identity provider); the baseline Alembic migration assumes the base schema already exists rather than creating it from nothing, so a brand-new database needs `init_db.py` run once before `alembic upgrade head` takes over; guardrail content checks are deterministic regex patterns rather than a trained moderation model; and in-memory WebSocket/queue state doesn't yet have a multi-replica coordination story. See the README's "Known Issues / Limitations" section for the full list.

## 7. Real-World Use Case

Picture an online retailer or SaaS company with customers across several countries and a support team that can't cover every language, every timezone.

They drop `<script src=".../widget-loader.js" data-tenant="default">` onto their site. A customer in Karachi asks about a return policy in Roman Urdu; a customer in Madrid asks where their order is, in Spanish — and before the system reveals anything about that order, it confirms the customer knows the email address it's registered under. Both get an answer immediately, grounded in the company's real policies and real order data — not a guess, and not handed to just anyone who guesses an order number. When a case is genuinely unusual, or the customer just wants a person, it's captured cleanly as a ticket with a summary and routed to the support team by Email and Slack, instead of getting lost in a generic inbox.

**The result:** most first-contact volume gets resolved instantly and correctly, in the customer's own language, with protected data staying protected — and the human team only sees the cases that actually need them.

---

This is a working multilingual support agent, not a prototype — it understands what a customer needs, answers from the business's real knowledge instead of guessing, confirms who it's talking to before disclosing anything sensitive, and knows exactly when to step back and bring in a person.
