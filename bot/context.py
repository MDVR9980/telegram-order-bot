"""Shared singletons (database + catalog) and admin-editable settings."""
from .catalog import Catalog
from .config import config
from .db import Database

db = Database(config.db_path)
catalog = Catalog(config.catalog_path)

DEFAULT_SETTINGS = {
    "support_username": config.support_username,
    "channel_url": config.channel_url,
    "welcome_text": "",           # empty = built-in welcome text
    "card_number": "6037-0000-0000-0000",
    "card_holder": "نام صاحب حساب",
    "bank_name": "بانک ملی",
    "delivery_time": "۲ تا ۱۲ ساعت",
    "orders_open": "1",
    "referral_percent": "10",
    "referral_mode": "purchase",  # purchase = after friend's first paid order (abuse-resistant) | join = as soon as the friend starts the bot
}


async def setting(key: str) -> str:
    return await db.get_setting(key, DEFAULT_SETTINGS.get(key, ""))


async def referral_percent() -> int:
    try:
        return max(0, min(100, int(await setting("referral_percent"))))
    except ValueError:
        return 10


async def load_catalog() -> None:
    """Load the catalog from the DB; on first run seed it from catalog.json."""
    raw = await db.get_setting("catalog", "")
    if raw:
        catalog.load(raw)
    else:
        await save_catalog()


async def save_catalog() -> None:
    await db.set_setting("catalog", catalog.dump())


async def support_username() -> str:
    return (await setting("support_username")).lstrip("@")
