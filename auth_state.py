from datetime import datetime, timedelta
from typing import Dict, Any

# Simple in-memory storage for pending authorizations
# auth_id -> { "status": "pending" | "completed" | "cancelled", "token": str, "user_data": dict, "expires": datetime }
pending_auths: Dict[str, Dict[str, Any]] = {}

def cleanup_expired():
    now = datetime.now()
    expired = [k for k, v in pending_auths.items() if v["expires"] < now]
    for k in expired:
        del pending_auths[k]
