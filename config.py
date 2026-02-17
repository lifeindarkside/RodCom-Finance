import os
import secrets
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
ALLOWED_CHAT_ID = int(os.getenv("ALLOWED_CHAT_ID", "0"))
DB_NAME = os.getenv("DB_NAME", "rodcom.db")

# JWT
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "72"))

# Site
SITE_URL = os.getenv("SITE_URL", "http://localhost:8080")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/app/uploads")
BOT_NAME = os.getenv("BOT_NAME", "")
