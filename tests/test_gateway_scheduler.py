import asyncio

from ai_bridge.gateway.scheduler import PriorityScheduler, SchedulerQueueFull


def test_priority_order_is_respected_for_waiting_jobs() -> None:
    async def run() -> None:
        scheduler = PriorityScheduler(max_concurrency=1, max_queue_size=10)
        first = await scheduler.acquire(priority=50, source="first")
        low_task = asyncio.create_task(
            scheduler.acquire(priority=200, source="low")
        )
        await asyncio.sleep(0)
        high_task = asyncio.create_task(
            scheduler.acquire(priority=10, source="ventilation")
        )
        await asyncio.sleep(0)

        await scheduler.release(first)
        high = await asyncio.wait_for(high_task, 1)
        assert high.source == "ventilation"
        assert not low_task.done()

        await scheduler.release(high)
        low = await asyncio.wait_for(low_task, 1)
        assert low.source == "low"
        await scheduler.release(low)

    asyncio.run(run())


def test_same_priority_remains_fifo() -> None:
    async def run() -> None:
        scheduler = PriorityScheduler(max_concurrency=1, max_queue_size=10)
        first = await scheduler.acquire(priority=1, source="block")
        a_task = asyncio.create_task(scheduler.acquire(priority=50, source="a"))
        await asyncio.sleep(0)
        b_task = asyncio.create_task(scheduler.acquire(priority=50, source="b"))
        await asyncio.sleep(0)

        await scheduler.release(first)
        a = await asyncio.wait_for(a_task, 1)
        assert a.source == "a"
        await scheduler.release(a)

        b = await asyncio.wait_for(b_task, 1)
        assert b.source == "b"
        await scheduler.release(b)

    asyncio.run(run())


def test_queue_limit_is_enforced() -> None:
    async def run() -> None:
        scheduler = PriorityScheduler(max_concurrency=1, max_queue_size=1)
        first = await scheduler.acquire(priority=1, source="block")
        waiting = asyncio.create_task(
            scheduler.acquire(priority=50, source="waiting")
        )
        await asyncio.sleep(0)

        try:
            await scheduler.acquire(priority=50, source="overflow")
        except SchedulerQueueFull:
            pass
        else:
            raise AssertionError("expected SchedulerQueueFull")

        waiting.cancel()
        try:
            await waiting
        except asyncio.CancelledError:
            pass
        await scheduler.release(first)

    asyncio.run(run())


def test_cancellation_after_dispatch_does_not_leak_active_slot() -> None:
    async def run() -> None:
        scheduler = PriorityScheduler(max_concurrency=1, max_queue_size=10)
        first = await scheduler.acquire(priority=1, source="block")
        waiting = asyncio.create_task(
            scheduler.acquire(priority=50, source="cancel-after-dispatch")
        )
        await asyncio.sleep(0)

        # release() grants the waiting job a slot by resolving its future, but
        # this task resumes before the waiting task can return from acquire().
        await scheduler.release(first)
        waiting.cancel()
        try:
            await waiting
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("expected waiting task cancellation")

        snapshot = await scheduler.snapshot()
        assert snapshot["active_count"] == 0
        assert snapshot["queued_count"] == 0

        next_ticket = await asyncio.wait_for(
            scheduler.acquire(priority=50, source="next"), 1
        )
        assert next_ticket.source == "next"
        await scheduler.release(next_ticket)

    asyncio.run(run())
