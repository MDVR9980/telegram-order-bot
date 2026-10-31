import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from .config import config
from .context import db
from .handlers import setup_routers
from .middlewares import UserMiddleware
from .utils import all_admin_ids

USER_COMMANDS = [
    BotCommand(command="start", description="🏠 منوی اصلی"),
    BotCommand(command="help", description="📖 راهنما"),
    BotCommand(command="cancel", description="❌ لغو عملیات"),
]
ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand(command="admin", description="🛠 پنل مدیریت"),
    BotCommand(command="order", description="🔍 مشاهده سفارش: /order 12"),
    BotCommand(command="block", description="🚫 مسدود کردن کاربر"),
    BotCommand(command="unblock", description="✅ رفع مسدودی کاربر"),
]


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeDefault())
    for admin_id in await all_admin_ids():
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:  # noqa: BLE001  (admin hasn't started the bot yet)
            pass


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    await db.connect()

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(UserMiddleware())
    dp.callback_query.outer_middleware(UserMiddleware())
    dp.include_router(setup_routers())

    await set_commands(bot)
    me = await bot.get_me()
    logging.info("Bot @%s started", me.username)
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
