from fastapi import APIRouter, Depends, HTTPException, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_db, require_role, audit_log, log_usage
from models import User

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("")
async def list_users(user=Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.name))
    users = result.scalars().all()
    return [{"id": u.id, "telegram_id": u.telegram_id, "name": u.name, "role": u.role} for u in users]


@router.put("/{user_id}/role")
async def update_user_role(user_id: int, role: str = Form(...), user=Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    if role not in ("viewer", "treasurer", "admin"):
        raise HTTPException(status_code=400, detail="Роль должна быть: viewer, treasurer, admin")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalars().first()
    if not target:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    target.role = role
    await db.commit()
    await audit_log(db, int(user["sub"]), "role_change", "user", target.id, f"{target.name}: {role}")
    await log_usage(db, int(user["sub"]), int(user["tid"]), user["name"], "role_change", f"{target.name} -> {role}")
    return {"message": f"Роль пользователя {target.name} изменена на {role}"}


@router.post("/register")
async def pre_register_user(telegram_id: int = Form(...), name: str = Form(""), role: str = Form("viewer"), user=Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    if role not in ("viewer", "treasurer", "admin"):
        raise HTTPException(status_code=400, detail="Роль должна быть: viewer, treasurer, admin")
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    existing = result.scalars().first()
    if existing:
        existing.role = role
        if name: existing.name = name
        await db.commit()
        await audit_log(db, int(user["sub"]), "role_change", "user", existing.id, f"{existing.name}: {role} (pre-register update)")
        return {"message": f"Пользователь {existing.name} обновлён, роль: {role}", "id": existing.id}
    new_user = User(telegram_id=telegram_id, name=name or f"User {telegram_id}", role=role)
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    await audit_log(db, int(user["sub"]), "create", "user", new_user.id, f"pre-register tg={telegram_id} role={role}")
    return {"message": f"Пользователь зарегистрирован с ролью: {role}", "id": new_user.id}
