from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_db, get_current_user, require_role, audit_log, log_usage
from models import User, Transaction, Collection
from uploads import save_upload, delete_upload

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.get("")
async def list_transactions(
    page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100),
    type: Optional[str] = None, category: Optional[str] = None,
    collection_id: Optional[int] = None,
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    q = select(Transaction).order_by(desc(Transaction.date))
    count_q = select(func.count(Transaction.id))
    if type:
        q = q.where(Transaction.type == type)
        count_q = count_q.where(Transaction.type == type)
    if category:
        q = q.where(Transaction.category == category)
        count_q = count_q.where(Transaction.category == category)
    if collection_id:
        q = q.where(Transaction.collection_id == collection_id)
        count_q = count_q.where(Transaction.collection_id == collection_id)
    total = (await db.execute(count_q)).scalar()
    offset = (page - 1) * per_page
    result = await db.execute(q.offset(offset).limit(per_page))
    transactions = result.scalars().all()
    user_ids = set(t.user_id for t in transactions if t.user_id)
    user_ids.update(t.created_by for t in transactions if t.created_by)
    users_map = {}
    if user_ids:
        users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
        for u in users_result.scalars().all():
            users_map[u.id] = u.name
    coll_ids = set(t.collection_id for t in transactions if t.collection_id)
    colls_map = {}
    if coll_ids:
        colls_result = await db.execute(select(Collection).where(Collection.id.in_(coll_ids)))
        for c in colls_result.scalars().all():
            colls_map[c.id] = c.name
    return {
        "total": total, "page": page, "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "items": [
            {
                "id": t.id, "type": t.type, "amount": t.amount, "category": t.category,
                "collection_name": colls_map.get(t.collection_id, "\u2014"),
                "collection_id": t.collection_id,
                "payer_name": t.payer_name or "\u2014",
                "description": t.description,
                "date": t.date.isoformat() if t.date else None,
                "photo_path": t.photo_path,
                "user_name": users_map.get(t.user_id, "\u2014"),
                "created_by_name": users_map.get(t.created_by, "\u2014"),
            }
            for t in transactions
        ],
    }


@router.post("")
async def create_transaction(
    type: str = Form(...), amount: float = Form(...),
    category: str = Form(None), collection_id: int = Form(None),
    collection_name: str = Form(None), collection_type: str = Form(None),
    payer_name: str = Form(None), description: str = Form(None),
    user_id: int = Form(None), date: str = Form(None),
    photos: List[UploadFile] = File(None),
    user=Depends(require_role("treasurer", "admin")),
    db: AsyncSession = Depends(get_db),
):
    if collection_name and not collection_id:
        res = await db.execute(select(Collection).where(Collection.name == collection_name))
        existing = res.scalars().first()
        if existing:
            collection_id = existing.id
        else:
            new_coll = Collection(name=collection_name, collection_type=collection_type or "event")
            db.add(new_coll)
            await db.commit()
            await db.refresh(new_coll)
            collection_id = new_coll.id
    photo_paths = []
    if photos:
        for photo in photos:
            fname = await save_upload(photo)
            if fname:
                photo_paths.append(fname)
    photo_path = ",".join(photo_paths) if photo_paths else None
    tx_date = datetime.now()
    if date:
        try:
            tx_date = datetime.fromisoformat(date)
        except ValueError:
            pass
    tx = Transaction(
        type=type, amount=amount, category=category,
        collection_id=collection_id, payer_name=payer_name,
        description=description, user_id=user_id,
        created_by=int(user["sub"]), date=tx_date, photo_path=photo_path,
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    await audit_log(db, int(user["sub"]), "create", "transaction", tx.id, f"{tx.type} {tx.amount}")
    await log_usage(db, int(user["sub"]), int(user["tid"]), user["name"], "create_tx", f"{tx.type} {tx.amount}")
    return {"id": tx.id, "message": "Операция создана"}


@router.put("/{tx_id}")
async def update_transaction(
    tx_id: int, type: str = Form(None), amount: float = Form(None),
    category: str = Form(None), description: str = Form(None),
    date: str = Form(None), photos: List[UploadFile] = File(None),
    delete_photos: str = Form(None),
    user=Depends(require_role("treasurer", "admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Transaction).where(Transaction.id == tx_id))
    tx = result.scalars().first()
    if not tx:
        raise HTTPException(status_code=404, detail="Операция не найдена")
    if user["role"] == "treasurer" and tx.created_by != int(user["sub"]):
        raise HTTPException(status_code=403, detail="Вы можете редактировать только свои операции")
    if type is not None: tx.type = type
    if amount is not None: tx.amount = amount
    if category is not None: tx.category = category
    if description is not None: tx.description = description
    if date:
        try: tx.date = datetime.fromisoformat(date)
        except ValueError: pass
    existing_photos = [p for p in (tx.photo_path or "").split(",") if p]
    if delete_photos:
        for dp in delete_photos.split(","):
            dp = dp.strip()
            if dp and dp in existing_photos:
                delete_upload(dp)
                existing_photos.remove(dp)
    if photos:
        for photo in photos:
            fname = await save_upload(photo)
            if fname:
                existing_photos.append(fname)
    tx.photo_path = ",".join(existing_photos) if existing_photos else None
    await db.commit()
    await audit_log(db, int(user["sub"]), "update", "transaction", tx.id, f"{tx.type} {tx.amount}")
    await log_usage(db, int(user["sub"]), int(user["tid"]), user["name"], "update_tx", f"tx#{tx.id}")
    return {"message": "Операция обновлена"}


@router.delete("/{tx_id}")
async def delete_transaction(tx_id: int, user=Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Transaction).where(Transaction.id == tx_id))
    tx = result.scalars().first()
    if not tx:
        raise HTTPException(status_code=404, detail="Операция не найдена")
    if tx.photo_path:
        for p in tx.photo_path.split(","):
            p = p.strip()
            if p:
                delete_upload(p)
    await db.delete(tx)
    await db.commit()
    await audit_log(db, int(user["sub"]), "delete", "transaction", tx_id, f"{tx.type} {tx.amount}")
    await log_usage(db, int(user["sub"]), int(user["tid"]), user["name"], "delete_tx", f"tx#{tx_id}")
    return {"message": "Операция удалена"}
