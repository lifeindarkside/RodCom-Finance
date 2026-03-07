from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models import User, AuditLog, UsageLog
from security import decode_token

security = HTTPBearer(auto_error=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    if not credentials:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Недействительный токен")
    user_id = int(payload.get("sub"))
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return {
        "sub": str(user.id),
        "tid": user.telegram_id,
        "role": user.role,
        "name": user.name,
    }


def require_role(*roles):
    async def checker(user=Depends(get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return user
    return checker


async def audit_log(db: AsyncSession, user_id: int, action: str, entity_type: str, entity_id: int = None, details: str = None):
    entry = AuditLog(user_id=user_id, action=action, entity_type=entity_type, entity_id=entity_id, details=details)
    db.add(entry)
    await db.commit()


async def log_usage(db: AsyncSession, user_id: int = None, telegram_id: int = None, name: str = None, action: str = "", details: str = None):
    entry = UsageLog(user_id=user_id, telegram_id=telegram_id, user_name=name, action=action, details=details)
    db.add(entry)
    await db.commit()
