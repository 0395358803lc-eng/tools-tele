from __future__ import annotations

import asyncio
import time
import unittest

from app.tg_manager import TgClientManager


class AccountOperationLockTests(unittest.TestCase):
    def test_same_account_features_are_serialized(self):
        async def scenario():
            manager = TgClientManager()
            events = []

            async def run(owner: str, delay: float):
                async with manager.account_operation(101, owner):
                    events.append((owner, "start", time.perf_counter()))
                    self.assertEqual(manager.operation_owner(101), owner)
                    await asyncio.sleep(delay)
                    events.append((owner, "end", time.perf_counter()))

            first = asyncio.create_task(run("phone_check", 0.05))
            await asyncio.sleep(0.005)
            second = asyncio.create_task(run("message_send", 0.01))
            await asyncio.gather(first, second)
            self.assertGreaterEqual(events[2][2], events[1][2])
            self.assertIsNone(manager.operation_owner(101))

        asyncio.run(scenario())

    def test_different_accounts_can_run_in_parallel(self):
        async def scenario():
            manager = TgClientManager()
            starts = {}

            async def run(account_id: int, owner: str):
                async with manager.account_operation(account_id, owner):
                    starts[account_id] = time.perf_counter()
                    await asyncio.sleep(0.05)

            await asyncio.gather(
                run(201, "phone_check"),
                run(202, "profile_update"),
            )
            self.assertLess(abs(starts[201] - starts[202]), 0.03)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
