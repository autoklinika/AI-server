import asyncio
from ai_bridge.gateway.resource_leases import ResourceLeaseNotActive,ResourceLeaseRegistry
from ai_bridge.gateway.scheduler import PriorityScheduler

def test_external_lease_shares_scheduler_with_normal_jobs():
    async def run():
        scheduler=PriorityScheduler(max_concurrency=1,max_queue_size=10);registry=ResourceLeaseRegistry(scheduler,ttl_seconds=30);blocker=await scheduler.acquire(priority=10,source="ventilation");lease=await registry.create(priority=50,source="telegram-media");assert lease["state"]=="queued";assert lease["queue_position"]==1;await scheduler.release(blocker);status=await registry.describe(lease["lease_id"]);assert status["state"]=="active";ticket=await registry.begin_use(lease["lease_id"]);assert ticket.job_id==lease["job_id"];await registry.end_use(lease["lease_id"]);assert (await scheduler.snapshot())["active_count"]==1;await registry.release(lease["lease_id"]);assert (await scheduler.snapshot())["active_count"]==0
    asyncio.run(run())

def test_release_after_use_dispatches_next_job():
    async def run():
        scheduler=PriorityScheduler(max_concurrency=1,max_queue_size=10);registry=ResourceLeaseRegistry(scheduler,ttl_seconds=30);lease=await registry.create(priority=50,source="telegram-chat");await registry.begin_use(lease["lease_id"]);waiting=asyncio.create_task(scheduler.acquire(priority=10,source="ventilation"));await asyncio.sleep(0);await registry.end_use(lease["lease_id"],release=True);ticket=await asyncio.wait_for(waiting,1);assert ticket.source=="ventilation";await scheduler.release(ticket)
    asyncio.run(run())

def test_queued_lease_cannot_be_used_early():
    async def run():
        scheduler=PriorityScheduler(max_concurrency=1,max_queue_size=10);registry=ResourceLeaseRegistry(scheduler,ttl_seconds=30);blocker=await scheduler.acquire(priority=1,source="block");lease=await registry.create(priority=50,source="telegram")
        try:await registry.begin_use(lease["lease_id"])
        except ResourceLeaseNotActive:pass
        else:raise AssertionError("queued lease must not bypass scheduler")
        await registry.release(lease["lease_id"]);await scheduler.release(blocker)
    asyncio.run(run())

def test_expired_idle_lease_is_reaped():
    async def run():
        scheduler=PriorityScheduler(max_concurrency=1,max_queue_size=10);registry=ResourceLeaseRegistry(scheduler,ttl_seconds=0.01);lease=await registry.create(priority=50,source="dead-worker");await asyncio.sleep(0.02);assert await registry.reap_expired()==1;assert await scheduler.job_status(lease["job_id"]) is None
    asyncio.run(run())
