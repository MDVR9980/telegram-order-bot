from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from .utils import is_admin, is_super


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject, event_from_user=None) -> bool:
        return event_from_user is not None and await is_admin(event_from_user.id)


class IsSuperAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject, event_from_user=None) -> bool:
        return event_from_user is not None and is_super(event_from_user.id)
