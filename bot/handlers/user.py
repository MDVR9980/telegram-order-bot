"""Customer side: my orders, receipts, preview feedback, rating, invites, support."""
from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from ..callbacks import MyOrder, Preview, Rate
from ..context import db, referral_percent, setting, support_username
from ..db import Status
from ..services import apply_promo, cancel_order, submit_receipt
from ..states import PromoFlow, ReceiptFlow, RevisionFlow, SupportFlow
from ..texts import payment_text
from ..utils import (
    all_admin_ids,
    esc,
    extract_file,
    fa,
    money,
    notify_admins,
    order_card_admin,
    order_card_user,
    safe_edit,
    send_files,
)

router = Router(name="user")

MY_ORDERS_TITLE = "📦 <b>سفارش‌های شما</b>\nبرای جزئیات روی هر سفارش بزنید:"


async def _own_order(call: CallbackQuery, order_id: int) -> dict | None:
    order = await db.get_order(order_id)
    if not order or order["user_id"] != call.from_user.id:
        await call.answer("سفارش پیدا نشد.", show_alert=True)
        return None
    return order


# ---------- my orders ----------
async def my_orders(message: Message, state: FSMContext):
    await state.clear()
    orders = await db.user_orders(message.from_user.id)
    if not orders:
        await message.answer("📭 هنوز سفارشی ثبت نکرده‌اید.\nبا «🎨 ثبت سفارش جدید» اولین اثرتان را سفارش دهید ✨")
        return
    await message.answer(MY_ORDERS_TITLE, reply_markup=kb.my_orders_kb(orders))


@router.callback_query(MyOrder.filter(F.action == "list"))
async def my_orders_cb(call: CallbackQuery):
    orders = await db.user_orders(call.from_user.id)
    await safe_edit(call.message, MY_ORDERS_TITLE if orders else "📭 سفارشی ندارید.", kb.my_orders_kb(orders))
    await call.answer()


@router.callback_query(MyOrder.filter(F.action == "view"))
async def view_order(call: CallbackQuery, callback_data: MyOrder):
    order = await _own_order(call, callback_data.order_id)
    if order:
        await safe_edit(call.message, order_card_user(order), kb.my_order_kb(order))
        await call.answer()


@router.callback_query(MyOrder.filter(F.action == "cancel"))
async def cancel_ask(call: CallbackQuery, callback_data: MyOrder):
    order = await _own_order(call, callback_data.order_id)
    if not order:
        return
    if order["status"] not in (Status.AWAITING_QUOTE, Status.AWAITING_PAYMENT):
        await call.answer("این سفارش دیگر قابل لغو نیست. برای پیگیری با پشتیبانی در تماس باشید.", show_alert=True)
        return
    await safe_edit(call.message, f"❓ از لغو سفارش #{fa(order['id'])} مطمئن هستید؟", kb.cancel_order_confirm_kb(order["id"]))
    await call.answer()


@router.callback_query(MyOrder.filter(F.action == "cancel_yes"))
async def cancel_yes(call: CallbackQuery, callback_data: MyOrder, state: FSMContext, bot: Bot):
    order = await _own_order(call, callback_data.order_id)
    if not order:
        return
    cancelled = await cancel_order(order["id"], (Status.AWAITING_QUOTE, Status.AWAITING_PAYMENT))
    if not cancelled:
        await call.answer("این سفارش دیگر قابل لغو نیست.", show_alert=True)
        return
    if (await state.get_data()).get("order_id") == order["id"]:
        await state.clear()
    note = "\n🎁 تخفیف این سفارش به حساب شما برگشت." if cancelled["discount_kind"] else ""
    await safe_edit(call.message, f"🗑 سفارش #{fa(order['id'])} لغو شد.{note}")
    await call.answer()
    await notify_admins(bot, f"🗑 مشتری سفارش <b>#{order['id']}</b> را لغو کرد.")


@router.callback_query(MyOrder.filter(F.action == "pay"))
async def pay_order(call: CallbackQuery, callback_data: MyOrder, state: FSMContext):
    order = await _own_order(call, callback_data.order_id)
    if not order:
        return
    if order["status"] == Status.PAYMENT_REVIEW:
        await call.answer("رسید این سفارش در حال بررسی است 🔎", show_alert=True)
        return
    if order["status"] != Status.AWAITING_PAYMENT:
        await call.answer("این سفارش در انتظار پرداخت نیست.", show_alert=True)
        return
    await state.set_state(ReceiptFlow.waiting)
    await state.update_data(order_id=order["id"])
    await call.message.answer(
        f"📸 لطفاً <b>عکس رسید</b> پرداخت سفارش #{fa(order['id'])} را بفرستید:\n"
        f"<i>(مبلغ: {money(order['price'])} — کارت: <code>{esc(await setting('card_number'))}</code>)</i>",
        reply_markup=kb.cancel_menu(),
    )
    await call.answer()


@router.callback_query(MyOrder.filter(F.action == "files"))
async def resend_files(call: CallbackQuery, callback_data: MyOrder, bot: Bot):
    order = await _own_order(call, callback_data.order_id)
    if not order:
        return
    files = await db.get_files(order["id"], "final")
    if not files:
        await call.answer("فایلی برای این سفارش ثبت نشده است.", show_alert=True)
        return
    await call.answer("در حال ارسال... 📥")
    await send_files(bot, call.from_user.id, files, caption=f"🎁 فایل‌های سفارش #{fa(order['id'])}")


# ---------- promo code ----------
@router.callback_query(MyOrder.filter(F.action == "promo"))
async def promo_start(call: CallbackQuery, callback_data: MyOrder, state: FSMContext):
    order = await _own_order(call, callback_data.order_id)
    if not order:
        return
    if order["status"] != Status.AWAITING_PAYMENT:
        await call.answer("کد تخفیف فقط قبل از پرداخت قابل استفاده است.", show_alert=True)
        return
    await state.set_state(PromoFlow.code)
    await state.update_data(order_id=order["id"])
    await call.message.answer(f"🎟 کد تخفیف خود را برای سفارش #{fa(order['id'])} بنویسید:", reply_markup=kb.cancel_menu())
    await call.answer()


@router.message(PromoFlow.code, F.text)
async def promo_got(message: Message, state: FSMContext, is_admin: bool):
    data = await state.get_data()
    ok, text = await apply_promo(message.from_user.id, data.get("order_id", 0), message.text[:40])
    if not ok:
        await message.answer(text + "\n\nکد دیگری بنویسید یا «❌ انصراف» را بزنید.")
        return
    await state.clear()
    await message.answer(text, reply_markup=kb.main_menu(is_admin))
    order = await db.get_order(data["order_id"])
    await message.answer(await payment_text(order), reply_markup=kb.pay_kb(order["id"]))


@router.message(PromoFlow.code)
async def promo_wrong(message: Message):
    await message.answer("🎟 لطفاً کد تخفیف را به صورت متن بنویسید.")


# ---------- receipt ----------
@router.message(ReceiptFlow.waiting, F.photo | F.document)
async def got_receipt(message: Message, state: FSMContext, bot: Bot, is_admin: bool):
    data = await state.get_data()
    await state.clear()
    file_id, file_type = extract_file(message)
    text = await submit_receipt(bot, message.from_user.id, data.get("order_id", 0), file_id, file_type)
    await message.answer(text, reply_markup=kb.main_menu(is_admin))


@router.message(ReceiptFlow.waiting)
async def receipt_wrong(message: Message):
    await message.answer("📸 لطفاً <b>عکس رسید</b> پرداخت را ارسال کنید (یا «❌ انصراف»).")


# A photo sent outside any flow: if the customer owes a payment, offer to use it as the receipt.
@router.message(StateFilter(None), F.photo | F.document)
async def stray_file(message: Message, state: FSMContext):
    unpaid = await db.user_orders_in(message.from_user.id, (Status.AWAITING_PAYMENT,))
    if not unpaid:
        await message.answer(
            "📸 عکس دریافت شد، اما الان منتظر عکسی نبودم!\n\n"
            "▫️ برای سفارش جدید: «🎨 ثبت سفارش جدید»\n"
            "▫️ برای پیگیری سفارش‌ها: «📦 سفارش‌های من»"
        )
        return
    file_id, file_type = extract_file(message)
    await state.update_data(pending_receipt=[file_id, file_type])
    await message.answer("🧾 این عکس، رسید پرداخت کدام سفارش است؟", reply_markup=kb.receipt_pick_kb(unpaid))


@router.callback_query(MyOrder.filter(F.action == "receipt_for"))
async def receipt_for(call: CallbackQuery, callback_data: MyOrder, state: FSMContext, bot: Bot):
    data = await state.get_data()
    pending = data.get("pending_receipt")
    if not pending:
        await call.answer("عکس رسید پیدا نشد؛ لطفاً دوباره بفرستید.", show_alert=True)
        return
    await state.update_data(pending_receipt=None)
    text = await submit_receipt(bot, call.from_user.id, callback_data.order_id, pending[0], pending[1])
    await safe_edit(call.message, text)
    await call.answer()


# ---------- preview feedback ----------
@router.callback_query(Preview.filter(F.action == "ok"))
async def preview_ok(call: CallbackQuery, callback_data: Preview, bot: Bot):
    order = await _own_order(call, callback_data.order_id)
    if not order:
        return
    if not await db.transition(order["id"], (Status.PREVIEW_SENT,), Status.PREVIEW_APPROVED):
        await call.answer("این پیش‌نمایش قبلاً بررسی شده است.", show_alert=True)
        return
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("😍 عالیه! فایل نهایی با کیفیت کامل به‌زودی برایتان ارسال می‌شود.")
    await call.answer()
    order = await db.get_order(order["id"])
    await notify_admins(bot, "👍 <b>مشتری پیش‌نمایش را تایید کرد</b> — آماده تحویل نهایی\n\n" + order_card_admin(order), kb.admin_order_kb(order))


@router.callback_query(Preview.filter(F.action == "revise"))
async def preview_revise(call: CallbackQuery, callback_data: Preview, state: FSMContext):
    order = await _own_order(call, callback_data.order_id)
    if not order:
        return
    if order["status"] != Status.PREVIEW_SENT:
        await call.answer("این پیش‌نمایش قبلاً بررسی شده است.", show_alert=True)
        return
    await state.set_state(RevisionFlow.text)
    await state.update_data(order_id=order["id"])
    await call.message.answer("✏️ لطفاً بنویسید چه تغییراتی مد نظرتان است (دقیق و واضح):", reply_markup=kb.cancel_menu())
    await call.answer()


@router.message(RevisionFlow.text, F.text)
async def got_revision(message: Message, state: FSMContext, bot: Bot, is_admin: bool):
    data = await state.get_data()
    await state.clear()
    if not await db.transition(data.get("order_id", 0), (Status.PREVIEW_SENT,), Status.REVISION):
        await message.answer("⚠️ این سفارش دیگر در مرحله پیش‌نمایش نیست.", reply_markup=kb.main_menu(is_admin))
        return
    await message.answer(
        "📝 درخواست اصلاح ثبت شد. پس از اعمال تغییرات، پیش‌نمایش جدید برایتان ارسال می‌شود.",
        reply_markup=kb.main_menu(is_admin),
    )
    order = await db.get_order(data["order_id"])
    await notify_admins(
        bot,
        f"✏️ <b>درخواست اصلاح</b> برای سفارش #{order['id']}:\n\n<blockquote>{esc(message.text)}</blockquote>\n\n" + order_card_admin(order),
        kb.admin_order_kb(order),
    )


@router.message(RevisionFlow.text)
async def revision_wrong(message: Message):
    await message.answer("✏️ لطفاً تغییرات مورد نظر را به صورت متن بنویسید.")


# ---------- rating ----------
@router.callback_query(Rate.filter())
async def rate(call: CallbackQuery, callback_data: Rate, bot: Bot):
    order = await _own_order(call, callback_data.order_id)
    if not order:
        return
    if order["status"] != Status.DELIVERED:
        await call.answer()
        return
    stars = max(1, min(5, callback_data.stars))
    first_time = order["rating"] is None
    await db.set_rating(order["id"], stars)
    await safe_edit(call.message, f"🙏 ممنون از امتیاز شما: {'⭐️' * stars}\nامیدواریم باز هم میزبان شما باشیم 🤍")
    await call.answer()
    if first_time:
        await notify_admins(bot, f"⭐️ مشتری سفارش #{order['id']} امتیاز {'⭐️' * stars} داد.")


# ---------- invite friends ----------
async def invite(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    me = await bot.me()
    link = f"https://t.me/{me.username}?start=ref_{message.from_user.id}"
    percent = fa(await referral_percent())
    stats = await db.referral_stats(message.from_user.id)
    condition = (
        "به محض اینکه دوستتان ربات را با لینک شما استارت کند"
        if await setting("referral_mode") == "join"
        else "بعد از اینکه دوستتان اولین سفارشش را پرداخت کند"
    )
    text = (
        "🎁 <b>دعوت دوستان = تخفیف!</b>\n\n"
        f"لینک اختصاصی خودتان را برای دوستانتان بفرستید. {condition}، "
        f"یک کد تخفیف <b>{percent}٪</b> به حساب شما اضافه می‌شود.\n\n"
        "▫️ کد تخفیف روی سفارش بعدی‌تان <b>خودکار</b> اعمال می‌شود.\n"
        "▫️ روی هر سفارش یک کد تخفیف استفاده می‌شود.\n"
        "▫️ فقط کاربرانی حساب می‌شوند که قبلاً عضو ربات نبوده‌اند.\n\n"
        f"🔗 لینک شما:\n<code>{link}</code>\n\n"
        f"👥 دعوت‌شده‌ها: <b>{fa(stats['invited'])}</b>\n"
        f"🎟 کدهای تخفیف آماده استفاده: <b>{fa(stats['credits'] or 0)}</b>"
    )
    share = "🎨 با لینوریا عکس‌هات رو به یک نقاشی دست‌ساز و ماندگار تبدیل کن! از اینجا سفارش بده 👇"
    await message.answer(text, reply_markup=kb.invite_kb(link, share))


# ---------- support ----------
async def support(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "💬 <b>پشتیبانی لینوریا</b>\n\nسوال، پیشنهاد یا مشکلی دارید؟ یکی از راه‌های زیر را انتخاب کنید:",
        reply_markup=kb.support_kb(await support_username()),
    )


@router.callback_query(F.data == "support:write")
async def support_write(call: CallbackQuery, state: FSMContext):
    await state.set_state(SupportFlow.text)
    await call.message.answer("✉️ پیامتان را بنویسید (متن، عکس یا ویس):", reply_markup=kb.cancel_menu())
    await call.answer()


@router.message(SupportFlow.text)
async def support_message(message: Message, state: FSMContext, bot: Bot, is_admin: bool):
    await state.clear()
    user = message.from_user
    uname = f"@{user.username}" if user.username else "—"
    header = (
        f"📨 <b>پیام پشتیبانی</b>\n"
        f"👤 <a href=\"tg://user?id={user.id}\">{esc(user.full_name)}</a> ({esc(uname)})\n"
        f"🆔 <code>{user.id}</code>"
    )
    delivered = False
    for admin_id in await all_admin_ids():
        try:
            await bot.send_message(admin_id, header)
            await message.copy_to(admin_id, reply_markup=kb.reply_user_kb(user.id))
            delivered = True
        except Exception:  # noqa: BLE001
            pass
    if delivered:
        await message.answer("✅ پیام شما برای پشتیبانی ارسال شد. به‌زودی پاسخ می‌دهیم 🤍", reply_markup=kb.main_menu(is_admin))
    else:
        await message.answer(
            "⚠️ ارسال پیام ناموفق بود. لطفاً مستقیم از طریق دکمه پشتیبانی پیام دهید.",
            reply_markup=kb.main_menu(is_admin),
        )
