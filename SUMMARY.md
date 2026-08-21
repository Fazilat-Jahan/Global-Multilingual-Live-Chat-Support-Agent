# Global Multilingual Live Chat Support Agent — Project Summary

A production-grade, embeddable AI support system that talks to customers in their own language, answers only from real company knowledge, and knows exactly when to bring in a human.

**At a glance:** 4 specialist agents · 3 guardrail layers · 5+ languages tested · 10 build phases complete

---

## 1. Why Was This Project Built?

Any business serving customers globally runs into the same wall: customers write in different languages, questions arrive at all hours, and a human team can't realistically staff every language around the clock.

The usual shortcuts don't hold up:
- A generic chatbot answers confidently and sometimes *wrongly*, because it isn't grounded in the company's actual policies.
- A plain FAQ page can't look up a specific order or refund.
- Routing every unresolved case to a human queue with no structure just buries the support team instead of helping them.

This project closes that gap: a support agent that **understands intent**, **answers from real company knowledge instead of guessing**, can **safely take real actions** (like checking an order), and **hands off to a person cleanly** the moment a case needs one — in whatever language the customer showed up speaking.

## 2. What Exactly Does the System Do?

From the customer's side, it's a chat widget on a website. Underneath, four specialist AI agents share the work, handed off natively between them as the conversation moves:

1. **Customer opens the widget** — no account, no login. A message can be typed in any language.
2. **Triage Agent reads it** — detects the language and the intent, then hands off to the right specialist.
3. **The right specialist answers**:
   - FAQ / policy / product questions → **RAG Agent**
   - Order / refund / ticket requests → **Action Agent**
   - Requests for a human → **Escalation Agent**
4. **The reply streams back** in the customer's own language, even though a different agent is now answering.
5. **If escalated** — a ticket and summary are created, the human team is notified by Email and Slack, and the customer is told someone will follow up outside the chat.
6. **The conversation survives a reconnect** — closing and reopening the tab resumes the same conversation, not a blank one.

## 3. Key Technologies Used

| Layer | Technology & Role |
|---|---|
| Frontend | Next.js + TypeScript embeddable widget, Tailwind CSS, WebSocket client for real-time streaming |
| Backend | FastAPI (Python), serving both REST endpoints and the chat WebSocket |
| Agent orchestration | OpenAI Agents SDK — native handoffs, guardrails, and tool-calling, not custom routing logic |
| LLM | Google Gemini, accessed through its OpenAI-compatible endpoint |
| Vector database | Qdrant, holding multilingual embeddings so retrieval works across languages |
| Relational database | PostgreSQL — durable conversations, messages, and support tickets |
| Cache / sessions | Redis — fast session lookups and rate-limit counters |
| Deployment | Docker, Render/Railway (backend), Vercel (frontend), CI on every push |

## 4. Architecture Overview

Every message passes through the same shape: a guardrail check, a routing decision, a specialist agent, another guardrail check. The routing itself is the Agents SDK's **native handoff mechanism** — the Triage Agent doesn't call a function to decide; it hands the whole conversation to another agent directly.

```
Customer message (any language, no login)
              │
              ▼
      Input Guardrails
   (injection · abuse · length)
              │
              ▼
        Triage Agent
  (detect language + intent)
              │
   ┌──────────┼──────────────┐
   ▼          ▼              ▼
RAG Agent  Action Agent  Escalation Agent
(search    (order/refund/ (ticket + Email/
 knowledge  ticket tools,  Slack, no live
 base via   authorized)    takeover)
 Qdrant)
   │          │              │
   └──────────┼──────────────┘
              ▼
      Output Guardrails
 (safety · language match)
              │
              ▼
   Reply streamed to widget
       (over WebSocket)
```

- **RAG Agent** only answers from what it retrieves from the knowledge base — if the retrieved content isn't good enough, it says so instead of guessing, or hands off to Escalation.
- **Action Agent**'s tools sit behind a guardrail that checks authorization and business rules *before* anything touches real data — the LLM can only request an action, never execute one directly.
- **Escalation Agent** never turns the chat into a live human channel — it packages the case (ticket, summary, notification) and tells the customer help is coming outside the chat.

## 5. What Makes It Production-Grade?

The difference between this and a weekend chatbot demo is almost entirely in what happens when something goes wrong, or when someone tries to misuse it.

- **Guardrails at every boundary** — input checks catch prompt injection, abuse, and oversized messages before Triage ever sees them; output checks catch unsafe replies, language drift, and leaked internals before the customer sees them.
- **Authorization enforced in code** — sensitive tools (order lookup, refunds) are checked against real authorization rules in backend code, never left to the LLM to police itself.
- **Durable sessions** — conversations and messages persist in PostgreSQL; Redis handles fast session lookups. A dropped connection resumes the same conversation, not a fresh one.
- **Resilient to real failures** — transient LLM or network errors are retried with backoff; rate limiting protects the system under load; failures return a safe message, never a traceback or an API key.
- **Tested and evaluated** — unit, integration, routing, guardrail, and multilingual test suites, plus a fixed evaluation set scoring RAG groundedness and abstention.
- **Actually deployable** — Dockerized, CI-gated (tests + lint on every push), HTTPS/WSS end to end, with a documented path to Render/Vercel or equivalent hosts.

## 6. Current Limitations / MVP Scope

The scope was chosen deliberately — every exclusion below was a decision, not an oversight.

**Built & working:**
- Multilingual chat, no login required
- Native multi-agent handoffs
- Grounded RAG answers, with abstention
- Authorized order/refund/ticket actions
- Real human escalation (ticket + Email/Slack)
- Session persistence across reconnects

**Intentionally not included:**
- Live human takeover inside the chat
- Voice, WhatsApp, or SMS as chat channels
- A full CRM or agent dashboard
- Kubernetes, enterprise SSO, custom model training
- Multi-tenant billing / self-serve onboarding

## 7. Real-World Use Case

Picture an online retailer or SaaS company with customers across several countries and a support team that can't cover every language, every timezone.

They embed this widget on their site or help center. A customer in Karachi asks about a return policy in Roman Urdu; a customer in Madrid asks where their order is, in Spanish. Both get an answer immediately, grounded in the company's real policies and real order data — not a guess. When a case is genuinely unusual, or the customer just wants a person, it's captured cleanly as a ticket with a summary and routed to the support team by Email and Slack, instead of getting lost in a generic inbox.

**The result:** most first-contact volume gets resolved instantly and correctly, in the customer's own language, and the human team only sees the cases that actually need them.

---

This is a working multilingual support agent, not a prototype — it understands what a customer needs, answers from the business's real knowledge instead of guessing, and knows exactly when to step back and bring in a person.
