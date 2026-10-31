import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Environment variable {name} is required (see .env.example)")
    return value


@dataclass(frozen=True)
class Config:
    bot_token: str
    super_admin_id: int
    db_path: Path
    support_username: str
    channel_url: str
    timezone: str
    catalog_path: Path


def load_config() -> Config:
    root = Path(__file__).resolve().parent.parent
    db_path = Path(os.getenv("DB_PATH", "data/bot.db"))
    if not db_path.is_absolute():
        db_path = root / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Config(
        bot_token=_require("BOT_TOKEN"),
        super_admin_id=int(_require("SUPER_ADMIN_ID")),
        db_path=db_path,
        support_username=os.getenv("SUPPORT_USERNAME", "LinoriaSupport").lstrip("@"),
        channel_url=os.getenv("CHANNEL_URL", ""),
        timezone=os.getenv("TIMEZONE", "Asia/Tehran"),
        catalog_path=root / "catalog.json",
    )


config = load_config()
