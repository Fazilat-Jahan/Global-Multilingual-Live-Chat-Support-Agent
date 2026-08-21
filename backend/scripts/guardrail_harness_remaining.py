"""Re-runs only the remaining Phase 4 guardrail harness cases (used after a
rate-limit interruption), so already-passed cases aren't retested against
the daily free-tier quota unnecessarily.
"""

import asyncio

from backend.scripts.guardrail_harness import (
    case_authorized_order_access,
    case_no_internal_leakage_on_bad_input,
)


async def main() -> None:
    await case_authorized_order_access()
    await case_no_internal_leakage_on_bad_input()


if __name__ == "__main__":
    asyncio.run(main())
