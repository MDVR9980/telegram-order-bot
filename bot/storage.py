"""FSM storage in SQLite, so users don't lose their place if the bot restarts."""
import json
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey

from .db import Database


def _key(key: StorageKey) -> str:
    return f"{key.bot_id}:{key.chat_id}:{key.user_id}:{key.thread_id or 0}:{key.destiny}"


class SQLiteStorage(BaseStorage):
    def __init__(self, db: Database):
        self.db = db

    async def set_state(self, key: StorageKey, state: str | State | None = None) -> None:
        value = state.state if isinstance(state, State) else state
        await self.db.conn.execute(
            "INSERT INTO fsm (key, state) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET state=excluded.state",
            (_key(key), value),
        )
        await self.db.conn.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        async with self.db.conn.execute("SELECT state FROM fsm WHERE key=?", (_key(key),)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        await self.db.conn.execute(
            "INSERT INTO fsm (key, data) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET data=excluded.data",
            (_key(key), json.dumps(data, ensure_ascii=False)),
        )
        await self.db.conn.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        async with self.db.conn.execute("SELECT data FROM fsm WHERE key=?", (_key(key),)) as cur:
            row = await cur.fetchone()
            return json.loads(row[0]) if row and row[0] else {}

    async def close(self) -> None:
        pass
