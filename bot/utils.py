from __future__ import annotations

import asyncio
import html
import logging
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import (
    InlineKeyboardMarkup,
    InputMediaDocument,
    InputMediaPhoto,
    Message,
)

from .config import config
from .context import catalog, db
from .db import Status

log = logging.getLogger(__name__)

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_EN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def fa(value) -> str:
    return str(value).translate(_FA_DIGITS)


def to_en_digits(text: str) -> str:
    return text.translate(_EN_DIGITS)


def money(amount: int) -> str:
    return f"{fa(f'{amount:,}').replace(',', '٬')} {catalog.currency}"


def esc(text: str | None) -> str:
    return html.escape(text or "")


def fmt_time(ts: str) -> str:
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return fa(dt.astimezone(ZoneInfo(config.timezone)).strftime("%Y/%m/%d - %H:%M"))
    except Exception:  # noqa: BLE001
        return ts


# ---------- per-user locks (albums arrive as parallel updates) ----------
_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def user_lock(user_id: int) -> asyncio.Lock:
    return _locks[user_id]


# ---------- roles ----------
async def is_admin(user_id: int) -> bool:
    return user_id == config.super_admin_id or user_id in await db.admin_ids()


def is_super(user_id: int) -> bool:
    return user_id == config.super_admin_id


async def all_admin_ids() -> list[int]:
    ids = [config.super_admin_id, *await db.admin_ids()]
    return list(dict.fromkeys(ids))


# ---------- files ----------
def extract_file(message: Message) -> tuple[str, str] | None:
    """Return (file_id, file_type) for a photo or image/document message."""
    if message.photo:
        return message.photo[-1].file_id, "photo"
    if message.document:
        return message.document.file_id, "document"
    return None


async def send_files(bot: Bot, chat_id: int, files: list[dict], caption: str | None = None) -> None:
    """Send stored files grouped as albums (photos and documents can't be mixed)."""
    photos = [f for f in files if f["file_type"] == "photo"]
    docs = [f for f in files if f["file_type"] == "document"]
    caption_used = False
    for group, media_cls in ((photos, InputMediaPhoto), (docs, InputMediaDocument)):
        for i in range(0, len(group), 10):
            chunk = group[i:i + 10]
            cap = None if caption_used else caption
            if len(chunk) == 1:
                send = bot.send_photo if media_cls is InputMediaPhoto else bot.send_document
                await send(chat_id, chunk[0]["file_id"], caption=cap)
            else:
                media = [media_cls(media=f["file_id"]) for f in chunk]
                if cap:
                    media[0].caption = cap
                await bot.send_media_group(chat_id, media)
            caption_used = True


async def notify_admins(
    bot: Bot, text: str, reply_markup: InlineKeyboardMarkup | None = None, files: list[dict] | None = None
) -> None:
    for admin_id in await all_admin_ids():
        try:
            if files:
                await send_files(bot, admin_id, files)
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
        except Exception as e:  # noqa: BLE001  (admin may have never started the bot)
            log.warning("could not notify admin %s: %s", admin_id, e)


# ---------- order text ----------
def order_lines(order: dict) -> list[str]:
    style = catalog.style(order["style"])
    size = catalog.size(order["size"])
    faces = catalog.face(order["faces"])
    delivery = catalog.delivery(order["delivery"])
    lines = [
        f"🎨 سبک: <b>{esc(style.title if style else order['style'])}</b>",
        f"📐 سایز: <b>{esc(size.title if size else order['size'])}</b>",
        f"👤 تعداد چهره: <b>{esc(faces.title if faces else order['faces'])}</b>",
        f"🚚 تحویل: <b>{esc(delivery.title if delivery else order['delivery'])}</b>",
    ]
    if order.get("description"):
        lines.append(f"📝 توضیحات: {esc(order['description'])}")
    if order.get("phone"):
        lines.append(f"📞 تلفن: <code>{esc(order['phone'])}</code>")
    if order.get("address"):
        lines.append(f"🏠 آدرس: {esc(order['address'])}")
    lines.append(f"💰 مبلغ: <b>{money(order['price'])}</b>")
    return lines


def order_card_user(order: dict) -> str:
    head = [
        f"🧾 <b>سفارش #{fa(order['id'])}</b>",
        f"وضعیت: {Status.label(order['status'])}",
        f"🕒 ثبت: {fmt_time(order['created_at'])}",
        "",
    ]
    tail = []
    if order["status"] == Status.AWAITING_PAYMENT and order.get("reject_reason"):
        tail = ["", f"⚠️ رسید قبلی تایید نشد: {esc(order['reject_reason'])}"]
    return "\n".join(head + order_lines(order) + tail)


def order_card_admin(order: dict) -> str:
    uname = f"@{order['username']}" if order.get("username") else "—"
    head = [
        f"🧾 <b>سفارش #{order['id']}</b> — {Status.label(order['status'])}",
        f"👤 مشتری: <a href=\"tg://user?id={order['user_id']}\">{esc(order.get('full_name'))}</a> ({esc(uname)})",
        f"🆔 <code>{order['user_id']}</code>",
        f"🕒 {fmt_time(order['created_at'])}",
        "",
    ]
    tail = []
    if order.get("rating"):
        tail.append(f"\n⭐️ امتیاز مشتری: {'⭐️' * order['rating']}")
    return "\n".join(head + order_lines(order) + tail)
