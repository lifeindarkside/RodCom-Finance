import logging
import time
from collections import defaultdict
from aiogram import Router, types, Bot
from aiogram.types import WebAppInfo
from aiogram.filters import Command, CommandObject
from sqlalchemy.future import select
from models import User
from database import get_db
from config import ALLOWED_CHAT_ID, SITE_URL, ADMIN_IDS
from security import create_token
from auth_state import pending_auths

router = Router()

# --- Rate limiting ---
# user_id -> list of timestamps
_rate_limit: dict = defaultdict(list)
RATE_LIMIT = 5    # max requests
RATE_WINDOW = 60  # per N seconds

def _is_rate_limited(user_id: int) -> bool:
    now = time.time()
    ts = _rate_limit[user_id]
    _rate_limit[user_id] = [t for t in ts if now - t < RATE_WINDOW]
    if len(_rate_limit[user_id]) >= RATE_LIMIT:
        return True
    _rate_limit[user_id].append(now)
    return False


@router.message(Command("start"))
async def cmd_start(message: types.Message, bot: Bot, command: CommandObject):
    user_id = message.from_user.id

    # Rate limit
    if _is_rate_limited(user_id):
        await message.answer("\u23f3 Слишком часто. Подождите минуту.")
        return

    # Parse auth deeplink
    target_auth_id = None
    args = command.args or ""
    if args.startswith("auth_") and len(args) < 50:
        target_auth_id = args[5:]
        if target_auth_id not in pending_auths:
            await message.answer(
                "\u26a0\ufe0f Ссылка для входа устарела.\n"
                "Нажмите \"Войти\" на сайте ещё раз."
            )
            return

    logging.info(f"CMD_START: user={user_id} auth={target_auth_id}")

    # Check chat membership
    is_member = False
    try:
        member = await bot.get_chat_member(ALLOWED_CHAT_ID, user_id)
        is_member = member.status not in ("left", "kicked")
    except Exception as e:
        logging.error(f"Membership check failed for {user_id}: {e}")
        # Admins bypass
        if user_id in ADMIN_IDS:
            is_member = True

    if not is_member:
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(
                text="\U0001f504 Проверить снова",
                callback_data="check_membership"
            )]
        ])
        await message.answer(
            "\u26d4 Вы не состоите в чате комитета.\n\n"
            "Вступите в чат и нажмите кнопку ниже.",
            reply_markup=kb
        )
        return

    # User is a member -- create/find in DB
    async for session in get_db():
        result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = result.scalars().first()
        if not user:
            role = "admin" if user_id in ADMIN_IDS else "viewer"
            user = User(telegram_id=user_id, name=message.from_user.full_name, role=role)
            session.add(user)
            await session.commit()
            await session.refresh(user)
        else:
            role = "admin" if user_id in ADMIN_IDS else user.role
            if user.role != role:
                user.role = role
                await session.commit()

        # Handle auth deeplink (for browser login)
        if target_auth_id:
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="\u2705 Да, войти", callback_data=f"auth_yes_{target_auth_id}"),
                    types.InlineKeyboardButton(text="\u274c Отмена", callback_data=f"auth_no_{target_auth_id}")
                ]
            ])
            await message.answer(
                f"\U0001f510 **Подтверждение входа**\n\n"
                f"Войти как **{user.name}**?\n\n"
                f"\u26a0\ufe0f После нажатия \u00abДа\u00bb страница в браузере обновится автоматически.",
                reply_markup=kb,
                parse_mode="Markdown"
            )
            return

        # Default start -- open Mini App
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(
                text="\U0001f4b0 Открыть РодКом",
                web_app=WebAppInfo(url=SITE_URL)
            )]
        ])
        await message.answer(
            f"\U0001f44b Привет, **{user.name}**!\n\n"
            f"\U0001f4b0 Нажмите кнопку ниже для открытия финансового контроля.\n"
            f"Также можно использовать кнопку Меню слева от поля ввода.",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        return


@router.callback_query(lambda c: c.data == "check_membership")
async def check_membership_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if _is_rate_limited(user_id):
        await callback.answer("\u23f3 Подождите минуту", show_alert=True)
        return

    try:
        bot = callback.bot
        member = await bot.get_chat_member(ALLOWED_CHAT_ID, user_id)
        if member.status in ("left", "kicked"):
            await callback.answer("\u274c Вы всё ещё не в чате", show_alert=True)
            return
    except Exception:
        await callback.answer("\u26a0\ufe0f Ошибка проверки", show_alert=True)
        return

    # User is now a member -- show success with Mini App button
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(
            text="\U0001f4b0 Открыть РодКом",
            web_app=WebAppInfo(url=SITE_URL)
        )]
    ])
    await callback.message.edit_text(
        f"\u2705 Доступ подтверждён!\n\n"
        f"Нажмите кнопку ниже.",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("auth_"))
async def process_auth_callback(callback: types.CallbackQuery):
    parts = callback.data.split("_", 2)
    if len(parts) < 3:
        await callback.answer("\u26a0\ufe0f Ошибка", show_alert=True)
        return

    action = parts[1]  # yes/no
    auth_id = parts[2]

    if auth_id not in pending_auths:
        await callback.answer("Сессия истекла", show_alert=True)
        await callback.message.edit_text("\u26a0\ufe0f Сессия истекла.")
        return

    if action == "yes":
        user_id = callback.from_user.id
        async for session in get_db():
            result = await session.execute(select(User).where(User.telegram_id == user_id))
            user = result.scalars().first()
            if not user:
                await callback.answer("Ошибка: пользователь не найден", show_alert=True)
                return

            token = create_token(user.id, user.telegram_id, user.role, user.name)
            pending_auths[auth_id]["status"] = "completed"
            pending_auths[auth_id]["token"] = token

            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="\U0001f517 Вернуться на сайт", url=SITE_URL)]
            ])

            await callback.answer("Успешно!")
            await callback.message.edit_text(
                "\u2705 **Вход подтверждён!**\n\nВернитесь в браузер \u2014 сайт уже открыт.",
                reply_markup=kb,
                parse_mode="Markdown"
            )
            return
    else:
        pending_auths[auth_id]["status"] = "cancelled"
        await callback.answer("Отменено")
        await callback.message.edit_text("\u274c Вход отменён.")
