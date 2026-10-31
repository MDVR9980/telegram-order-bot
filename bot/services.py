"""Business actions shared by customer and admin handlers."""
import logging

from aiogram import Bot

from . import keyboards as kb
from .context import db, referral_percent, setting
from .db import Status
from .db import now
from .utils import apply_discount, fa, money, notify_admins, order_card_admin

log = logging.getLogger(__name__)


async def _tell(bot: Bot, user_id: int, text: str, markup=None) -> None:
    try:
        await bot.send_message(user_id, text, reply_markup=markup)
    except Exception as e:  # noqa: BLE001  (user blocked the bot, etc.)
        log.warning("cannot message %s: %s", user_id, e)


# ---------- pricing / discounts ----------
def compute_price(base: int, percent: int, fixed: int) -> tuple[int, int]:
    """Returns (discount_amount, final_price)."""
    if percent:
        price = apply_discount(base, percent)
    elif fixed:
        price = max(0, base - fixed)
    else:
        price = base
    return base - price, price


async def release_discount(order: dict) -> None:
    """Give back whatever discount an order was holding (referral coupon or promo code use)."""
    if order.get("discount_kind") == "referral":
        await db.give_back_credit(order["user_id"])
    elif order.get("discount_kind") == "promo" and order.get("discount_code"):
        await db.release_promo(order["discount_code"], order["user_id"])


async def cancel_order(order_id: int, allowed: tuple[str, ...]) -> dict | None:
    """Cancel if the order is in `allowed` statuses. Returns the order (before cancel) or None."""
    order = await db.get_order(order_id)
    if not order or not await db.transition(order_id, allowed, Status.CANCELLED):
        return None
    await release_discount(order)
    return order


async def set_quote(order_id: int, base_price: int) -> dict | None:
    """Set/changes the base price. On the first quote a referral coupon (if any) is used automatically.
    An existing discount (referral or promo) is kept and recalculated on the new price."""
    order = await db.get_order(order_id)
    if not order or order["status"] not in (Status.AWAITING_QUOTE, Status.AWAITING_PAYMENT):
        return None
    kind, code = order["discount_kind"], order["discount_code"]
    percent, fixed = order["discount_percent"], order["discount_fixed"]
    took_credit = False
    if order["status"] == Status.AWAITING_QUOTE and not kind:
        p = await referral_percent()
        if p and await db.take_credit(order["user_id"]):
            kind, percent, took_credit = "referral", p, True
    amount, price = compute_price(base_price, percent, fixed)
    ok = await db.set_pricing(
        order_id, (Status.AWAITING_QUOTE, Status.AWAITING_PAYMENT),
        base_price=base_price, discount_kind=kind, discount_code=code, discount_percent=percent,
        discount_fixed=fixed, discount_amount=amount, price=price,
    )
    if not ok:
        if took_credit:
            await db.give_back_credit(order["user_id"])
        return None
    return await db.get_order(order_id)


def promo_label(promo: dict) -> str:
    return f"{fa(promo['value'])}٪" if promo["kind"] == "percent" else money(promo["value"])


async def apply_promo(user_id: int, order_id: int, raw_code: str) -> tuple[bool, str]:
    code = raw_code.strip().upper()
    order = await db.get_order(order_id)
    if not order or order["user_id"] != user_id:
        return False, "⚠️ سفارش پیدا نشد."
    if order["status"] != Status.AWAITING_PAYMENT:
        return False, "⚠️ کد تخفیف فقط قبل از پرداخت قابل استفاده است."
    promo = await db.get_promo(code)
    if not promo or not promo["active"]:
        return False, "❌ این کد تخفیف معتبر نیست."
    if promo["expires_at"] and promo["expires_at"] <= now():
        return False, "⌛️ مهلت استفاده از این کد تخفیف تمام شده است."
    if promo["max_uses"] is not None and promo["used"] >= promo["max_uses"]:
        return False, "😔 ظرفیت این کد تخفیف تکمیل شده است."
    if order["discount_code"] == code:
        return False, "✅ این کد قبلاً روی همین سفارش اعمال شده است."
    if await db.promo_used_by(code, user_id):
        return False, "⚠️ شما قبلاً از این کد تخفیف استفاده کرده‌اید."

    percent = promo["value"] if promo["kind"] == "percent" else 0
    fixed = promo["value"] if promo["kind"] == "amount" else 0
    amount, price = compute_price(order["base_price"], percent, fixed)
    if amount <= order["discount_amount"]:
        return False, (
            "ℹ️ تخفیف فعلی این سفارش از این کد بیشتر یا برابر است، پس کد اعمال نشد.\n"
            "<i>(روی هر سفارش فقط یک تخفیف قابل استفاده است.)</i>"
        )
    if not await db.claim_promo(code, user_id, order_id):
        return False, "❌ این کد تخفیف دیگر قابل استفاده نیست."
    ok = await db.set_pricing(
        order_id, (Status.AWAITING_PAYMENT,),
        base_price=order["base_price"], discount_kind="promo", discount_code=code,
        discount_percent=percent, discount_fixed=fixed, discount_amount=amount, price=price,
    )
    if not ok:
        await db.release_promo(code, user_id)
        return False, "⚠️ وضعیت سفارش تغییر کرده است؛ لطفاً دوباره بررسی کنید."
    await release_discount(order)  # the previous discount (if any) is returned
    note = "\n🎁 کد تخفیف دعوتِ قبلی به حساب شما برگشت." if order["discount_kind"] == "referral" else ""
    return True, f"🎉 کد <b>{code}</b> با موفقیت اعمال شد! ({promo_label(promo)} تخفیف){note}"


# ---------- receipts ----------
async def submit_receipt(bot: Bot, user_id: int, order_id: int, file_id: str, file_type: str) -> str:
    """Returns a message for the customer."""
    order = await db.get_order(order_id)
    if not order or order["user_id"] != user_id:
        return "⚠️ سفارش پیدا نشد."
    if order["status"] == Status.PAYMENT_REVIEW:
        return "🔎 رسید این سفارش قبلاً ارسال شده و در حال بررسی است. نتیجه به شما اطلاع داده می‌شود."
    if not await db.transition(order_id, (Status.AWAITING_PAYMENT,), Status.PAYMENT_REVIEW):
        return "⚠️ این سفارش در انتظار پرداخت نیست. از «📦 سفارش‌های من» وضعیت را بررسی کنید."
    await db.add_file(order_id, "receipt", file_id, file_type)
    order = await db.get_order(order_id)
    await notify_admins(
        bot,
        "💳 <b>رسید پرداخت جدید</b>\n\n" + order_card_admin(order),
        kb.admin_order_kb(order),
        files=[{"file_id": file_id, "file_type": file_type}],
    )
    return (
        f"✅ رسید سفارش <b>#{fa(order_id)}</b> دریافت شد.\n\n"
        "🔎 پس از بررسی و تایید پرداخت، کار شروع می‌شود و به شما اطلاع داده خواهد شد. ممنون از صبوری‌تان 🤍"
    )


# ---------- referrals ----------
async def _notify_referrer(bot: Bot, referrer_id: int, purchased: bool) -> None:
    percent = fa(await referral_percent())
    event = "اولین سفارشش را در لینوریا ثبت کرد" if purchased else "با لینک شما به لینوریا پیوست"
    await _tell(
        bot,
        referrer_id,
        f"🎉 یکی از دوستانی که دعوت کرده بودید {event}!\n"
        f"🎁 یک کد تخفیف <b>{percent}٪</b> به حساب شما اضافه شد و روی سفارش بعدی‌تان خودکار اعمال می‌شود.",
    )


async def register_referral(bot: Bot, user_id: int, payload: str, is_new: bool) -> None:
    """Called on /start ref_<id>. Only brand-new users count, and nobody can invite themselves."""
    if not is_new or not payload.startswith("ref_"):
        return
    try:
        referrer_id = int(payload[4:])
    except ValueError:
        return
    if referrer_id == user_id or not await db.get_user(referrer_id):
        return
    await db.set_referrer(user_id, referrer_id)
    if await setting("referral_mode") == "join":
        rewarded = await db.reward_referrer(user_id)
        if rewarded:
            await _notify_referrer(bot, rewarded, purchased=False)


async def on_payment_approved(bot: Bot, order: dict) -> None:
    if await setting("referral_mode") != "join":
        rewarded = await db.reward_referrer(order["user_id"])
        if rewarded:
            await _notify_referrer(bot, rewarded, purchased=True)
