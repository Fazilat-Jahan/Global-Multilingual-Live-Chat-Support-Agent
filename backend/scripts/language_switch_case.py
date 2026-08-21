"""Isolated re-run of the mid-conversation language-switch case from
routing_harness.py, to avoid free-tier rate limits when re-testing alone.

Run with: python -m backend.scripts.language_switch_case
"""

import asyncio

from backend.scripts.routing_harness import run_language_switch_case

if __name__ == "__main__":
    asyncio.run(run_language_switch_case())
