from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .callbacks import Adm, MyOrder, Nav, Pick, Preview, Rate
from .catalog import Option
from .context import catalog
from .db import Status
from .utils import fa, money

# ---------- reply (main menu) ----------
BTN_ORDER = "🎨 ثبت سفارش جدید"
BTN_MY_ORDERS = "📦 سفارش‌های من"
BTN_PRICES = "💰 تعرفه‌ها"
BTN_SAMPLES = "🖼 نمونه‌کارها"
BTN_HELP = "📖 راهنما"
BTN_SUPPORT = "💬 پشتیبانی"
BTN_INVITE = "🎁 دعوت دوستان (تخفیف)"
BTN_ADMIN = "🛠 پنل مدیریت"
BTN_CANCEL = "❌ انصراف"


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_ORDER)],
        [KeyboardButton(text=BTN_MY_ORDERS), KeyboardButton(text=BTN_PRICES)],
        [KeyboardButton(text=BTN_SAMPLES), KeyboardButton(text=BTN_HELP)],
        [KeyboardButton(text=BTN_INVITE), KeyboardButton(text=BTN_SUPPORT)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, input_field_placeholder="یک گزینه را انتخاب کنید 👇")


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True)


# ---------- order wizard ----------
def options_kb(field: str, options: list[Option], with_back: bool = True) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for o in options:
        kb.button(text=o.title, callback_data=Pick(field=field, value=o.id))
    kb.adjust(1)
    nav = []
    if with_back:
        nav.append(InlineKeyboardButton(text="🔙 مرحله قبل", callback_data=Nav(action="back").pack()))
    nav.append(InlineKeyboardButton(text="✖️ انصراف", callback_data=Nav(action="cancel").pack()))
    kb.row(*nav)
    return kb.as_markup()


def photos_kb(count: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if count:
        kb.button(text=f"✅ ادامه ({fa(count)} عکس دریافت شد)", callback_data=Nav(action="photos_done"))
    kb.button(text="🔙 مرحله قبل", callback_data=Nav(action="back"))
    kb.button(text="✖️ انصراف", callback_data=Nav(action="cancel"))
    kb.adjust(1, 2)
    return kb.as_markup()


def skip_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⏭ توضیحی ندارم", callback_data=Nav(action="skip_desc"))
    kb.button(text="🔙 مرحله قبل", callback_data=Nav(action="back"))
    kb.adjust(1)
    return kb.as_markup()


def confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ ثبت نهایی سفارش", callback_data=Nav(action="confirm"))
    kb.button(text="✏️ شروع دوباره", callback_data=Nav(action="edit"))
    kb.button(text="✖️ انصراف", callback_data=Nav(action="cancel"))
    kb.adjust(1, 2)
    return kb.as_markup()


# ---------- customer orders ----------
def my_orders_kb(orders: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for o in orders:
        kb.button(
            text=f"سفارش #{fa(o['id'])} • {Status.label(o['status'])}",
            callback_data=MyOrder(action="view", order_id=o["id"]),
        )
    kb.adjust(1)
    return kb.as_markup()


def my_order_kb(order: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    oid = order["id"]
    if order["status"] == Status.AWAITING_PAYMENT:
        kb.button(text="💳 پرداخت و ارسال رسید", callback_data=MyOrder(action="pay", order_id=oid))
        kb.button(text="🎟 کد تخفیف دارم", callback_data=MyOrder(action="promo", order_id=oid))
    if order["status"] in (Status.AWAITING_QUOTE, Status.AWAITING_PAYMENT):
        kb.button(text="🗑 لغو سفارش", callback_data=MyOrder(action="cancel", order_id=oid))
    if order["status"] == Status.PREVIEW_SENT:
        kb.button(text="👍 تایید پیش‌نمایش", callback_data=Preview(action="ok", order_id=oid))
        kb.button(text="✏️ درخواست اصلاح", callback_data=Preview(action="revise", order_id=oid))
    if order["status"] == Status.DELIVERED:
        kb.button(text="📥 دریافت دوباره فایل‌ها", callback_data=MyOrder(action="files", order_id=oid))
    kb.button(text="🔙 لیست سفارش‌ها", callback_data=MyOrder(action="list"))
    kb.adjust(1)
    return kb.as_markup()


def pay_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📸 ارسال عکس رسید", callback_data=MyOrder(action="pay", order_id=order_id))
    kb.button(text="🎟 کد تخفیف دارم", callback_data=MyOrder(action="promo", order_id=order_id))
    kb.button(text="🗑 لغو سفارش", callback_data=MyOrder(action="cancel", order_id=order_id))
    kb.adjust(1, 2)
    return kb.as_markup()


def cancel_order_confirm_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ بله، لغو شود", callback_data=MyOrder(action="cancel_yes", order_id=order_id))
    kb.button(text="🔙 خیر", callback_data=MyOrder(action="view", order_id=order_id))
    kb.adjust(2)
    return kb.as_markup()


def receipt_pick_kb(orders: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for o in orders:
        kb.button(text=f"🧾 رسید سفارش #{fa(o['id'])} ({money(o['price'])})", callback_data=MyOrder(action="receipt_for", order_id=o["id"]))
    kb.adjust(1)
    return kb.as_markup()


def invite_kb(link: str, share_text: str) -> InlineKeyboardMarkup:
    from urllib.parse import quote

    kb = InlineKeyboardBuilder()
    kb.button(text="📤 ارسال لینک برای دوستان", url=f"https://t.me/share/url?url={quote(link)}&text={quote(share_text)}")
    return kb.as_markup()


def preview_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="😍 عالیه، تایید می‌کنم", callback_data=Preview(action="ok", order_id=order_id))
    kb.button(text="✏️ نیاز به اصلاح دارد", callback_data=Preview(action="revise", order_id=order_id))
    kb.adjust(1)
    return kb.as_markup()


def rate_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in range(5, 0, -1):
        kb.button(text="⭐️" * s, callback_data=Rate(order_id=order_id, stars=s))
    kb.adjust(1)
    return kb.as_markup()


def support_kb(username: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✉️ ارسال پیام از طریق ربات", callback_data="support:write")
    if username:
        kb.button(text=f"💬 چت با @{username}", url=f"https://t.me/{username}")
    kb.adjust(1)
    return kb.as_markup()


def samples_kb(channel_url: str) -> InlineKeyboardMarkup | None:
    if not channel_url.startswith(("https://", "http://", "tg://")):
        return None
    kb = InlineKeyboardBuilder()
    kb.button(text="🖼 مشاهده نمونه‌کارها در کانال", url=channel_url)
    return kb.as_markup()


# ---------- admin ----------
ORDER_FILTERS = {
    "quote": ("🧮 منتظر قیمت", (Status.AWAITING_QUOTE,)),
    "review": ("🔎 رسیدهای در انتظار", (Status.PAYMENT_REVIEW,)),
    "work": ("🎨 در حال انجام", (Status.IN_PROGRESS, Status.REVISION, Status.PREVIEW_APPROVED)),
    "preview": ("👀 منتظر نظر مشتری", (Status.PREVIEW_SENT,)),
    "unpaid": ("⏳ پرداخت نشده", (Status.AWAITING_PAYMENT,)),
    "done": ("✅ تحویل شده", (Status.DELIVERED,)),
    "cancelled": ("❌ لغو شده", (Status.CANCELLED,)),
    "all": ("📋 همه سفارش‌ها", tuple(Status.LABELS)),
}


def admin_panel_kb(counts: dict[str, int], is_super: bool, orders_open: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, (title, _) in ORDER_FILTERS.items():
        kb.button(text=f"{title} ({fa(counts.get(key, 0))})", callback_data=Adm(action="list", arg=key))
    kb.button(text="🔍 جستجوی سفارش", callback_data=Adm(action="find"))
    kb.button(text="📊 آمار", callback_data=Adm(action="stats"))
    kb.button(text="📣 پیام همگانی", callback_data=Adm(action="broadcast"))
    kb.button(text="🎨 خدمات و قیمت‌ها", callback_data=Adm(action="catalog"))
    kb.button(text="🎟 کدهای تخفیف", callback_data=Adm(action="promos"))
    kb.button(text="⚙️ تنظیمات", callback_data=Adm(action="settings"))
    kb.button(
        text="🟢 پذیرش سفارش: باز" if orders_open else "🔴 پذیرش سفارش: بسته",
        callback_data=Adm(action="toggle_open"),
    )
    if is_super:
        kb.button(text="👥 مدیریت ادمین‌ها", callback_data=Adm(action="admins"))
    kb.adjust(1, 2, 2, 2, 1, 2, 2, 2, 1, 1, 1)
    return kb.as_markup()


def admin_list_kb(orders: list[dict], filter_key: str, page: int, has_next: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for o in orders:
        name = (o.get("full_name") or "")[:18]
        kb.button(text=f"#{o['id']} • {name} • {Status.label(o['status'])}", callback_data=Adm(action="view", order_id=o["id"]))
    kb.adjust(1)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=Adm(action="list", arg=f"{filter_key}~{page - 1}").pack()))
    if has_next:
        nav.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=Adm(action="list", arg=f"{filter_key}~{page + 1}").pack()))
    if nav:
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text="🔙 پنل مدیریت", callback_data=Adm(action="panel").pack()))
    return kb.as_markup()


def admin_order_kb(order: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    oid, st = order["id"], order["status"]
    if st == Status.AWAITING_QUOTE:
        for p in catalog.quick_prices:
            kb.button(text=f"💰 {fa(f'{p // 1000:,}')} هزار", callback_data=Adm(action="quote", order_id=oid, arg=str(p)))
        kb.button(text="✍️ مبلغ دلخواه", callback_data=Adm(action="quote_custom", order_id=oid))
    if st == Status.PAYMENT_REVIEW:
        kb.button(text="✅ تایید پرداخت", callback_data=Adm(action="approve", order_id=oid))
        kb.button(text="❌ رد رسید", callback_data=Adm(action="reject", order_id=oid))
        kb.button(text="🧾 مشاهده رسید", callback_data=Adm(action="receipt", order_id=oid))
    elif st == Status.AWAITING_PAYMENT:
        kb.button(text="✅ تایید دستی پرداخت", callback_data=Adm(action="approve", order_id=oid))
        kb.button(text="✏️ تغییر قیمت", callback_data=Adm(action="quote_custom", order_id=oid))
    if st in Status.WORKING:
        kb.button(text="👀 ارسال پیش‌نمایش", callback_data=Adm(action="upload", order_id=oid, arg="preview"))
        kb.button(text="📤 تحویل فایل نهایی", callback_data=Adm(action="upload", order_id=oid, arg="final"))
    kb.button(text="🖼 عکس‌های مشتری", callback_data=Adm(action="files", order_id=oid, arg="reference"))
    if st not in (Status.AWAITING_QUOTE, Status.AWAITING_PAYMENT, Status.PAYMENT_REVIEW):
        kb.button(text="🧾 رسید پرداخت", callback_data=Adm(action="receipt", order_id=oid))
    if st in (Status.PREVIEW_SENT, Status.REVISION, Status.PREVIEW_APPROVED, Status.DELIVERED):
        kb.button(text="👀 پیش‌نمایش‌ها", callback_data=Adm(action="files", order_id=oid, arg="preview"))
    if st == Status.DELIVERED:
        kb.button(text="📁 فایل‌های تحویلی", callback_data=Adm(action="files", order_id=oid, arg="final"))
    kb.button(text="💬 پیام به مشتری", callback_data=Adm(action="msg", order_id=oid))
    if st in Status.ACTIVE:
        kb.button(text="🗑 لغو سفارش", callback_data=Adm(action="cancel", order_id=oid))
    kb.button(text="🔄 بروزرسانی", callback_data=Adm(action="view", order_id=oid))
    kb.adjust(2)
    return kb.as_markup()


def confirm_cancel_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ بله، لغو شود", callback_data=Adm(action="cancel_yes", order_id=order_id))
    kb.button(text="🔙 خیر", callback_data=Adm(action="view", order_id=order_id))
    return kb.as_markup()


def upload_kb(count: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if count:
        kb.button(text=f"🚀 ارسال برای مشتری ({fa(count)} فایل)", callback_data=Adm(action="upload_done"))
    kb.button(text="✖️ انصراف", callback_data=Adm(action="abort"))
    kb.adjust(1)
    return kb.as_markup()


def reject_reasons_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, reason in enumerate(REJECT_REASONS):
        kb.button(text=reason, callback_data=Adm(action="reject_quick", order_id=order_id, arg=str(i)))
    kb.button(text="✖️ انصراف", callback_data=Adm(action="abort"))
    kb.adjust(1)
    return kb.as_markup()


REJECT_REASONS = [
    "مبلغ واریزی با مبلغ سفارش مطابقت ندارد",
    "رسید ناخوانا یا نامعتبر است",
    "واریزی به حساب ما نرسیده است",
]


def abort_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✖️ انصراف", callback_data=Adm(action="abort"))
    return kb.as_markup()


def reply_user_kb(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="↩️ پاسخ", callback_data=Adm(action="reply", arg=str(user_id)))
    kb.button(text="🚫 مسدود کردن", callback_data=Adm(action="block", arg=str(user_id)))
    return kb.as_markup()


SETTING_LABELS = {
    "card_number": "💳 شماره کارت",
    "card_holder": "👤 نام صاحب کارت",
    "bank_name": "🏦 نام بانک",
    "delivery_time": "⏱ زمان آماده‌سازی",
    "referral_percent": "🎁 درصد تخفیف دعوت",
    "support_username": "💬 آیدی پشتیبانی",
    "channel_url": "📢 لینک کانال",
    "welcome_text": "👋 متن خوش‌آمد",
    "art_spec": "✏️ متن سبک و سایز",
}


def settings_kb(values: dict[str, str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, label in SETTING_LABELS.items():
        value = values.get(key, "")
        if key == "welcome_text":
            value = "سفارشی" if value else "پیش‌فرض"
        elif key == "art_spec":
            value = "ویرایش"
        kb.button(text=f"{label}: {value[:30]}", callback_data=Adm(action="set", arg=key))
    mode = "با عضویت دوست" if values.get("referral_mode") == "join" else "بعد از اولین خرید دوست"
    kb.button(text=f"🎁 شرط تخفیف دعوت: {mode}", callback_data=Adm(action="toggle_ref_mode"))
    kb.button(text="🔙 پنل مدیریت", callback_data=Adm(action="panel"))
    kb.adjust(1)
    return kb.as_markup()


def admins_kb(admins: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for a in admins:
        name = a.get("full_name") or str(a["user_id"])
        kb.button(text=f"🗑 حذف {name}", callback_data=Adm(action="del_admin", arg=str(a["user_id"])))
    kb.button(text="➕ افزودن ادمین", callback_data=Adm(action="add_admin"))
    kb.button(text="🔙 پنل مدیریت", callback_data=Adm(action="panel"))
    kb.adjust(1)
    return kb.as_markup()


def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ ارسال برای همه", callback_data=Adm(action="broadcast_go"))
    kb.button(text="✖️ انصراف", callback_data=Adm(action="abort"))
    kb.adjust(1)
    return kb.as_markup()
