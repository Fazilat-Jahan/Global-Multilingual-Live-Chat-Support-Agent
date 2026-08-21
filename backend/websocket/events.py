"""The stable WebSocket event protocol. The frontend only needs to know
these event shapes — never internal agent/tool implementation details.

Server -> client events:
    connected           {type, session_id}
    message_received    {type, message_id}
    agent_started        {type, agent}
    agent_handoff        {type, from, to}
    tool_started          {type, tool, agent}
    tool_completed        {type, tool, agent, result}
    response_delta        {type, delta, agent}
    response_completed    {type, text, agent}
    escalation             {type, agent}
    error                   {type, message}
    ping                    {type}   (heartbeat)

Client -> server events:
    user_message   {type, message_id, content}
    pong           {type}   (heartbeat ack)
"""

CONNECTED = "connected"
MESSAGE_RECEIVED = "message_received"
AGENT_STARTED = "agent_started"
AGENT_HANDOFF = "agent_handoff"
TOOL_STARTED = "tool_started"
TOOL_COMPLETED = "tool_completed"
RESPONSE_DELTA = "response_delta"
RESPONSE_COMPLETED = "response_completed"
ESCALATION = "escalation"
ERROR = "error"
PING = "ping"

USER_MESSAGE = "user_message"
PONG = "pong"


def build_event(kind: str, **payload) -> dict:
    return {"type": kind, **payload}
