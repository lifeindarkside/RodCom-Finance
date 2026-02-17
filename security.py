from datetime import datetime, timedelta
from typing import Optional
from jose import jwt, JWTError
from config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_HOURS

def create_token(user_id: int, telegram_id: int, role: str, name: str) -> str:
    payload = {
        "sub": str(user_id),
        "tid": telegram_id,
        "role": role,
        "name": name,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
