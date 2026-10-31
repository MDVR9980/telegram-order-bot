from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                 INTEGER PRIMARY KEY,
    username           TEXT,
    full_name          TEXT,
    is_blocked         INTEGER NOT NULL DEFAULT 0,
    referred_by        INTEGER,
    referral_rewarded  INTEGER NOT NULL DEFAULT 0,   -- referrer already got credit for this user
    referral_credits   INTEGER NOT NULL DEFAULT 0,   -- unused discount coupons
    created_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admins (
    user_id     INTEGER PRIMARY KEY,
    added_by    INTEGER,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    style            TEXT NOT NULL,
    faces            TEXT NOT NULL,
    description      TEXT,
    base_price       INTEGER,                 -- set by admin
    discount_kind    TEXT,                    -- NULL | referral | promo
    discount_code    TEXT,                    -- promo code, if any
    discount_percent INTEGER NOT NULL DEFAULT 0,
    discount_fixed   INTEGER NOT NULL DEFAULT 0,
    discount_amount  INTEGER NOT NULL DEFAULT 0,
    price            INTEGER,                 -- final amount to pay
    status           TEXT NOT NULL,
    reject_reason    TEXT,
    rating           INTEGER,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS promo_codes (
    code        TEXT PRIMARY KEY,           -- stored upper-case
    kind        TEXT NOT NULL,              -- percent | amount
    value       INTEGER NOT NULL,
    max_uses    INTEGER,                    -- NULL = unlimited
    used        INTEGER NOT NULL DEFAULT 0,
    expires_at  TEXT,                       -- UTC, NULL = never
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS promo_uses (
    code      TEXT NOT NULL,
    user_id   INTEGER NOT NULL,
    order_id  INTEGER NOT NULL,
    PRIMARY KEY (code, user_id)             -- each customer can use a code once
);

CREATE TABLE IF NOT EXISTS fsm (
    key    TEXT PRIMARY KEY,
    state  TEXT,
    data   TEXT NOT NULL DEFAULT '{}'
);
"""


class Status:
    AWAITING_QUOTE = "awaiting_quote"
    AWAITING_PAYMENT = "awaiting_payment"
    PAYMENT_REVIEW = "payment_review"
    IN_PROGRESS = "in_progress"
    PREVIEW_SENT = "preview_sent"
    REVISION = "revision"
    PREVIEW_APPROVED = "preview_approved"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

    LABELS = {
        AWAITING_QUOTE: "🧮 در انتظار تعیین قیمت",
        AWAITING_PAYMENT: "⏳ در انتظار پرداخت",
        PAYMENT_REVIEW: "🔎 بررسی رسید",
        IN_PROGRESS: "🎨 در حال طراحی",
        PREVIEW_SENT: "👀 پیش‌نمایش ارسال شد",
        REVISION: "✏️ در حال اصلاح",
        PREVIEW_APPROVED: "👍 پیش‌نمایش تایید شد",
        DELIVERED: "✅ تحویل شده",
        CANCELLED: "❌ لغو شده",
    }
    ACTIVE = (AWAITING_QUOTE, AWAITING_PAYMENT, PAYMENT_REVIEW, IN_PROGRESS, PREVIEW_SENT, REVISION, PREVIEW_APPROVED)
    UNPAID = (AWAITING_QUOTE, AWAITING_PAYMENT, PAYMENT_REVIEW)
    WORKING = (IN_PROGRESS, REVISION, PREVIEW_SENT, PREVIEW_APPROVED)
    PAID = (IN_PROGRESS, PREVIEW_SENT, REVISION, PREVIEW_APPROVED, DELIVERED)

    @classmethod
    def label(cls, status: str) -> str:
        return cls.LABELS.get(status, status)


def now() -> str:
    # UTC, same format as SQLite's datetime('now') so string comparisons work
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _marks(items) -> str:
    return ",".join("?" * len(items))


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

    async def _exec(self, sql: str, params: tuple = ()) -> tuple[int, int]:
        """Returns (lastrowid, rowcount)."""
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cur.lastrowid, cur.rowcount

    # ---------- users ----------
    async def upsert_user(self, user_id: int, username: str | None, full_name: str) -> bool:
        """Insert or update a user. Returns True if the user is new."""
        _, inserted = await self._exec(
            "INSERT OR IGNORE INTO users (id, username, full_name, created_at) VALUES (?, ?, ?, ?)",
            (user_id, username, full_name, now()),
        )
        if not inserted:
            await self._exec("UPDATE users SET username=?, full_name=? WHERE id=?", (username, full_name, user_id))
        return bool(inserted)

    async def get_user(self, user_id: int) -> dict | None:
        return await self._one("SELECT * FROM users WHERE id=?", (user_id,))

    async def set_blocked(self, user_id: int, blocked: bool) -> bool:
        _, n = await self._exec("UPDATE users SET is_blocked=? WHERE id=?", (int(blocked), user_id))
        return n > 0

    async def all_user_ids(self) -> list[int]:
        return [r["id"] for r in await self._all("SELECT id FROM users WHERE is_blocked=0")]

    # ---------- referrals ----------
    async def set_referrer(self, user_id: int, referrer_id: int) -> None:
        await self._exec("UPDATE users SET referred_by=? WHERE id=? AND referred_by IS NULL", (referrer_id, user_id))

    async def reward_referrer(self, invited_id: int) -> int | None:
        """Give the inviter of `invited_id` one coupon (once). Returns the inviter id if rewarded."""
        _, n = await self._exec(
            "UPDATE users SET referral_rewarded=1 WHERE id=? AND referred_by IS NOT NULL AND referral_rewarded=0",
            (invited_id,),
        )
        if not n:
            return None
        user = await self.get_user(invited_id)
        await self._exec("UPDATE users SET referral_credits=referral_credits+1 WHERE id=?", (user["referred_by"],))
        return user["referred_by"]

    async def take_credit(self, user_id: int) -> bool:
        """Atomically consume one coupon."""
        _, n = await self._exec(
            "UPDATE users SET referral_credits=referral_credits-1 WHERE id=? AND referral_credits>0", (user_id,)
        )
        return n > 0

    async def give_back_credit(self, user_id: int) -> None:
        await self._exec("UPDATE users SET referral_credits=referral_credits+1 WHERE id=?", (user_id,))

    async def referral_stats(self, user_id: int) -> dict:
        return await self._one(
            """SELECT
                 (SELECT COUNT(*) FROM users WHERE referred_by=?) invited,
                 (SELECT COUNT(*) FROM users WHERE referred_by=? AND referral_rewarded=1) rewarded,
                 (SELECT referral_credits FROM users WHERE id=?) credits""",
            (user_id, user_id, user_id),
        )

    # ---------- admins ----------
    async def add_admin(self, user_id: int, added_by: int) -> None:
        await self._exec(
            "INSERT OR IGNORE INTO admins (user_id, added_by, created_at) VALUES (?, ?, ?)", (user_id, added_by, now())
        )

    async def remove_admin(self, user_id: int) -> None:
        await self._exec("DELETE FROM admins WHERE user_id=?", (user_id,))

    async def admin_ids(self) -> list[int]:
        return [r["user_id"] for r in await self._all("SELECT user_id FROM admins")]

    async def list_admins(self) -> list[dict]:
        return await self._all(
            """SELECT a.user_id, u.username, u.full_name FROM admins a
               LEFT JOIN users u ON u.id = a.user_id ORDER BY a.created_at"""
        )

    # ---------- orders ----------
    async def create_order(self, user_id: int, style: str, faces: str, description: str | None) -> int:
        ts = now()
        order_id, _ = await self._exec(
            """INSERT INTO orders (user_id, style, faces, description, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, style, faces, description, Status.AWAITING_QUOTE, ts, ts),
        )
        return order_id

    async def get_order(self, order_id: int) -> dict | None:
        return await self._one(
            """SELECT o.*, u.username, u.full_name FROM orders o
               JOIN users u ON u.id = o.user_id WHERE o.id=?""",
            (order_id,),
        )

    async def user_orders(self, user_id: int, limit: int = 20) -> list[dict]:
        return await self._all("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))

    async def user_orders_in(self, user_id: int, statuses: tuple[str, ...]) -> list[dict]:
        return await self._all(
            f"SELECT * FROM orders WHERE user_id=? AND status IN ({_marks(statuses)}) ORDER BY id DESC",
            (user_id, *statuses),
        )

    async def user_paid_orders(self, user_id: int) -> int:
        row = await self._one(
            f"SELECT COUNT(*) c FROM orders WHERE user_id=? AND status IN ({_marks(Status.PAID)})",
            (user_id, *Status.PAID),
        )
        return row["c"]

    async def orders_by_status(self, statuses: tuple[str, ...], limit: int = 30, offset: int = 0) -> list[dict]:
        return await self._all(
            f"""SELECT o.*, u.username, u.full_name FROM orders o JOIN users u ON u.id=o.user_id
                WHERE o.status IN ({_marks(statuses)}) ORDER BY o.id DESC LIMIT ? OFFSET ?""",
            (*statuses, limit, offset),
        )

    async def count_by_status(self, statuses: tuple[str, ...]) -> int:
        row = await self._one(f"SELECT COUNT(*) c FROM orders WHERE status IN ({_marks(statuses)})", statuses)
        return row["c"]

    async def transition(self, order_id: int, from_statuses: tuple[str, ...], to_status: str,
                         reject_reason: str | None = None) -> bool:
        """Change status only if the order is currently in one of `from_statuses`.
        Prevents double actions (two admins clicking at once, double taps)."""
        _, n = await self._exec(
            f"""UPDATE orders SET status=?, reject_reason=?, updated_at=?
                WHERE id=? AND status IN ({_marks(from_statuses)})""",
            (to_status, reject_reason, now(), order_id, *from_statuses),
        )
        return n > 0

    async def set_pricing(self, order_id: int, from_statuses: tuple[str, ...], *, base_price: int,
                          discount_kind: str | None, discount_code: str | None, discount_percent: int,
                          discount_fixed: int, discount_amount: int, price: int) -> bool:
        """Write price + discount and move the order to AWAITING_PAYMENT, only if it is in `from_statuses`."""
        _, n = await self._exec(
            f"""UPDATE orders SET base_price=?, discount_kind=?, discount_code=?, discount_percent=?,
                       discount_fixed=?, discount_amount=?, price=?, status=?, updated_at=?
                WHERE id=? AND status IN ({_marks(from_statuses)})""",
            (base_price, discount_kind, discount_code, discount_percent, discount_fixed, discount_amount, price,
             Status.AWAITING_PAYMENT, now(), order_id, *from_statuses),
        )
        return n > 0

    async def set_rating(self, order_id: int, rating: int) -> None:
        await self._exec("UPDATE orders SET rating=?, updated_at=? WHERE id=?", (rating, now(), order_id))

    async def stats(self) -> dict:
        paid = ",".join(f"'{s}'" for s in Status.PAID)
        active = ",".join(f"'{s}'" for s in Status.ACTIVE)
        return await self._one(
            f"""SELECT
                  (SELECT COUNT(*) FROM users) users,
                  (SELECT COUNT(*) FROM users WHERE referred_by IS NOT NULL) referred,
                  (SELECT COUNT(*) FROM orders) orders,
                  (SELECT COUNT(*) FROM orders WHERE status='{Status.DELIVERED}') delivered,
                  (SELECT COUNT(*) FROM orders WHERE status IN ({active})) active,
                  (SELECT COALESCE(SUM(price),0) FROM orders WHERE status IN ({paid})) revenue,
                  (SELECT COALESCE(SUM(price),0) FROM orders WHERE status IN ({paid})
                       AND updated_at >= datetime('now','-30 day')) revenue_30,
                  (SELECT ROUND(AVG(rating),1) FROM orders WHERE rating IS NOT NULL) avg_rating,
                  (SELECT COUNT(*) FROM orders WHERE created_at >= datetime('now','-1 day')) today
            """
        )

    async def order_extra(self, order: dict) -> dict:
        counts = await self._all("SELECT kind, COUNT(*) c FROM order_files WHERE order_id=? GROUP BY kind", (order["id"],))
        extra = {"reference": 0, "receipt": 0, "preview": 0, "final": 0}
        extra.update({r["kind"]: r["c"] for r in counts})
        row = await self._one("SELECT COUNT(*) c FROM orders WHERE user_id=?", (order["user_id"],))
        extra["user_orders"] = row["c"]
        extra["user_paid"] = await self.user_paid_orders(order["user_id"])
        return extra

    # ---------- files ----------
    async def add_file(self, order_id: int, kind: str, file_id: str, file_type: str) -> None:
        await self._exec(
            "INSERT INTO order_files (order_id, kind, file_id, file_type, created_at) VALUES (?, ?, ?, ?, ?)",
            (order_id, kind, file_id, file_type, now()),
        )

    async def get_files(self, order_id: int, kind: str) -> list[dict]:
        return await self._all("SELECT * FROM order_files WHERE order_id=? AND kind=? ORDER BY id", (order_id, kind))

    async def delete_files(self, order_id: int, kind: str) -> None:
        await self._exec("DELETE FROM order_files WHERE order_id=? AND kind=?", (order_id, kind))

    # ---------- promo codes ----------
    async def create_promo(self, code: str, kind: str, value: int, max_uses: int | None, expires_at: str | None) -> bool:
        _, n = await self._exec(
            """INSERT OR IGNORE INTO promo_codes (code, kind, value, max_uses, expires_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (code.upper(), kind, value, max_uses, expires_at, now()),
        )
        return n > 0

    async def get_promo(self, code: str) -> dict | None:
        return await self._one("SELECT * FROM promo_codes WHERE code=?", (code.upper(),))

    async def list_promos(self) -> list[dict]:
        return await self._all("SELECT * FROM promo_codes ORDER BY created_at DESC")

    async def toggle_promo(self, code: str) -> None:
        await self._exec("UPDATE promo_codes SET active=1-active WHERE code=?", (code.upper(),))

    async def delete_promo(self, code: str) -> None:
        await self._exec("DELETE FROM promo_codes WHERE code=?", (code.upper(),))

    async def promo_used_by(self, code: str, user_id: int) -> bool:
        return await self._one("SELECT 1 FROM promo_uses WHERE code=? AND user_id=?", (code.upper(), user_id)) is not None

    async def claim_promo(self, code: str, user_id: int, order_id: int) -> bool:
        """Atomically reserve one use of a valid code for this user."""
        code = code.upper()
        _, n = await self._exec(
            """UPDATE promo_codes SET used=used+1
               WHERE code=? AND active=1 AND (max_uses IS NULL OR used < max_uses)
                 AND (expires_at IS NULL OR expires_at > ?)""",
            (code, now()),
        )
        if not n:
            return False
        _, n = await self._exec(
            "INSERT OR IGNORE INTO promo_uses (code, user_id, order_id) VALUES (?, ?, ?)", (code, user_id, order_id)
        )
        if not n:  # already used by this customer
            await self._exec("UPDATE promo_codes SET used=used-1 WHERE code=?", (code,))
            return False
        return True

    async def release_promo(self, code: str, user_id: int) -> None:
        _, n = await self._exec("DELETE FROM promo_uses WHERE code=? AND user_id=?", (code.upper(), user_id))
        if n:
            await self._exec("UPDATE promo_codes SET used=MAX(used-1,0) WHERE code=?", (code.upper(),))

    # ---------- settings ----------
    async def get_setting(self, key: str, default: str = "") -> str:
        row = await self._one("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self._exec(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
