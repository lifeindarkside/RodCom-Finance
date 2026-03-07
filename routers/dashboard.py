from fastapi import APIRouter, Depends
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from config import BOT_NAME
from dependencies import get_db, get_current_user
from models import User, Transaction, Collection

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
async def dashboard(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    income_q = select(func.coalesce(func.sum(Transaction.amount), 0)).where(Transaction.type == "income")
    total_income = (await db.execute(income_q)).scalar()
    expense_q = select(func.coalesce(func.sum(Transaction.amount), 0)).where(Transaction.type == "expense")
    total_expense = (await db.execute(expense_q)).scalar()
    cat_q = (
        select(func.coalesce(Transaction.category, "Прочее"), func.sum(Transaction.amount))
        .where(Transaction.type == "expense")
        .group_by(func.coalesce(Transaction.category, "Прочее"))
        .order_by(desc(func.sum(Transaction.amount)))
    )
    expense_cats = (await db.execute(cat_q)).all()
    recent_q = select(Transaction).order_by(desc(Transaction.date)).limit(10)
    recent = (await db.execute(recent_q)).scalars().all()
    users_q = select(func.count(User.id))
    total_users = (await db.execute(users_q)).scalar()
    coll_q = select(Collection).where(Collection.is_active == 1)
    colls = (await db.execute(coll_q)).scalars().all()
    coll_balances = []
    for c in colls:
        c_income = (await db.execute(select(func.coalesce(func.sum(Transaction.amount), 0)).where(Transaction.collection_id == c.id, Transaction.type == "income"))).scalar()
        c_expense = (await db.execute(select(func.coalesce(func.sum(Transaction.amount), 0)).where(Transaction.collection_id == c.id, Transaction.type == "expense"))).scalar()
        payers_count = (await db.execute(
            select(func.count(func.distinct(Transaction.payer_name)))
            .where(Transaction.collection_id == c.id, Transaction.type == "income", Transaction.payer_name.isnot(None))
        )).scalar()
        coll_balances.append({
            "id": c.id, "name": c.name,
            "collection_type": c.collection_type or "general",
            "income": c_income, "expense": c_expense,
            "balance": c_income - c_expense,
            "payers_count": payers_count or 0,
        })
    recent_coll_ids = set(t.collection_id for t in recent if t.collection_id)
    coll_names = {}
    if recent_coll_ids:
        coll_res = await db.execute(select(Collection).where(Collection.id.in_(recent_coll_ids)))
        for c in coll_res.scalars().all():
            coll_names[c.id] = c.name
    recent_user_ids = set(t.created_by for t in recent if t.created_by)
    recent_users = {}
    if recent_user_ids:
        u_res = await db.execute(select(User).where(User.id.in_(recent_user_ids)))
        for u in u_res.scalars().all():
            recent_users[u.id] = u.name
    expense_categories = [{"category": name, "amount": amt} for name, amt in expense_cats]
    return {
        "balance": total_income - total_expense,
        "total_income": total_income,
        "total_expense": total_expense,
        "total_users": total_users,
        "expense_by_category": expense_categories,
        "coll_balances": coll_balances,
        "recent_transactions": [
            {
                "id": t.id, "type": t.type, "amount": t.amount,
                "payer_name": t.payer_name,
                "collection_name": coll_names.get(t.collection_id, ""),
                "category": t.category, "description": t.description,
                "date": t.date.isoformat() if t.date else None,
                "photo_path": t.photo_path,
                "created_by_name": recent_users.get(t.created_by, ""),
            }
            for t in recent
        ],
    }


@router.get("/categories")
async def list_categories(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Transaction.category).distinct().where(Transaction.category.isnot(None)).order_by(Transaction.category))
    return [row[0] for row in result.all()]


@router.get("/config")
async def get_config():
    return {"bot_name": BOT_NAME}
