"""Admin panel: payment review, preview/final delivery, messaging, settings, broadcast, admins."""
import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import keyboards as kb
from ..callbacks import Adm, MyOrder
from ..context import DEFAULT_SETTINGS, catalog, db, setting
from ..db import Status
from ..filters import IsAdmin
from ..states import AdminFlow
from ..utils import (
    esc,
    extract_file,
    fa,
    is_super,
    money,
    order_card_admin,
    send_files,
    to_en_digits,
    user_lock,
)

log = logging.getLogger(__name__)

router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def _safe_edit(message: Message, text: str, markup=None):
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await message.answer(text, reply_markup=markup)


async def _notify_user(bot: Bot, user_id: int, text: str, markup=None) -> bool:
    try:
        await bot.send_message(user_id, text, reply_markup=markup)
        return True
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        log.warning("cannot message user %s: %s", user_id, e)
        return False


# ---------- panel ----------
async def panel_text_markup(user_id: int):
    counts = {key: await db.count_by_status(sts) for key, (_, sts) in kb.ORDER_FILTERS.items()}
    open_ = await setting("orders_open") == "1"
    text = (
        "🛠 <b>پنل مدیریت لینوریا</b>\n\n"
        f"🔎 رسید در انتظار بررسی: <b>{fa(counts['review'])}</b>\n"
        f"🎨 در حال انجام: <b>{fa(counts['work'])}</b>\n"
        f"👀 منتظر نظر مشتری: <b>{fa(counts['preview'])}</b>"
    )
    return text, kb.admin_panel_kb(counts, is_super(user_id), open_)


@router.message(Command("admin"))
async def panel(message: Message, state: FSMContext):
    await state.clear()
    text, markup = await panel_text_markup(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(Adm.filter(F.action == "panel"))
async def panel_cb(call: CallbackQuery, state: FSMContext):
    await state.clear()
    text, markup = await panel_text_markup(call.from_user.id)
    await _safe_edit(call.message, text, markup)
    await call.answer()


@router.callback_query(Adm.filter(F.action == "abort"))
async def abort(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("لغو شد")


# ---------- order lists ----------
PAGE = 10


@router.callback_query(Adm.filter(F.action == "list"))
async def order_list(call: CallbackQuery, callback_data: Adm):
    key, _, page = callback_data.arg.partition(":")
    page = int(page or 0)
    title, statuses = kb.ORDER_FILTERS[key]
    orders = await db.orders_by_status(statuses, limit=PAGE + 1, offset=page * PAGE)
    has_next = len(orders) > PAGE
    orders = orders[:PAGE]
    text = f"{title}\n\n" + ("سفارشی در این بخش نیست ✨" if not orders else "روی سفارش بزنید:")
    await _safe_edit(call.message, text, kb.admin_list_kb(orders, key, page, has_next))
    await call.answer()


async def _send_order_card(target: Message, order_id: int, edit: bool = False):
    order = await db.get_order(order_id)
    if not order:
        await target.answer(f"❌ سفارش #{order_id} پیدا نشد.")
        return
    if edit:
        await _safe_edit(target, order_card_admin(order), kb.admin_order_kb(order))
    else:
        await target.answer(order_card_admin(order), reply_markup=kb.admin_order_kb(order))


@router.callback_query(Adm.filter(F.action == "view"))
async def view(call: CallbackQuery, callback_data: Adm):
    await _send_order_card(call.message, callback_data.order_id, edit=True)
    await call.answer()


@router.message(Command("order"))
async def order_cmd(message: Message, command: CommandObject):
    arg = to_en_digits((command.args or "").strip().lstrip("#"))
    if not arg.isdigit():
        await message.answer("استفاده: <code>/order 12</code>")
        return
    await _send_order_card(message, int(arg))


@router.callback_query(Adm.filter(F.action == "find"))
async def find(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlow.find_order)
    await call.message.answer("🔍 شماره سفارش را بفرستید:", reply_markup=kb.abort_kb())
    await call.answer()


@router.message(AdminFlow.find_order, F.text)
async def find_got(message: Message, state: FSMContext):
    arg = to_en_digits(message.text.strip().lstrip("#"))
    if not arg.isdigit():
        await message.answer("⚠️ فقط عدد بفرستید.")
        return
    await state.clear()
    await _send_order_card(message, int(arg))


@router.callback_query(Adm.filter(F.action == "files"))
async def show_files(call: CallbackQuery, callback_data: Adm, bot: Bot):
    files = await db.get_files(callback_data.order_id, callback_data.arg)
    if not files:
        await call.answer("فایلی وجود ندارد.", show_alert=True)
        return
    await call.answer()
    await send_files(bot, call.from_user.id, files, caption=f"📎 سفارش #{callback_data.order_id}")


@router.callback_query(Adm.filter(F.action == "receipt"))
async def show_receipt(call: CallbackQuery, callback_data: Adm, bot: Bot):
    files = await db.get_files(callback_data.order_id, "receipt")
    if not files:
        await call.answer("رسیدی ثبت نشده.", show_alert=True)
        return
    await call.answer()
    await send_files(bot, call.from_user.id, files[-1:], caption=f"🧾 آخرین رسید سفارش #{callback_data.order_id}")


# ---------- payment review ----------
@router.callback_query(Adm.filter(F.action == "approve"))
async def approve(call: CallbackQuery, callback_data: Adm, bot: Bot):
    order = await db.get_order(callback_data.order_id)
    if not order or order["status"] not in (Status.PAYMENT_REVIEW, Status.AWAITING_PAYMENT):
        await call.answer("این سفارش قبلاً بررسی شده است.", show_alert=True)
        await _send_order_card(call.message, callback_data.order_id, edit=True)
        return
    await db.set_status(order["id"], Status.IN_PROGRESS)
    delivery_time = await setting("delivery_time")
    await _notify_user(
        bot,
        order["user_id"],
        f"🎉 پرداخت سفارش <b>#{fa(order['id'])}</b> تایید شد!\n\n"
        f"🎨 هنرمند ما کار روی اثر شما را شروع کرد.\n⏱ زمان تقریبی آماده‌سازی: <b>{esc(delivery_time)}</b>\n\n"
        "به محض آماده شدن، پیش‌نمایش برایتان ارسال می‌شود 🤍",
    )
    await call.answer("✅ پرداخت تایید شد")
    await _send_order_card(call.message, order["id"], edit=True)


@router.callback_query(Adm.filter(F.action == "reject"))
async def reject(call: CallbackQuery, callback_data: Adm, state: FSMContext):
    order = await db.get_order(callback_data.order_id)
    if not order or order["status"] != Status.PAYMENT_REVIEW:
        await call.answer("این سفارش در وضعیت بررسی رسید نیست.", show_alert=True)
        return
    await state.set_state(AdminFlow.reject_reason)
    await state.update_data(order_id=order["id"])
    await call.message.answer(
        f"❌ رد رسید سفارش #{order['id']}\n\nیک دلیل انتخاب کنید یا دلیل دلخواه را تایپ کنید:",
        reply_markup=kb.reject_reasons_kb(order["id"]),
    )
    await call.answer()


async def _do_reject(bot: Bot, order_id: int, reason: str) -> bool:
    order = await db.get_order(order_id)
    if not order or order["status"] != Status.PAYMENT_REVIEW:
        return False
    await db.set_status(order_id, Status.AWAITING_PAYMENT, reject_reason=reason)
    b = InlineKeyboardBuilder()
    b.button(text="💳 ارسال مجدد رسید", callback_data=MyOrder(action="pay", order_id=order_id))
    await _notify_user(
        bot,
        order["user_id"],
        f"⚠️ رسید پرداخت سفارش <b>#{fa(order_id)}</b> تایید نشد.\n\n"
        f"📝 دلیل: {esc(reason)}\n\n"
        "لطفاً پس از بررسی، رسید صحیح را دوباره ارسال کنید یا با پشتیبانی در تماس باشید.",
        b.as_markup(),
    )
    return True


@router.callback_query(AdminFlow.reject_reason, Adm.filter(F.action == "reject_quick"))
async def reject_quick(call: CallbackQuery, callback_data: Adm, state: FSMContext, bot: Bot):
    reason = kb.REJECT_REASONS[int(callback_data.arg)]
    await state.clear()
    ok = await _do_reject(bot, callback_data.order_id, reason)
    await call.message.edit_text(f"❌ رسید سفارش #{callback_data.order_id} رد شد.\nدلیل: {esc(reason)}" if ok else "این سفارش قبلاً بررسی شده است.")
    await call.answer()


@router.message(AdminFlow.reject_reason, F.text)
async def reject_custom(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    ok = await _do_reject(bot, data["order_id"], message.text[:500])
    await message.answer(f"❌ رسید سفارش #{data['order_id']} رد شد." if ok else "این سفارش قبلاً بررسی شده است.")


# ---------- cancel ----------
@router.callback_query(Adm.filter(F.action == "cancel"))
async def cancel_ask(call: CallbackQuery, callback_data: Adm):
    await call.message.edit_reply_markup(reply_markup=kb.confirm_cancel_kb(callback_data.order_id))
    await call.answer("مطمئن هستید؟")


@router.callback_query(Adm.filter(F.action == "cancel_yes"))
async def cancel_yes(call: CallbackQuery, callback_data: Adm, bot: Bot):
    order = await db.get_order(callback_data.order_id)
    if order and order["status"] in Status.ACTIVE:
        await db.set_status(order["id"], Status.CANCELLED)
        await _notify_user(
            bot, order["user_id"],
            f"❌ سفارش <b>#{fa(order['id'])}</b> لغو شد.\nبرای اطلاعات بیشتر با پشتیبانی در تماس باشید.",
        )
    await call.answer("لغو شد")
    await _send_order_card(call.message, callback_data.order_id, edit=True)


# ---------- upload preview / final ----------
@router.callback_query(Adm.filter(F.action == "upload"))
async def upload_start(call: CallbackQuery, callback_data: Adm, state: FSMContext):
    order = await db.get_order(callback_data.order_id)
    if not order or order["status"] not in (Status.IN_PROGRESS, Status.REVISION, Status.PREVIEW_SENT, Status.PREVIEW_APPROVED):
        await call.answer("این سفارش در مرحله تحویل نیست.", show_alert=True)
        return
    kind = callback_data.arg
    await state.set_state(AdminFlow.upload)
    await state.update_data(order_id=order["id"], kind=kind, files=[], caption=None)
    what = "👀 <b>پیش‌نمایش</b>" if kind == "preview" else "📤 <b>فایل‌های نهایی</b>"
    tip = (
        "💡 پیشنهاد: پیش‌نمایش را با واترمارک یا کیفیت پایین‌تر بفرستید."
        if kind == "preview"
        else "💡 برای حفظ کیفیت، فایل اصلی را به صورت Document بفرستید (موکاپ‌ها را هم می‌توانید اضافه کنید)."
    )
    await call.message.answer(
        f"{what} سفارش #{order['id']} را بفرستید (عکس یا فایل، چند تا هم می‌شود).\n"
        f"اگر متنی بفرستید به عنوان توضیح برای مشتری ارسال می‌شود.\n\n{tip}",
        reply_markup=kb.upload_kb(0),
    )
    await call.answer()


@router.message(AdminFlow.upload, F.photo | F.document)
async def upload_file(message: Message, state: FSMContext):
    file_id, file_type = extract_file(message)
    async with user_lock(message.from_user.id):
        data = await state.get_data()
        files = data.get("files", [])
        files.append({"file_id": file_id, "file_type": file_type})
        await state.update_data(files=files)
        count = len(files)
        if message.caption:
            await state.update_data(caption=message.caption)
    await asyncio.sleep(1.2)
    data = await state.get_data()
    if len(data.get("files", [])) == count and await state.get_state() == AdminFlow.upload.state:
        await message.answer(f"📎 {fa(count)} فایل آماده ارسال است.", reply_markup=kb.upload_kb(count))


@router.message(AdminFlow.upload, F.text)
async def upload_caption(message: Message, state: FSMContext):
    await state.update_data(caption=message.text[:900])
    data = await state.get_data()
    await message.answer("📝 توضیح ثبت شد و همراه فایل‌ها ارسال می‌شود.", reply_markup=kb.upload_kb(len(data.get("files", []))))


@router.callback_query(AdminFlow.upload, Adm.filter(F.action == "upload_done"))
async def upload_done(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    order = await db.get_order(data["order_id"])
    files, kind, note = data.get("files", []), data["kind"], data.get("caption")
    if not order or not files:
        await call.answer("فایلی دریافت نشده.", show_alert=True)
        return
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)
    oid = order["id"]
    try:
        if kind == "preview":
            await send_files(bot, order["user_id"], files, caption=f"👀 پیش‌نمایش سفارش #{fa(oid)}")
            text = (
                f"✨ <b>پیش‌نمایش اثر شما آماده است!</b> (سفارش #{fa(oid)})\n\n"
                + (f"💬 {esc(note)}\n\n" if note else "")
                + "لطفاً بررسی کنید و نظرتان را بگویید 👇"
            )
            await bot.send_message(order["user_id"], text, reply_markup=kb.preview_kb(oid))
            new_status = Status.PREVIEW_SENT
        else:
            await send_files(bot, order["user_id"], files, caption=f"🎁 اثر نهایی سفارش #{fa(oid)}")
            text = (
                f"🎉 <b>اثر هنری شما تحویل داده شد!</b> (سفارش #{fa(oid)})\n\n"
                + (f"💬 {esc(note)}\n\n" if note else "")
                + "از اینکه لینوریا را انتخاب کردید ممنونیم 🤍\n"
                "فایل‌ها همیشه از «📦 سفارش‌های من» قابل دریافت دوباره هستند.\n\n"
                "⭐️ لطفاً به کار ما امتیاز دهید:"
            )
            await bot.send_message(order["user_id"], text, reply_markup=kb.rate_kb(oid))
            new_status = Status.DELIVERED
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        await call.message.answer(f"⚠️ ارسال به مشتری ناموفق بود: {esc(str(e))}")
        await call.answer()
        return

    for f in files:
        await db.add_file(oid, kind, f["file_id"], f["file_type"])
    await db.set_status(oid, new_status)
    await call.answer("✅ ارسال شد")
    await call.message.answer("✅ برای مشتری ارسال شد.")
    await _send_order_card(call.message, oid)


# ---------- message a user ----------
@router.callback_query(Adm.filter(F.action == "msg"))
async def msg_start(call: CallbackQuery, callback_data: Adm, state: FSMContext):
    order = await db.get_order(callback_data.order_id)
    if not order:
        await call.answer("سفارش پیدا نشد", show_alert=True)
        return
    await state.set_state(AdminFlow.message_user)
    await state.update_data(user_id=order["user_id"], order_id=order["id"])
    await call.message.answer(f"💬 پیام خود برای مشتری سفارش #{order['id']} را بفرستید:", reply_markup=kb.abort_kb())
    await call.answer()


@router.callback_query(Adm.filter(F.action == "reply"))
async def reply_start(call: CallbackQuery, callback_data: Adm, state: FSMContext):
    await state.set_state(AdminFlow.message_user)
    await state.update_data(user_id=int(callback_data.arg), order_id=None)
    await call.message.answer("↩️ پاسخ خود را بفرستید:", reply_markup=kb.abort_kb())
    await call.answer()


@router.message(AdminFlow.message_user)
async def msg_send(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    title = f"📩 <b>پیام از لینوریا</b> درباره سفارش #{fa(data['order_id'])}:" if data.get("order_id") else "📩 <b>پاسخ پشتیبانی لینوریا:</b>"
    try:
        await bot.send_message(data["user_id"], title)
        await message.copy_to(data["user_id"])
        await message.answer("✅ پیام ارسال شد.")
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        await message.answer(f"⚠️ ارسال ناموفق بود (احتمالاً کاربر ربات را بلاک کرده): {esc(str(e))}")


# ---------- block ----------
@router.callback_query(Adm.filter(F.action == "block"))
async def block_cb(call: CallbackQuery, callback_data: Adm):
    await db.set_blocked(int(callback_data.arg), True)
    await call.answer("🚫 کاربر مسدود شد. برای رفع: /unblock " + callback_data.arg, show_alert=True)


@router.message(Command("block", "unblock"))
async def block_cmd(message: Message, command: CommandObject):
    arg = to_en_digits((command.args or "").strip())
    if not arg.isdigit():
        await message.answer(f"استفاده: <code>/{command.command} 123456789</code>")
        return
    blocked = command.command == "block"
    await db.set_blocked(int(arg), blocked)
    await message.answer("🚫 کاربر مسدود شد." if blocked else "✅ کاربر آزاد شد.")


# ---------- stats ----------
@router.callback_query(Adm.filter(F.action == "stats"))
async def stats(call: CallbackQuery):
    s = await db.stats()
    rating = fa(s["avg_rating"]) if s["avg_rating"] else "—"
    text = (
        "📊 <b>آمار ربات</b>\n\n"
        f"👥 کاربران: <b>{fa(s['users'])}</b>\n"
        f"🧾 کل سفارش‌ها: <b>{fa(s['orders'])}</b>\n"
        f"🆕 سفارش‌های ۲۴ ساعت اخیر: <b>{fa(s['today'])}</b>\n"
        f"🎨 سفارش‌های فعال: <b>{fa(s['active'])}</b>\n"
        f"🔎 رسید در انتظار: <b>{fa(s['review'])}</b>\n"
        f"✅ تحویل شده: <b>{fa(s['delivered'])}</b>\n"
        f"💰 درآمد (پرداخت‌های تایید شده): <b>{money(s['revenue'])}</b>\n"
        f"⭐️ میانگین امتیاز: <b>{rating}</b>"
    )
    b = InlineKeyboardBuilder()
    b.button(text="🔙 پنل مدیریت", callback_data=Adm(action="panel"))
    await _safe_edit(call.message, text, b.as_markup())
    await call.answer()


# ---------- toggle accepting orders ----------
@router.callback_query(Adm.filter(F.action == "toggle_open"))
async def toggle_open(call: CallbackQuery):
    new = "0" if await setting("orders_open") == "1" else "1"
    await db.set_setting("orders_open", new)
    text, markup = await panel_text_markup(call.from_user.id)
    await _safe_edit(call.message, text, markup)
    await call.answer("پذیرش سفارش باز شد 🟢" if new == "1" else "پذیرش سفارش بسته شد 🔴")


# ---------- settings ----------
async def _settings_markup():
    values = {k: await setting(k) for k in kb.SETTING_LABELS}
    return kb.settings_kb(values)


@router.callback_query(Adm.filter(F.action == "settings"))
async def settings(call: CallbackQuery):
    await _safe_edit(call.message, "⚙️ <b>تنظیمات</b>\nبرای ویرایش روی هر مورد بزنید:", await _settings_markup())
    await call.answer()


@router.callback_query(Adm.filter(F.action == "set"))
async def set_start(call: CallbackQuery, callback_data: Adm, state: FSMContext):
    if callback_data.arg not in DEFAULT_SETTINGS:
        await call.answer()
        return
    await state.set_state(AdminFlow.setting_value)
    await state.update_data(key=callback_data.arg)
    current = await setting(callback_data.arg)
    await call.message.answer(
        f"{kb.SETTING_LABELS[callback_data.arg]}\nمقدار فعلی: <code>{esc(current)}</code>\n\nمقدار جدید را بفرستید:",
        reply_markup=kb.abort_kb(),
    )
    await call.answer()


@router.message(AdminFlow.setting_value, F.text)
async def set_value(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    await db.set_setting(data["key"], message.text.strip()[:200])
    await message.answer("✅ ذخیره شد.", reply_markup=await _settings_markup())


@router.callback_query(Adm.filter(F.action == "reload_catalog"))
async def reload_catalog(call: CallbackQuery):
    try:
        catalog.reload()
        await call.answer("✅ تعرفه‌ها از catalog.json بارگذاری شد", show_alert=True)
    except Exception as e:  # noqa: BLE001
        await call.answer(f"⚠️ خطا در catalog.json: {e}"[:190], show_alert=True)


# ---------- broadcast ----------
@router.callback_query(Adm.filter(F.action == "broadcast"))
async def broadcast_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlow.broadcast)
    await call.message.answer("📣 پیام همگانی را بفرستید (متن، عکس، ویدیو و ...):", reply_markup=kb.abort_kb())
    await call.answer()


@router.message(AdminFlow.broadcast)
async def broadcast_preview(message: Message, state: FSMContext):
    await state.update_data(chat_id=message.chat.id, message_id=message.message_id)
    await state.set_state(AdminFlow.broadcast_confirm)
    users = await db.all_user_ids()
    await message.answer(f"این پیام برای <b>{fa(len(users))}</b> کاربر ارسال شود؟", reply_markup=kb.broadcast_confirm_kb())


@router.callback_query(AdminFlow.broadcast_confirm, Adm.filter(F.action == "broadcast_go"))
async def broadcast_go(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    await call.message.edit_text("⏳ در حال ارسال...")
    await call.answer()
    asyncio.create_task(_broadcast(bot, call.message, data["chat_id"], data["message_id"]))


async def _broadcast(bot: Bot, status_msg: Message, chat_id: int, message_id: int):
    ok = fail = 0
    for uid in await db.all_user_ids():
        for _ in range(2):
            try:
                await bot.copy_message(uid, chat_id, message_id)
                ok += 1
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except Exception:  # noqa: BLE001
                fail += 1
                break
        await asyncio.sleep(0.05)  # stay under Telegram's ~30 msg/s limit
    await status_msg.edit_text(f"📣 ارسال تمام شد.\n✅ موفق: {fa(ok)}\n❌ ناموفق: {fa(fail)}")


# ---------- admins (super admin only) ----------
async def _admins_view():
    admins = await db.list_admins()
    lines = ["👥 <b>ادمین‌ها</b>", "", "👑 سوپر ادمین (از فایل .env)"]
    for a in admins:
        name = esc(a.get("full_name") or "—")
        lines.append(f"▫️ {name} — <code>{a['user_id']}</code>")
    return "\n".join(lines), kb.admins_kb(admins)


@router.callback_query(Adm.filter(F.action == "admins"))
async def admins(call: CallbackQuery):
    if not is_super(call.from_user.id):
        await call.answer("فقط سوپر ادمین", show_alert=True)
        return
    text, markup = await _admins_view()
    await _safe_edit(call.message, text, markup)
    await call.answer()


@router.callback_query(Adm.filter(F.action == "add_admin"))
async def add_admin_start(call: CallbackQuery, state: FSMContext):
    if not is_super(call.from_user.id):
        await call.answer("فقط سوپر ادمین", show_alert=True)
        return
    await state.set_state(AdminFlow.add_admin)
    await call.message.answer(
        "➕ آیدی عددی ادمین جدید را بفرستید، یا یک پیام از او را اینجا فوروارد کنید.\n"
        "<i>(ادمین جدید باید قبلاً ربات را استارت کرده باشد تا پیام‌ها به او برسد.)</i>",
        reply_markup=kb.abort_kb(),
    )
    await call.answer()


@router.message(AdminFlow.add_admin)
async def add_admin_got(message: Message, state: FSMContext):
    if not is_super(message.from_user.id):
        return
    uid = None
    if message.forward_origin and getattr(message.forward_origin, "sender_user", None):
        uid = message.forward_origin.sender_user.id
    elif message.text and to_en_digits(message.text.strip()).isdigit():
        uid = int(to_en_digits(message.text.strip()))
    if not uid:
        await message.answer("⚠️ آیدی عددی معتبر نیست (یا حریم خصوصی فوروارد کاربر بسته است).")
        return
    await state.clear()
    await db.add_admin(uid, message.from_user.id)
    text, markup = await _admins_view()
    await message.answer(f"✅ <code>{uid}</code> ادمین شد.\n\n{text}", reply_markup=markup)


@router.callback_query(Adm.filter(F.action == "del_admin"))
async def del_admin(call: CallbackQuery, callback_data: Adm):
    if not is_super(call.from_user.id):
        await call.answer("فقط سوپر ادمین", show_alert=True)
        return
    await db.remove_admin(int(callback_data.arg))
    text, markup = await _admins_view()
    await _safe_edit(call.message, text, markup)
    await call.answer("حذف شد")
