from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_db, require_role
from models import User, AuditLog, UsageLog

router = APIRouter(tags=["admin"])


@router.get("/api/admin/stats")
async def admin_stats(user=Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    now = datetime.now()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    total_users = (await db.execute(select(func.count(User.id)))).scalar()
    login_actions = ["login_tma", "login_widget", "login_bot"]
    active_7d = (await db.execute(select(func.count(func.distinct(UsageLog.user_id))).where(UsageLog.action.in_(login_actions), UsageLog.created_at >= week_ago))).scalar()
    active_30d = (await db.execute(select(func.count(func.distinct(UsageLog.user_id))).where(UsageLog.action.in_(login_actions), UsageLog.created_at >= month_ago))).scalar()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    logins_today = (await db.execute(select(func.count(UsageLog.id)).where(UsageLog.action.in_(login_actions), UsageLog.created_at >= today_start))).scalar()
    logins_7d = (await db.execute(select(func.count(UsageLog.id)).where(UsageLog.action.in_(login_actions), UsageLog.created_at >= week_ago))).scalar()
    logins_30d = (await db.execute(select(func.count(UsageLog.id)).where(UsageLog.action.in_(login_actions), UsageLog.created_at >= month_ago))).scalar()
    logins_tma = (await db.execute(select(func.count(UsageLog.id)).where(UsageLog.action == "login_tma", UsageLog.created_at >= month_ago))).scalar()
    logins_widget = (await db.execute(select(func.count(UsageLog.id)).where(UsageLog.action == "login_widget", UsageLog.created_at >= month_ago))).scalar()
    logins_bot = (await db.execute(select(func.count(UsageLog.id)).where(UsageLog.action == "login_bot", UsageLog.created_at >= month_ago))).scalar()
    top_users_q = (select(UsageLog.user_name, UsageLog.user_id, func.count(UsageLog.id).label("cnt")).where(UsageLog.action.in_(login_actions), UsageLog.created_at >= month_ago).group_by(UsageLog.user_id, UsageLog.user_name).order_by(desc("cnt")).limit(10))
    top_users = (await db.execute(top_users_q)).all()
    tx_7d = (await db.execute(select(func.count(UsageLog.id)).where(UsageLog.action == "create_tx", UsageLog.created_at >= week_ago))).scalar()
    tx_30d = (await db.execute(select(func.count(UsageLog.id)).where(UsageLog.action == "create_tx", UsageLog.created_at >= month_ago))).scalar()
    return {
        "total_users": total_users, "active_7d": active_7d, "active_30d": active_30d,
        "logins_today": logins_today, "logins_7d": logins_7d, "logins_30d": logins_30d,
        "logins_tma": logins_tma, "logins_widget": logins_widget, "logins_bot": logins_bot,
        "tx_created_7d": tx_7d, "tx_created_30d": tx_30d,
        "top_users": [{"name": r[0] or "?", "user_id": r[1], "count": r[2]} for r in top_users],
    }


@router.get("/api/admin/usage")
async def admin_usage(page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=200), user=Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    total = (await db.execute(select(func.count(UsageLog.id)))).scalar()
    offset = (page - 1) * per_page
    q = select(UsageLog).order_by(desc(UsageLog.created_at)).offset(offset).limit(per_page)
    entries = (await db.execute(q)).scalars().all()
    return {
        "total": total, "page": page, "pages": (total + per_page - 1) // per_page,
        "items": [{"id": e.id, "user_name": e.user_name or "?", "telegram_id": e.telegram_id, "action": e.action, "details": e.details, "created_at": e.created_at.isoformat() if e.created_at else None} for e in entries],
    }


@router.get("/api/audit")
async def list_audit(page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=200), user=Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    count_q = select(func.count(AuditLog.id))
    total = (await db.execute(count_q)).scalar()
    offset = (page - 1) * per_page
    q = select(AuditLog).order_by(desc(AuditLog.created_at)).offset(offset).limit(per_page)
    entries = (await db.execute(q)).scalars().all()
    user_ids = set(e.user_id for e in entries if e.user_id)
    users_map = {}
    if user_ids:
        u_res = await db.execute(select(User).where(User.id.in_(user_ids)))
        for u in u_res.scalars().all():
            users_map[u.id] = u.name
    return {
        "total": total, "page": page, "pages": (total + per_page - 1) // per_page,
        "items": [
            {"id": e.id, "user_name": users_map.get(e.user_id, "?"), "action": e.action, "entity_type": e.entity_type, "entity_id": e.entity_id, "details": e.details, "created_at": e.created_at.isoformat() if e.created_at else None}
            for e in entries
        ],
    }
