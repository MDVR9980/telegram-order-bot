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


async def safe_edit(message: Message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Edit a bot message; ignore 'not modified', fall back to a new message if editing is impossible."""
    from aiogram.exceptions import TelegramBadRequest

    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        await message.answer(text, reply_markup=markup)


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


# ---------- prices ----------
def parse_price(text: str) -> int | None:
    """'320' / '320000' / '۳۲۰ هزار' / '320,000' -> toman. Numbers below 10,000 are read as thousands."""
    digits = "".join(ch for ch in to_en_digits(text) if ch.isdigit())
    if not digits or len(digits) > 10:
        return None
    value = int(digits)
    if value < 10_000:
        value *= 1000
    return value if value > 0 else None


def apply_discount(base: int, percent: int) -> int:
    if percent <= 0:
        return base
    return int(round(base * (100 - percent) / 100 / 1000.0)) * 1000


# ---------- order text ----------
def price_lines(order: dict) -> list[str]:
    if order.get("price") is None:
        return ["💰 مبلغ: <i>بعد از بررسی عکس‌ها اعلام می‌شود</i>"]
    if order.get("discount_amount"):
        if order.get("discount_kind") == "referral":
            label = f"🎁 تخفیف دعوت دوستان ({fa(order['discount_percent'])}٪)"
        else:
            how = f"{fa(order['discount_percent'])}٪" if order.get("discount_percent") else "مبلغ ثابت"
            label = f"🎟 کد تخفیف {esc(order.get('discount_code'))} ({how})"
        return [
            f"💰 مبلغ: <s>{money(order['base_price'])}</s>",
            f"{label}: −{money(order['discount_amount'])}",
            f"💳 مبلغ نهایی: <b>{money(order['price'])}</b>",
        ]
    return [f"💳 مبلغ: <b>{money(order['price'])}</b>"]


def order_lines(order: dict) -> list[str]:
    style = catalog.style(order["style"], include_hidden=True)
    faces = catalog.face(order["faces"], include_hidden=True)
    lines = [
        f"🎨 نوع اثر: <b>{esc(style.title if style else order['style'])}</b>",
        f"👤 تعداد افراد: <b>{esc(faces.title if faces else order['faces'])}</b>",
    ]
    if order.get("description"):
        lines.append(f"📝 توضیحات: {esc(order['description'])}")
    return lines + price_lines(order)


STAGES = [
    ("ثبت سفارش", ()),
    ("تعیین قیمت", (Status.AWAITING_QUOTE,)),
    ("پرداخت و تایید رسید", (Status.AWAITING_PAYMENT, Status.PAYMENT_REVIEW)),
    ("طراحی اثر", (Status.IN_PROGRESS, Status.REVISION)),
    ("پیش‌نمایش و تایید شما", (Status.PREVIEW_SENT,)),
    ("تحویل فایل نهایی", (Status.PREVIEW_APPROVED,)),
]
_STAGE_INDEX = {st: i for i, (_, sts) in enumerate(STAGES) for st in sts}

NEXT_STEP = {
    Status.AWAITING_QUOTE: "🧮 در حال بررسی عکس‌ها هستیم؛ قیمت به‌زودی برایتان ارسال می‌شود.",
    Status.AWAITING_PAYMENT: "💳 مبلغ را واریز کنید و با دکمه زیر عکس رسید را بفرستید.",
    Status.PAYMENT_REVIEW: "🔎 رسید شما در حال بررسی است.",
    Status.IN_PROGRESS: "🎨 هنرمند در حال کشیدن اثر شماست.",
    Status.REVISION: "✏️ در حال اعمال اصلاحات درخواستی شما هستیم.",
    Status.PREVIEW_SENT: "👀 پیش‌نمایش ارسال شده؛ لطفاً تایید کنید یا درخواست اصلاح بدهید.",
    Status.PREVIEW_APPROVED: "📤 فایل نهایی به‌زودی برایتان ارسال می‌شود.",
    Status.DELIVERED: "🎁 اثر شما تحویل داده شده است. از دکمه زیر می‌توانید فایل‌ها را دوباره دریافت کنید.",
    Status.CANCELLED: "این سفارش لغو شده است.",
}


def progress_tracker(status: str) -> str:
    if status == Status.CANCELLED:
        return "❌ <b>لغو شده</b>"
    current = len(STAGES) if status == Status.DELIVERED else _STAGE_INDEX.get(status, 0)
    lines = []
    for i, (title, _) in enumerate(STAGES):
        if i < current:
            icon = "✅"
        elif i == current:
            icon = "🔄"
        else:
            icon = "⚪️"
        lines.append(f"{icon} {title}")
    return "\n".join(lines)


def order_card_user(order: dict) -> str:
    head = [
        f"🧾 <b>سفارش شماره #{fa(order['id'])}</b>",
        f"🕒 ثبت: {fmt_time(order['created_at'])}",
        "",
        "<b>📍 مراحل سفارش:</b>",
        progress_tracker(order["status"]),
        "",
        f"👈 {NEXT_STEP.get(order['status'], '')}",
        "",
        "<b>📋 جزئیات:</b>",
    ]
    tail = []
    if order["status"] == Status.AWAITING_PAYMENT and order.get("reject_reason"):
        tail = ["", f"⚠️ رسید قبلی تایید نشد: {esc(order['reject_reason'])}"]
    return "\n".join(head + order_lines(order) + tail)


def order_card_admin(order: dict, extra: dict | None = None) -> str:
    """Full details for admins. `extra` (optional): file counts and customer history."""
    uname = f"@{order['username']}" if order.get("username") else "—"
    head = [
        f"🧾 <b>سفارش #{order['id']}</b> — {Status.label(order['status'])}",
        "",
        f"👤 مشتری: <a href=\"tg://user?id={order['user_id']}\">{esc(order.get('full_name'))}</a> ({esc(uname)})",
        f"🆔 <code>{order['user_id']}</code>",
    ]
    if extra:
        head.append(f"📚 سوابق مشتری: {fa(extra['user_orders'])} سفارش، {fa(extra['user_paid'])} پرداخت‌شده")
    head += [
        f"🕒 ثبت: {fmt_time(order['created_at'])}",
        f"🔄 آخرین تغییر: {fmt_time(order['updated_at'])}",
        "",
    ]
    tail = []
    if extra:
        tail.append(
            f"\n📎 فایل‌ها: {fa(extra['reference'])} عکس مشتری • {fa(extra['receipt'])} رسید • "
            f"{fa(extra['preview'])} پیش‌نمایش • {fa(extra['final'])} فایل نهایی"
        )
    if order["status"] == Status.AWAITING_PAYMENT and order.get("reject_reason"):
        tail.append(f"\n⚠️ آخرین رسید رد شد: {esc(order['reject_reason'])}")
    if order.get("rating"):
        tail.append(f"\n⭐️ امتیاز مشتری: {'⭐️' * order['rating']}")
    return "\n".join(head + order_lines(order) + tail)
