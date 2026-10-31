from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT,
    full_name   TEXT,
    phone       TEXT,
    is_blocked  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admins (
    user_id     INTEGER PRIMARY KEY,
    added_by    INTEGER,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    style         TEXT NOT NULL,
    size          TEXT NOT NULL,
    faces         TEXT NOT NULL,
    delivery      TEXT NOT NULL,
    description   TEXT,
    phone         TEXT,
    address       TEXT,
    price         INTEGER NOT NULL,
    status        TEXT NOT NULL,
    reject_reason TEXT,
    rating        INTEGER,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_user   ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

CREATE TABLE IF NOT EXISTS order_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL REFERENCES orders(id),
    kind        TEXT NOT NULL,      -- reference | receipt | preview | final
    file_id     TEXT NOT NULL,
    file_type   TEXT NOT NULL,      -- photo | document
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_order ON order_files(order_id, kind);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Status:
    AWAITING_PAYMENT = "awaiting_payment"
    PAYMENT_REVIEW = "payment_review"
    IN_PROGRESS = "in_progress"
    PREVIEW_SENT = "preview_sent"
    REVISION = "revision"
    PREVIEW_APPROVED = "preview_approved"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

    LABELS = {
        AWAITING_PAYMENT: "⏳ در انتظار پرداخت",
        PAYMENT_REVIEW: "🔎 بررسی رسید",
        IN_PROGRESS: "🎨 در حال طراحی",
        PREVIEW_SENT: "👀 پیش‌نمایش ارسال شد",
        REVISION: "✏️ در حال اصلاح",
        PREVIEW_APPROVED: "👍 پیش‌نمایش تایید شد",
        DELIVERED: "✅ تحویل شده",
        CANCELLED: "❌ لغو شده",
    }
    ACTIVE = (AWAITING_PAYMENT, PAYMENT_REVIEW, IN_PROGRESS, PREVIEW_SENT, REVISION, PREVIEW_APPROVED)

    @classmethod
    def label(cls, status: str) -> str:
        return cls.LABELS.get(status, status)


def now() -> str:
    # UTC, same format as SQLite's datetime('now') so string comparisons work
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    # ---------- low level ----------
    async def _one(self, sql: str, params: tuple = ()) -> dict | None:
        async with self.conn.execute(sql, params) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        async with self.conn.execute(sql, params) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def _exec(self, sql: str, params: tuple = ()) -> int:
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cur.lastrowid

    # ---------- users ----------
    async def upsert_user(self, user_id: int, username: str | None, full_name: str) -> None:
        await self._exec(
            """INSERT INTO users (id, username, full_name, created_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name""",
            (user_id, username, full_name, now()),
        )

    async def get_user(self, user_id: int) -> dict | None:
        return await self._one("SELECT * FROM users WHERE id=?", (user_id,))

    async def set_user_phone(self, user_id: int, phone: str) -> None:
        await self._exec("UPDATE users SET phone=? WHERE id=?", (phone, user_id))

    async def set_blocked(self, user_id: int, blocked: bool) -> None:
        await self._exec("UPDATE users SET is_blocked=? WHERE id=?", (int(blocked), user_id))

    async def all_user_ids(self) -> list[int]:
        rows = await self._all("SELECT id FROM users WHERE is_blocked=0")
        return [r["id"] for r in rows]

    # ---------- admins ----------
    async def add_admin(self, user_id: int, added_by: int) -> None:
        await self._exec(
            "INSERT OR IGNORE INTO admins (user_id, added_by, created_at) VALUES (?, ?, ?)",
            (user_id, added_by, now()),
        )

    async def remove_admin(self, user_id: int) -> None:
        await self._exec("DELETE FROM admins WHERE user_id=?", (user_id,))

    async def admin_ids(self) -> list[int]:
        rows = await self._all("SELECT user_id FROM admins")
        return [r["user_id"] for r in rows]

    async def list_admins(self) -> list[dict]:
        return await self._all(
            """SELECT a.user_id, u.username, u.full_name FROM admins a
               LEFT JOIN users u ON u.id = a.user_id ORDER BY a.created_at"""
        )

    # ---------- orders ----------
    async def create_order(self, user_id: int, data: dict[str, Any], price: int) -> int:
        ts = now()
        return await self._exec(
            """INSERT INTO orders (user_id, style, size, faces, delivery, description, phone, address,
                                   price, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id, data["style"], data["size"], data["faces"], data["delivery"],
                data.get("description"), data.get("phone"), data.get("address"),
                price, Status.AWAITING_PAYMENT, ts, ts,
            ),
        )

    async def get_order(self, order_id: int) -> dict | None:
        return await self._one(
            """SELECT o.*, u.username, u.full_name FROM orders o
               JOIN users u ON u.id = o.user_id WHERE o.id=?""",
            (order_id,),
        )

    async def user_orders(self, user_id: int, limit: int = 20) -> list[dict]:
        return await self._all(
            "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)
        )

    async def orders_by_status(self, statuses: tuple[str, ...], limit: int = 30, offset: int = 0) -> list[dict]:
        marks = ",".join("?" * len(statuses))
        return await self._all(
            f"""SELECT o.*, u.username, u.full_name FROM orders o JOIN users u ON u.id=o.user_id
                WHERE o.status IN ({marks}) ORDER BY o.id DESC LIMIT ? OFFSET ?""",
            (*statuses, limit, offset),
        )

    async def count_by_status(self, statuses: tuple[str, ...]) -> int:
        marks = ",".join("?" * len(statuses))
        row = await self._one(f"SELECT COUNT(*) c FROM orders WHERE status IN ({marks})", statuses)
        return row["c"]

    async def set_status(self, order_id: int, status: str, reject_reason: str | None = None) -> None:
        await self._exec(
            "UPDATE orders SET status=?, reject_reason=?, updated_at=? WHERE id=?",
            (status, reject_reason, now(), order_id),
        )

    async def set_rating(self, order_id: int, rating: int) -> None:
        await self._exec("UPDATE orders SET rating=?, updated_at=? WHERE id=?", (rating, now(), order_id))

    async def stats(self) -> dict:
        row = await self._one(
            f"""SELECT
                  (SELECT COUNT(*) FROM users) users,
                  (SELECT COUNT(*) FROM orders) orders,
                  (SELECT COUNT(*) FROM orders WHERE status='{Status.DELIVERED}') delivered,
                  (SELECT COUNT(*) FROM orders WHERE status IN ({",".join(repr(s) for s in Status.ACTIVE)})) active,
                  (SELECT COUNT(*) FROM orders WHERE status='{Status.PAYMENT_REVIEW}') review,
                  (SELECT COALESCE(SUM(price),0) FROM orders
                     WHERE status NOT IN ('{Status.AWAITING_PAYMENT}','{Status.PAYMENT_REVIEW}','{Status.CANCELLED}')) revenue,
                  (SELECT ROUND(AVG(rating),2) FROM orders WHERE rating IS NOT NULL) avg_rating,
                  (SELECT COUNT(*) FROM orders WHERE created_at >= datetime('now','-1 day')) today
            """
        )
        return row

    # ---------- files ----------
    async def add_file(self, order_id: int, kind: str, file_id: str, file_type: str) -> None:
        await self._exec(
            "INSERT INTO order_files (order_id, kind, file_id, file_type, created_at) VALUES (?, ?, ?, ?, ?)",
            (order_id, kind, file_id, file_type, now()),
        )

    async def get_files(self, order_id: int, kind: str) -> list[dict]:
        return await self._all(
            "SELECT * FROM order_files WHERE order_id=? AND kind=? ORDER BY id", (order_id, kind)
        )

    # ---------- settings ----------
    async def get_setting(self, key: str, default: str = "") -> str:
        row = await self._one("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self._exec(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
