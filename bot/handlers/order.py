"""Customer order wizard: style → size → faces → delivery → photos → description → (phone/address) → confirm."""
import asyncio

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from .. import keyboards as kb
from ..callbacks import Nav, Pick
from ..context import catalog, db, setting
from ..db import Status
from ..states import OrderFlow, ReceiptFlow
from ..texts import payment_text
from ..utils import esc, extract_file, fa, money, notify_admins, order_card_admin, order_lines, user_lock

router = Router(name="order")

TOTAL_STEPS = 6


def _progress(n: int) -> str:
    return f"<b>مرحله {fa(n)} از {fa(TOTAL_STEPS)}</b>  " + "🟣" * n + "⚪️" * (TOTAL_STEPS - n)


# ---------- step renderers ----------
async def ask_style(target: Message, edit: bool = False):
    text = f"{_progress(1)}\n\n🎨 <b>سبک اثر</b> را انتخاب کنید:"
    markup = kb.options_kb("style", catalog.styles, with_back=False, show_price=True)
    await (target.edit_text(text, reply_markup=markup) if edit else target.answer(text, reply_markup=markup))


async def ask_size(target: Message, edit: bool = False):
    text = f"{_progress(2)}\n\n📐 <b>سایز اثر</b> را انتخاب کنید:"
    markup = kb.options_kb("size", catalog.sizes)
    await (target.edit_text(text, reply_markup=markup) if edit else target.answer(text, reply_markup=markup))


async def ask_faces(target: Message, edit: bool = False):
    text = f"{_progress(3)}\n\n👤 <b>چند نفر</b> در نقاشی باشند؟"
    markup = kb.options_kb("faces", catalog.faces)
    await (target.edit_text(text, reply_markup=markup) if edit else target.answer(text, reply_markup=markup))


async def ask_delivery(target: Message, edit: bool = False):
    text = f"{_progress(4)}\n\n🚚 <b>نوع تحویل</b> را انتخاب کنید:"
    markup = kb.options_kb("delivery", catalog.deliveries, show_price=True)
    await (target.edit_text(text, reply_markup=markup) if edit else target.answer(text, reply_markup=markup))


async def ask_photos(target: Message, count: int = 0, edit: bool = False):
    text = (
        f"{_progress(5)}\n\n"
        f"📸 حالا <b>عکس یا عکس‌های مورد نظر</b> را بفرستید (حداکثر {fa(catalog.max_reference_photos)} عکس).\n\n"
        "💡 <i>نکته: هر چه عکس واضح‌تر و با نور بهتری باشد، نتیجه زیباتر می‌شود. "
        "برای حفظ کیفیت، بهتر است عکس را به صورت «فایل» ارسال کنید.</i>"
    )
    markup = kb.photos_kb(count)
    await (target.edit_text(text, reply_markup=markup) if edit else target.answer(text, reply_markup=markup))


async def ask_description(target: Message, edit: bool = False):
    text = (
        f"{_progress(6)}\n\n"
        "📝 اگر توضیح خاصی دارید بنویسید.\n"
        "<i>مثلاً: «پس‌زمینه ساده باشد»، «متن تولدت مبارک پایین کار نوشته شود»، «فقط چهره سمت راست» و ...</i>"
    )
    markup = kb.skip_kb()
    await (target.edit_text(text, reply_markup=markup) if edit else target.answer(text, reply_markup=markup))


STEP_RENDERERS: dict[State, callable] = {
    OrderFlow.style: ask_style,
    OrderFlow.size: ask_size,
    OrderFlow.faces: ask_faces,
    OrderFlow.delivery: ask_delivery,
}
PREVIOUS = {
    OrderFlow.size.state: OrderFlow.style,
    OrderFlow.faces.state: OrderFlow.size,
    OrderFlow.delivery.state: OrderFlow.faces,
    OrderFlow.photos.state: OrderFlow.delivery,
    OrderFlow.description.state: OrderFlow.photos,
}


# ---------- entry ----------
async def start_order(message: Message, state: FSMContext, is_admin: bool):
    if await setting("orders_open") != "1" and not is_admin:
        await message.answer(
            "🙏 در حال حاضر به دلیل حجم بالای سفارش‌ها، ثبت سفارش موقتاً بسته است.\n"
            "به‌زودی دوباره باز می‌شود؛ اطلاع‌رسانی از طریق کانال انجام خواهد شد 🤍"
        )
        return
    await state.clear()
    await state.set_state(OrderFlow.style)
    await message.answer("✨ بزن بریم! فقط چند قدم تا اثر هنری اختصاصی شما فاصله است.", reply_markup=kb.cancel_menu())
    await ask_style(message)


# ---------- picks ----------
@router.callback_query(OrderFlow.style, Pick.filter(F.field == "style"))
async def pick_style(call: CallbackQuery, callback_data: Pick, state: FSMContext):
    await state.update_data(style=callback_data.value)
    await state.set_state(OrderFlow.size)
    await ask_size(call.message, edit=True)
    await call.answer()


@router.callback_query(OrderFlow.size, Pick.filter(F.field == "size"))
async def pick_size(call: CallbackQuery, callback_data: Pick, state: FSMContext):
    await state.update_data(size=callback_data.value)
    await state.set_state(OrderFlow.faces)
    await ask_faces(call.message, edit=True)
    await call.answer()


@router.callback_query(OrderFlow.faces, Pick.filter(F.field == "faces"))
async def pick_faces(call: CallbackQuery, callback_data: Pick, state: FSMContext):
    await state.update_data(faces=callback_data.value)
    await state.set_state(OrderFlow.delivery)
    await ask_delivery(call.message, edit=True)
    await call.answer()


@router.callback_query(OrderFlow.delivery, Pick.filter(F.field == "delivery"))
async def pick_delivery(call: CallbackQuery, callback_data: Pick, state: FSMContext):
    await state.update_data(delivery=callback_data.value)
    data = await state.get_data()
    await state.set_state(OrderFlow.photos)
    await ask_photos(call.message, count=len(data.get("photos", [])), edit=True)
    await call.answer()


# ---------- back ----------
@router.callback_query(Nav.filter(F.action == "back"))
async def go_back(call: CallbackQuery, state: FSMContext):
    current = await state.get_state()
    prev = PREVIOUS.get(current)
    if prev is None:
        await call.answer()
        return
    await state.set_state(prev)
    if prev == OrderFlow.photos:
        data = await state.get_data()
        await ask_photos(call.message, count=len(data.get("photos", [])), edit=True)
    else:
        await STEP_RENDERERS[prev](call.message, edit=True)
    await call.answer()


# ---------- photos ----------
@router.message(OrderFlow.photos, F.photo | F.document)
async def got_photo(message: Message, state: FSMContext):
    file = extract_file(message)
    if message.document and not (message.document.mime_type or "").startswith("image/"):
        await message.answer("⚠️ لطفاً فقط فایل تصویری (عکس) ارسال کنید.")
        return
    async with user_lock(message.from_user.id):
        data = await state.get_data()
        photos = data.get("photos", [])
        if len(photos) >= catalog.max_reference_photos:
            await message.answer(f"⚠️ حداکثر {fa(catalog.max_reference_photos)} عکس قابل ارسال است.")
            return
        photos.append(list(file))
        await state.update_data(photos=photos)
        count = len(photos)

    # albums arrive as several updates — wait a moment and answer only once
    await asyncio.sleep(1.2)
    data = await state.get_data()
    if len(data.get("photos", [])) != count or await state.get_state() != OrderFlow.photos.state:
        return
    await message.answer(
        f"✅ {fa(count)} عکس دریافت شد. اگر عکس دیگری دارید بفرستید، وگرنه «ادامه» را بزنید.",
        reply_markup=kb.photos_kb(count),
    )


@router.message(OrderFlow.photos)
async def photos_wrong(message: Message, state: FSMContext):
    data = await state.get_data()
    await message.answer("📸 لطفاً عکس بفرستید.", reply_markup=kb.photos_kb(len(data.get("photos", []))))


@router.callback_query(OrderFlow.photos, Nav.filter(F.action == "photos_done"))
async def photos_done(call: CallbackQuery, state: FSMContext):
    await state.set_state(OrderFlow.description)
    await ask_description(call.message, edit=True)
    await call.answer()


# ---------- description ----------
async def _after_description(message: Message, state: FSMContext):
    data = await state.get_data()
    delivery = catalog.delivery(data["delivery"])
    if delivery and delivery.needs_address:
        await state.set_state(OrderFlow.phone)
        await message.answer(
            "📞 برای ارسال پستی، <b>شماره تماس</b> خود را بفرستید (یا دکمه زیر را بزنید):",
            reply_markup=kb.phone_menu(),
        )
    else:
        await show_summary(message, state)


@router.message(OrderFlow.description, F.text)
async def got_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text[:1000])
    await _after_description(message, state)


@router.callback_query(OrderFlow.description, Nav.filter(F.action == "skip_desc"))
async def skip_description(call: CallbackQuery, state: FSMContext):
    await state.update_data(description=None)
    await call.message.edit_reply_markup(reply_markup=None)
    await _after_description(call.message, state)
    await call.answer()


@router.message(OrderFlow.description)
async def description_wrong(message: Message):
    await message.answer("📝 لطفاً توضیحات را به صورت متن بنویسید یا «توضیحی ندارم» را بزنید.", reply_markup=kb.skip_kb())


# ---------- phone / address ----------
@router.message(OrderFlow.phone, F.contact)
@router.message(OrderFlow.phone, F.text.regexp(r"^[+0-9۰-۹\s-]{8,20}$"))
async def got_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text.strip()
    await state.update_data(phone=phone)
    await db.set_user_phone(message.from_user.id, phone)
    await state.set_state(OrderFlow.address)
    await message.answer(
        "🏠 حالا <b>آدرس کامل پستی</b> همراه با کد پستی و نام گیرنده را بنویسید:",
        reply_markup=kb.cancel_menu(),
    )


@router.message(OrderFlow.phone)
async def phone_wrong(message: Message):
    await message.answer("⚠️ شماره معتبر نیست. لطفاً دکمه «📱 ارسال شماره من» را بزنید یا شماره را بنویسید.")


@router.message(OrderFlow.address, F.text.len() >= 10)
async def got_address(message: Message, state: FSMContext):
    await state.update_data(address=message.text[:1000])
    await show_summary(message, state)


@router.message(OrderFlow.address)
async def address_wrong(message: Message):
    await message.answer("⚠️ لطفاً آدرس کامل را به صورت متن بنویسید.")


# ---------- summary / confirm ----------
async def show_summary(message: Message, state: FSMContext):
    data = await state.get_data()
    price = catalog.price(data["style"], data["size"], data["faces"], data["delivery"])
    await state.update_data(price=price)
    await state.set_state(OrderFlow.confirm)
    preview = {**data, "price": price}
    text = "\n".join(
        ["📋 <b>خلاصه سفارش شما</b>", ""]
        + order_lines(preview)
        + [f"🖼 تعداد عکس: <b>{fa(len(data.get('photos', [])))}</b>", "", "اگر همه‌چیز درست است، تایید کنید 👇"]
    )
    await message.answer("✅ اطلاعات کامل شد.", reply_markup=ReplyKeyboardRemove())
    await message.answer(text, reply_markup=kb.confirm_kb())


@router.callback_query(OrderFlow.confirm, Nav.filter(F.action == "edit"))
async def edit_order(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(OrderFlow.style)
    await ask_style(call.message, edit=True)
    await call.answer("از اول شروع کنیم ✏️")


@router.callback_query(OrderFlow.confirm, Nav.filter(F.action == "confirm"))
async def confirm_order(call: CallbackQuery, state: FSMContext, bot: Bot, is_admin: bool):
    data = await state.get_data()
    try:
        price = catalog.price(data["style"], data["size"], data["faces"], data["delivery"])
    except (KeyError, ValueError):
        await state.clear()
        await call.message.edit_text("⚠️ اطلاعات سفارش ناقص بود. لطفاً دوباره ثبت سفارش کنید.")
        return
    order_id = await db.create_order(call.from_user.id, data, price)
    for file_id, file_type in data.get("photos", []):
        await db.add_file(order_id, "reference", file_id, file_type)

    await state.clear()
    await state.set_state(ReceiptFlow.waiting)
    await state.update_data(order_id=order_id)

    await call.message.edit_text(f"🎉 سفارش <b>#{fa(order_id)}</b> با موفقیت ثبت شد.")
    await call.message.answer(await payment_text(order_id, price), reply_markup=kb.pay_kb(order_id))
    await call.message.answer(
        "منتظر عکس رسید شما هستم 📸",
        reply_markup=kb.main_menu(is_admin),
    )
    await call.answer()

    order = await db.get_order(order_id)
    await notify_admins(bot, "🆕 <b>سفارش جدید (در انتظار پرداخت)</b>\n\n" + order_card_admin(order), kb.admin_order_kb(order))


@router.message(OrderFlow.style)
@router.message(OrderFlow.size)
@router.message(OrderFlow.faces)
@router.message(OrderFlow.delivery)
@router.message(OrderFlow.confirm)
async def use_buttons(message: Message):
    await message.answer("👆 لطفاً از دکمه‌های پیام بالا استفاده کنید (یا «❌ انصراف» برای لغو).")
