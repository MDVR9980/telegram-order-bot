"""Customer side: my orders, receipts, preview feedback, rating, support."""
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from ..callbacks import MyOrder, Preview, Rate
from ..context import db
from ..db import Status
from ..states import ReceiptFlow, RevisionFlow, SupportFlow
from ..texts import payment_text
from ..utils import (
    all_admin_ids,
    esc,
    extract_file,
    fa,
    notify_admins,
    order_card_admin,
    order_card_user,
    send_files,
)

router = Router(name="user")


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
    await message.answer("📦 <b>سفارش‌های شما</b>\nبرای جزئیات روی هر سفارش بزنید:", reply_markup=kb.my_orders_kb(orders))


@router.callback_query(MyOrder.filter(F.action == "list"))
async def my_orders_cb(call: CallbackQuery):
    orders = await db.user_orders(call.from_user.id)
    await call.message.edit_text("📦 <b>سفارش‌های شما</b>\nبرای جزئیات روی هر سفارش بزنید:", reply_markup=kb.my_orders_kb(orders))
    await call.answer()


@router.callback_query(MyOrder.filter(F.action == "view"))
async def view_order(call: CallbackQuery, callback_data: MyOrder):
    order = await _own_order(call, callback_data.order_id)
    if order:
        await call.message.edit_text(order_card_user(order), reply_markup=kb.my_order_kb(order))
        await call.answer()


@router.callback_query(MyOrder.filter(F.action == "cancel"))
async def cancel_order(call: CallbackQuery, callback_data: MyOrder, state: FSMContext, bot: Bot):
    order = await _own_order(call, callback_data.order_id)
    if not order:
        return
    if order["status"] != Status.AWAITING_PAYMENT:
        await call.answer("این سفارش دیگر قابل لغو نیست. برای پیگیری با پشتیبانی در تماس باشید.", show_alert=True)
        return
    await db.set_status(order["id"], Status.CANCELLED)
    await state.clear()
    await call.message.edit_text(f"🗑 سفارش #{fa(order['id'])} لغو شد.")
    await call.answer()
    await notify_admins(bot, f"🗑 مشتری سفارش <b>#{order['id']}</b> را لغو کرد.")


@router.callback_query(MyOrder.filter(F.action == "pay"))
async def pay_order(call: CallbackQuery, callback_data: MyOrder, state: FSMContext):
    order = await _own_order(call, callback_data.order_id)
    if not order:
        return
    if order["status"] != Status.AWAITING_PAYMENT:
        await call.answer("این سفارش در انتظار پرداخت نیست.", show_alert=True)
        return
    await state.set_state(ReceiptFlow.waiting)
    await state.update_data(order_id=order["id"])
    await call.message.answer(await payment_text(order["id"], order["price"]), reply_markup=kb.pay_kb(order["id"]))
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


# ---------- receipt ----------
@router.message(ReceiptFlow.waiting, F.photo | F.document)
async def got_receipt(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    order = await db.get_order(data.get("order_id", 0))
    if not order or order["user_id"] != message.from_user.id or order["status"] != Status.AWAITING_PAYMENT:
        await state.clear()
        await message.answer("⚠️ این سفارش در انتظار پرداخت نیست. از «📦 سفارش‌های من» وضعیت را بررسی کنید.")
        return
    file_id, file_type = extract_file(message)
    await db.add_file(order["id"], "receipt", file_id, file_type)
    await db.set_status(order["id"], Status.PAYMENT_REVIEW)
    await state.clear()
    await message.answer(
        f"✅ رسید سفارش <b>#{fa(order['id'])}</b> دریافت شد.\n\n"
        "🔎 پس از بررسی و تایید پرداخت، کار شروع می‌شود و نتیجه به شما اطلاع داده خواهد شد. ممنون از صبوری‌تان 🤍"
    )
    order = await db.get_order(order["id"])
    await notify_admins(
        bot,
        "💳 <b>رسید پرداخت جدید</b>\n\n" + order_card_admin(order),
        kb.admin_order_kb(order),
        files=[{"file_id": file_id, "file_type": file_type}],
    )


@router.message(ReceiptFlow.waiting)
async def receipt_wrong(message: Message):
    await message.answer("📸 لطفاً <b>عکس رسید</b> پرداخت را ارسال کنید (یا «❌ انصراف»).")


# ---------- preview feedback ----------
@router.callback_query(Preview.filter(F.action == "ok"))
async def preview_ok(call: CallbackQuery, callback_data: Preview, bot: Bot):
    order = await _own_order(call, callback_data.order_id)
    if not order:
        return
    if order["status"] != Status.PREVIEW_SENT:
        await call.answer("این پیش‌نمایش قبلاً بررسی شده است.", show_alert=True)
        return
    await db.set_status(order["id"], Status.PREVIEW_APPROVED)
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
    await call.message.answer(
        "✏️ لطفاً بنویسید چه تغییراتی مد نظرتان است (دقیق و واضح):",
        reply_markup=kb.cancel_menu(),
    )
    await call.answer()


@router.message(RevisionFlow.text, F.text)
async def got_revision(message: Message, state: FSMContext, bot: Bot, is_admin: bool):
    data = await state.get_data()
    order = await db.get_order(data["order_id"])
    await state.clear()
    if not order or order["status"] != Status.PREVIEW_SENT:
        await message.answer("⚠️ این سفارش در مرحله پیش‌نمایش نیست.", reply_markup=kb.main_menu(is_admin))
        return
    await db.set_status(order["id"], Status.REVISION)
    await message.answer(
        "📝 درخواست اصلاح ثبت شد. پس از اعمال تغییرات، پیش‌نمایش جدید برایتان ارسال می‌شود.",
        reply_markup=kb.main_menu(is_admin),
    )
    order = await db.get_order(order["id"])
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
    stars = max(1, min(5, callback_data.stars))
    await db.set_rating(order["id"], stars)
    await call.message.edit_text(f"🙏 ممنون از امتیاز شما: {'⭐️' * stars}\nامیدواریم باز هم میزبان شما باشیم 🤍")
    await call.answer()
    await notify_admins(bot, f"⭐️ مشتری سفارش #{order['id']} امتیاز {'⭐️' * stars} داد.")


# ---------- support ----------
async def support(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "💬 <b>پشتیبانی لینوریا</b>\n\nسوال، پیشنهاد یا مشکلی دارید؟ یکی از راه‌های زیر را انتخاب کنید:",
        reply_markup=kb.support_kb(),
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
    for admin_id in await all_admin_ids():
        try:
            await bot.send_message(admin_id, header)
            await message.copy_to(admin_id, reply_markup=kb.reply_user_kb(user.id))
        except Exception:  # noqa: BLE001
            pass
    await message.answer("✅ پیام شما برای پشتیبانی ارسال شد. به‌زودی پاسخ می‌دهیم 🤍", reply_markup=kb.main_menu(is_admin))
