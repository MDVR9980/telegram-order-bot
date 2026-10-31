"""Shared singletons (database + catalog)."""
from .catalog import Catalog
from .config import config
from .db import Database

db = Database(config.db_path)
catalog = Catalog(config.catalog_path)

# default values for admin-editable settings
DEFAULT_SETTINGS = {
    "card_number": "6037-0000-0000-0000",
    "card_holder": "نام صاحب حساب",
    "bank_name": "بانک ملی",
    "delivery_time": "۲ تا ۱۲ ساعت",
    "orders_open": "1",
}


async def setting(key: str) -> str:
    return await db.get_setting(key, DEFAULT_SETTINGS.get(key, ""))
