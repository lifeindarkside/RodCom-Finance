import hashlib
import hmac
import json
import urllib.parse
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


def verify_telegram_hash(data: dict, bot_token: str) -> bool:
    check_hash = data.pop("hash", None)
    if not check_hash:
        return False
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()) if v is not None)
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    hmac_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return hmac_hash == check_hash


def verify_tma_init_data(init_data: str, bot_token: str) -> Optional[dict]:
    parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = chr(10).join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if calculated_hash != received_hash:
        return None
    user_data = parsed.get("user")
    if user_data:
        try:
            return json.loads(user_data)
        except json.JSONDecodeError:
            return None
    return None
