import asyncio
from sqlalchemy import delete, select, update

from backend.app.db import AsyncSessionLocal
from backend.app.models import Account, AppSetting, BulkJob
from backend.app.tenant import system_scope, tenant_scope

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"

async def cleanup():
    with system_scope():
        async with AsyncSessionLocal() as db:
            for model in (AppSetting, BulkJob, Account):
                await db.execute(delete(model).where(model.user_id.in_([A, B])))
            await db.commit()

async def seed():
    for uid, phone, suffix in ((A, "+84990000001", "a"), (B, "+84990000002", "b")):
        with tenant_scope(uid):
            async with AsyncSessionLocal() as db:
                db.add(Account(phone=phone, session_file=f"test_{suffix}", status="disconnected"))
                db.add(AppSetting(key=f"user:{uid}:rate_min", value="1.0"))
                db.add(BulkJob(id=f"tenant-test-{suffix}", type="test", status="queued", total=0))
                await db.commit()
async def check_tenant(uid, own_phone, other_phone, other_job):
    with tenant_scope(uid):
        async with AsyncSessionLocal() as db:
            phones = (await db.execute(select(Account.phone).order_by(Account.id))).scalars().all()
            assert phones == [own_phone], (uid, phones)
            other = await db.scalar(select(Account).where(Account.phone == other_phone))
            assert other is None
            other_id = await db.scalar(select(Account.id).where(Account.phone == other_phone))
            assert other_id is None
            result = await db.execute(update(BulkJob).where(BulkJob.id == other_job).values(status="hacked"))
            assert result.rowcount == 0, result.rowcount
            result = await db.execute(delete(BulkJob).where(BulkJob.id == other_job))
            assert result.rowcount == 0, result.rowcount
            await db.commit()

async def cross_write_blocked():
    blocked = False
    with tenant_scope(A):
        async with AsyncSessionLocal() as db:
            db.add(BulkJob(user_id=B, id="tenant-cross-write", type="test", status="queued", total=0))
            try:
                await db.commit()
            except PermissionError:
                blocked = True
                await db.rollback()
    assert blocked, "cross-tenant INSERT was not blocked"
async def main():
    await cleanup()
    try:
        await seed()
        await check_tenant(A, "+84990000001", "+84990000002", "tenant-test-b")
        await check_tenant(B, "+84990000002", "+84990000001", "tenant-test-a")
        await cross_write_blocked()
        print("TENANT_GUARD_PASS")
    finally:
        await cleanup()

if __name__ == "__main__":
    asyncio.run(main())
