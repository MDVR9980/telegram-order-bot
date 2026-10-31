from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from .context import db
from .utils import is_admin


class UserMiddleware(BaseMiddleware):
    """Registers every user, drops updates from blocked users, injects `is_admin`."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.is_bot:
            return await handler(event, data)

        data["is_new_user"] = await db.upsert_user(user.id, user.username, user.full_name)
        admin = await is_admin(user.id)
        if not admin:
            row = await db.get_user(user.id)
            if row and row["is_blocked"]:
                if isinstance(event, CallbackQuery):
                    await event.answer("⛔️ دسترسی شما محدود شده است.", show_alert=True)
                elif isinstance(event, Message):
                    await event.answer("⛔️ دسترسی شما به ربات محدود شده است.")
                return None
        data["is_admin"] = admin
        return await handler(event, data)
