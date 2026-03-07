from fastapi import APIRouter, Depends, HTTPException, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_db, get_current_user, require_role, audit_log
from models import Collection

router = APIRouter(prefix="/api/collections", tags=["collections"])


@router.get("")
async def list_collections(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Collection).where(Collection.is_active == 1).order_by(Collection.name))
    colls = result.scalars().all()
    return [{"id": c.id, "name": c.name, "collection_type": c.collection_type or "general", "is_active": c.is_active} for c in colls]


@router.put("/{coll_id}/type")
async def update_collection_type(
    coll_id: int, collection_type: str = Form(...),
    user=Depends(require_role("admin")), db: AsyncSession = Depends(get_db),
):
    if collection_type not in ("general", "event"):
        raise HTTPException(status_code=400, detail="Тип должен быть: general или event")
    result = await db.execute(select(Collection).where(Collection.id == coll_id))
    coll = result.scalars().first()
    if not coll:
        raise HTTPException(status_code=404, detail="Сбор не найден")
    coll.collection_type = collection_type
    await db.commit()
    await audit_log(db, int(user["sub"]), "update", "collection", coll.id, f"type -> {collection_type}")
    return {"message": f"Тип сбора '{coll.name}' изменён на {collection_type}"}
