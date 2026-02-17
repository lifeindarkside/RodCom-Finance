import logging
import asyncio
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN, SITE_URL
from aiogram.types import MenuButtonWebApp, WebAppInfo
from handlers import common
from middlewares.auth import AuthMiddleware

# Setup logging
logging.basicConfig(level=logging.INFO)

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Include routers
dp.include_router(common.router)

# Middleware
# AuthMiddleware logic for bot needs update or removal if only /start is used
# But we might want to restrict other commands if added later
# For now, just keep it but modify it to check chat membership if needed 
# Actually, handlers/common.py does the check. Middleware might be redundant or interfering. 
# Let's keep it simple and skip middleware for now as logic is in handler.
# dp.update.middleware(AuthMiddleware()) 

async def start_bot():
    """Function to start bot polling"""
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        # Set Menu Button to open Mini App
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="Открыть",
                    web_app=WebAppInfo(url=SITE_URL)
                )
            )
            logging.info(f"Menu button set to {SITE_URL}")
        except Exception as e:
            logging.error(f"Failed to set menu button: {e}")
        logging.info("Starting bot polling...")
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Bot error: {e}")
