from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import AuditLog

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
async def list_audit(
    limit: int = Query(100, ge=1, le=500),
    action: str | None = None,
    account_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        q = q.where(AuditLog.action == action)
    if account_id is not None:
        q = q.where(AuditLog.account_id == account_id)
    res = await db.execute(q)
    return [{
        "id": row.id,
        "action": row.action,
        "account_id": row.account_id,
        "detail": row.detail or {},
        "created_at": row.created_at,
    } for row in res.scalars().all()]
