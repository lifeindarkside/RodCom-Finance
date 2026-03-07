import logging
import os
import shutil
import uuid
import mimetypes
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import hmac
import hashlib
from jose import jwt, JWTError
from sqlalchemy import select, func, desc, text
from sqlalchemy.ext.asyncio import AsyncSession
from config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_HOURS, UPLOAD_DIR, BOT_TOKEN, BOT_NAME, ALLOWED_CHAT_ID, ADMIN_IDS
import s3_storage
from compliance import router as compliance_router

def verify_telegram_hash(data: dict, bot_token: str) -> bool:
    check_hash = data.pop("hash", None)
    if not check_hash:
        return False
    data_check_string = "\n".join([f"{k}={v}" for k, v in sorted(data.items()) if v is not None])
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    hmac_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return hmac_hash == check_hash

def verify_tma_init_data(init_data: str, bot_token: str) -> dict:
    import urllib.parse
    parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = chr(10).join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if calculated_hash != received_hash:
        return None
    import json
    user_data = parsed.get("user")
    if user_data:
        try:
            return json.loads(user_data)
        except json.JSONDecodeError:
            return None
    return None

from database import AsyncSessionLocal, engine, Base
from models import User, Transaction, AuditLog, UsageLog, Collection

app = FastAPI(title="РодКом Финансы", docs_url="/api/docs")
app.include_router(compliance_router)
security = HTTPBearer(auto_error=False)

os.makedirs(UPLOAD_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def save_upload(photo: UploadFile) -> str | None:
    if not photo or not photo.filename:
        return None
    ext = os.path.splitext(photo.filename)[1] or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    content = await photo.read()
    if s3_storage.is_configured():
        content_type = photo.content_type or mimetypes.guess_type(filename)[0] or 'image/jpeg'
        if s3_storage.upload(content, filename, content_type):
            return filename
        raise HTTPException(status_code=500, detail="Ошибка загрузки файла в хранилище")
    else:
        filepath = os.path.join(UPLOAD_DIR, filename)
        with open(filepath, "wb") as fb:
            fb.write(content)
        return filename

def delete_upload(filename: str):
    if s3_storage.is_configured():
        s3_storage.delete(filename)
    local_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(local_path):
        os.remove(local_path)

@app.get("/uploads/{filename}")
async def serve_upload(filename: str):
    if '..' in filename or '/' in filename or '\\' in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    local_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.isfile(local_path):
        return FileResponse(local_path, headers={"Cache-Control": "public, max-age=86400"})
    if s3_storage.is_configured():
        data = s3_storage.download(filename)
        if data:
            ct = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
            return Response(content=data, media_type=ct, headers={"Cache-Control": "public, max-age=86400"})
    raise HTTPException(status_code=404, detail="File not found")

def create_token(user_id: int, telegram_id: int, role: str, name: str) -> str:
    payload = {
        "sub": str(user_id),
        "tid": telegram_id,
        "role": role,
        "name": name,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Недействительный токен")

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    if not credentials:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    payload = decode_token(credentials.credentials)
    user_id = int(payload.get("sub"))
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return {
        "sub": str(user.id),
        "tid": user.telegram_id,
        "role": user.role,
        "name": user.name
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

import asyncio
from bot import start_bot, bot

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        try:
            await conn.execute(text("ALTER TABLE collections ADD COLUMN collection_type TEXT DEFAULT 'general'"))
            logging.info("Added collection_type column to collections table")
        except Exception:
            pass
    asyncio.create_task(start_bot())

from auth_state import pending_auths, cleanup_expired
from config import BOT_NAME

@app.get("/api/auth/request")
async def auth_request():
    cleanup_expired()
    auth_id = str(uuid.uuid4())
    pending_auths[auth_id] = {
        "status": "pending",
        "expires": datetime.now() + timedelta(minutes=5)
    }
    bot_url = f"https://t.me/{BOT_NAME}?start=auth_{auth_id}"
    return {"auth_id": auth_id, "bot_url": bot_url}

@app.get("/api/auth/check/{auth_id}")
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

@app.get("/api/auth/widget")
async def auth_widget(
    id: int, first_name: str, last_name: Optional[str] = None,
    username: Optional[str] = None, photo_url: Optional[str] = None,
    auth_date: int = 0, hash: str = "",
    db: AsyncSession = Depends(get_db)
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
            raise HTTPException(status_code=403, detail=f"Не удалось проверить членство в чате. Убедитесь, что бот добавлен в чат как администратор.")
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

from pydantic import BaseModel

class TMAAuthRequest(BaseModel):
    init_data: str

@app.post("/api/auth/tma")
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

@app.get("/api/auth/me")
async def auth_me(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == int(user["sub"])))
    db_user = result.scalars().first()
    if not db_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return {"id": db_user.id, "telegram_id": db_user.telegram_id, "name": db_user.name, "role": db_user.role}

@app.get("/auth")
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

@app.get("/api/dashboard")
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

@app.get("/api/transactions")
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

@app.post("/api/transactions")
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

@app.get("/api/collections")
async def list_collections(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Collection).where(Collection.is_active == 1).order_by(Collection.name))
    colls = result.scalars().all()
    return [{"id": c.id, "name": c.name, "collection_type": c.collection_type or "general", "is_active": c.is_active} for c in colls]

@app.put("/api/collections/{coll_id}/type")
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

@app.put("/api/transactions/{tx_id}")
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

@app.delete("/api/transactions/{tx_id}")
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

@app.get("/api/users")
async def list_users(user=Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.name))
    users = result.scalars().all()
    return [{"id": u.id, "telegram_id": u.telegram_id, "name": u.name, "role": u.role} for u in users]

@app.put("/api/users/{user_id}/role")
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

@app.get("/api/audit")
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

@app.post("/api/users/register")
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

@app.get("/api/categories")
async def list_categories(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Transaction.category).distinct().where(Transaction.category.isnot(None)).order_by(Transaction.category))
    return [row[0] for row in result.all()]

@app.get("/api/admin/stats")
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

@app.get("/api/admin/usage")
async def admin_usage(page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=200), user=Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    total = (await db.execute(select(func.count(UsageLog.id)))).scalar()
    offset = (page - 1) * per_page
    q = select(UsageLog).order_by(desc(UsageLog.created_at)).offset(offset).limit(per_page)
    entries = (await db.execute(q)).scalars().all()
    return {
        "total": total, "page": page, "pages": (total + per_page - 1) // per_page,
        "items": [{"id": e.id, "user_name": e.user_name or "?", "telegram_id": e.telegram_id, "action": e.action, "details": e.details, "created_at": e.created_at.isoformat() if e.created_at else None} for e in entries],
    }

@app.get("/api/config")
async def get_config():
    return {"bot_name": BOT_NAME}

@app.get("/")
async def serve_index():
    return FileResponse("static/index.html")

@app.get("/{path:path}")
async def serve_spa(path: str):
    static_path = os.path.join("static", path)
    if os.path.isfile(static_path):
        return FileResponse(static_path)
    return FileResponse("static/index.html")
