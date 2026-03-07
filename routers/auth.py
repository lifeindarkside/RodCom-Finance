import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_state import pending_auths, cleanup_expired
from bot import bot
from config import BOT_TOKEN, BOT_NAME, ALLOWED_CHAT_ID, ADMIN_IDS
from dependencies import get_db, get_current_user, log_usage
from models import User
from security import create_token, verify_telegram_hash, verify_tma_init_data

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/request")
async def auth_request():
    cleanup_expired()
    auth_id = str(uuid.uuid4())
    pending_auths[auth_id] = {
        "status": "pending",
        "expires": datetime.now() + timedelta(minutes=5),
    }
    bot_url = f"https://t.me/{BOT_NAME}?start=auth_{auth_id}"
    return {"auth_id": auth_id, "bot_url": bot_url}


@router.get("/check/{auth_id}")
async def auth_check(auth_id: str):
    if auth_id not in pending_auths:
        raise HTTPException(status_code=404, detail="Auth session not found or expired")
    session = pending_auths[auth_id]
    if session["status"] == "completed":
        token = session["token"]
        del pending_auths[auth_id]
        return {"status": "completed", "token": token}
    if session["status"] == "cancelled":
        del pending_auths[auth_id]
        return {"status": "cancelled"}
    return {"status": "pending"}


@router.get("/widget")
async def auth_widget(
    id: int, first_name: str, last_name: Optional[str] = None,
    username: Optional[str] = None, photo_url: Optional[str] = None,
    auth_date: int = 0, hash: str = "",
    db: AsyncSession = Depends(get_db),
):
    logging.info(f"Widget auth attempt: id={id}, name={first_name}, hash={hash[:8]}...")
    data = {"id": id, "first_name": first_name, "last_name": last_name, "username": username, "photo_url": photo_url, "auth_date": auth_date, "hash": hash}
    if not verify_telegram_hash(data, BOT_TOKEN):
        raise HTTPException(status_code=401, detail="Ошибка проверки подписи Telegram")
    if datetime.now().timestamp() - auth_date > 86400:
        raise HTTPException(status_code=401, detail="Срок действия авторизации истек")
    try:
        member = await bot.get_chat_member(chat_id=ALLOWED_CHAT_ID, user_id=id)
        logging.info(f"Widget membership check: user={id}, status={member.status}")
        if member.status in ("left", "kicked"):
            raise HTTPException(status_code=403, detail="Вы не состоите в чате комитета. Вступите в чат и попробуйте снова.")
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Widget membership check failed for user={id}: {e}")
        if id not in ADMIN_IDS:
            raise HTTPException(status_code=403, detail="Не удалось проверить членство в чате. Убедитесь, что бот добавлен в чат как администратор.")
    result = await db.execute(select(User).where(User.telegram_id == id))
    user = result.scalars().first()
    if not user:
        role = "admin" if id in ADMIN_IDS else "viewer"
        user = User(telegram_id=id, name=f"{first_name} {last_name or ''}".strip(), role=role)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        role = "admin" if id in ADMIN_IDS else user.role
        if user.role != role:
            user.role = role
            await db.commit()
    token = create_token(user.id, user.telegram_id, user.role, user.name)
    await log_usage(db, user.id, user.telegram_id, user.name, "login_widget")
    return {"token": token}


class TMAAuthRequest(BaseModel):
    init_data: str


@router.post("/tma")
async def auth_tma(body: TMAAuthRequest, db: AsyncSession = Depends(get_db)):
    user_data = verify_tma_init_data(body.init_data, BOT_TOKEN)
    if not user_data:
        raise HTTPException(status_code=401, detail="Невалидные данные Telegram Mini App")
    tg_id = user_data.get("id")
    first_name = user_data.get("first_name", "")
    last_name = user_data.get("last_name", "")
    if not tg_id:
        raise HTTPException(status_code=401, detail="Telegram ID не найден в данных")
    logging.info(f"TMA auth attempt: id={tg_id}, name={first_name}")
    try:
        member = await bot.get_chat_member(chat_id=ALLOWED_CHAT_ID, user_id=tg_id)
        logging.info(f"TMA membership check: user={tg_id}, status={member.status}")
        if member.status in ("left", "kicked"):
            raise HTTPException(status_code=403, detail="Вы не состоите в чате комитета. Вступите в чат и попробуйте снова.")
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"TMA membership check failed for user={tg_id}: {e}")
        if tg_id not in ADMIN_IDS:
            raise HTTPException(status_code=403, detail="Не удалось проверить членство в чате.")
    result = await db.execute(select(User).where(User.telegram_id == tg_id))
    user = result.scalars().first()
    if not user:
        role = "admin" if tg_id in ADMIN_IDS else "viewer"
        user = User(telegram_id=tg_id, name=f"{first_name} {last_name}".strip(), role=role)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        role = "admin" if tg_id in ADMIN_IDS else user.role
        if user.role != role:
            user.role = role
            await db.commit()
    token = create_token(user.id, user.telegram_id, user.role, user.name)
    await log_usage(db, user.id, user.telegram_id, user.name, "login_tma")
    return {"token": token}


@router.get("/me")
async def auth_me(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == int(user["sub"])))
    db_user = result.scalars().first()
    if not db_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return {"id": db_user.id, "telegram_id": db_user.telegram_id, "name": db_user.name, "role": db_user.role}


# Auth redirect page (not under /api/auth prefix)
auth_page_router = APIRouter()


@auth_page_router.get("/auth")
async def auth_page(token: str = Query(None)):
    if not token:
        return HTMLResponse("<h1>Ошибка авторизации</h1><p>Токен отсутствует.</p>", status_code=400)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Авторизация</title></head>
<body><script>
localStorage.setItem('token', '{token}');
window.location.href = '/';
</script></body></html>"""
    return HTMLResponse(html)
