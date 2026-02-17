import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

# Add project root to path
sys.path.append(os.getcwd())

from handlers import common
from models import User
from database import get_db
from sqlalchemy.future import select

# Mock aiogram types
class MockUser:
    def __init__(self, id, full_name, username):
        self.id = id
        self.full_name = full_name
        self.username = username
        self.is_bot = False

class MockChat:
    def __init__(self, id):
        self.id = id
        self.type = 'private'

class MockMessage:
    def __init__(self, user):
        self.from_user = user
        self.chat = MockChat(user.id)
        self.text = "/start"
        self.answer = AsyncMock()

async def test_bot_start_command():
    print("--- Testing /start command logic ---")
    
    # Setup
    user_id = 123456789
    allowed_chat_id = int(os.getenv("ALLOWED_CHAT_ID", 0))
    print(f"Allowed Chat ID: {allowed_chat_id}")
    
    mock_user = MockUser(user_id, "Test User", "testuser")
    mock_message = MockMessage(mock_user)
    
    # Mock Bot
    mock_bot = AsyncMock()
    # Mock get_chat_member to return member
    mock_member = MagicMock()
    mock_member.status = "member"
    mock_bot.get_chat_member.return_value = mock_member
    
    # Execute handler
    print("Executing cmd_start handler...")
    await common.cmd_start(mock_message, mock_bot)
    
    # Verify response
    if mock_message.answer.called:
        args, kwargs = mock_message.answer.call_args
        text = args[0]
        reply_markup = kwargs.get('reply_markup')
        
        print("\n[SUCCESS] Bot replied!")
        print(f"Text preview: {text[:50]}...")
        
        # Check for link
        if reply_markup and reply_markup.inline_keyboard:
            button = reply_markup.inline_keyboard[0][0]
            url = button.url
            print(f"Button URL: {url}")
            if "/auth?token=" in url:
                print("[SUCCESS] Link contains token.")
            else:
                print("[FAIL] Link missing token!")
        else:
            print("[FAIL] No inline keyboard with link!")
            
        # Verify DB
        print("\nVerifying Database...")
        async for session in get_db():
            result = await session.execute(select(User).where(User.telegram_id == user_id))
            db_user = result.scalars().first()
            if db_user:
                print(f"[SUCCESS] User found in DB: {db_user.name} ({db_user.role})")
            else:
                print("[FAIL] User not found in DB!")
            break
            
    else:
        print("\n[FAIL] Bot did not reply!")

if __name__ == "__main__":
    try:
        asyncio.run(test_bot_start_command())
    except Exception as e:
        print(f"\n[ERROR] Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
