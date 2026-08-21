"""Re-runs only the escalation-status case from persistence_harness.py after
a rate-limit interruption."""

import asyncio

from backend.scripts.persistence_harness import case_escalation_status_transition

if __name__ == "__main__":
    asyncio.run(case_escalation_status_transition())
