"""Customer order wizard: type → number of people → photos → description → confirm.
The price is set afterwards by an admin."""
import asyncio

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from ..callbacks import Nav, Pick
from ..context import catalog, db, referral_percent, setting
from ..states import OrderFlow
from ..texts import price_range
from ..utils import extract_file, fa, notify_admins, order_card_admin, order_lines, safe_edit, user_lock

router = Router(name="order")

def _single_style() -> bool:
    """With only one visible type of work, the 'choose type' step is skipped."""
    return len(catalog.styles) == 1


def _progress(step: str) -> str:
    steps = ["faces", "photos", "description"] if _single_style() else ["style", "faces", "photos", "description"]
    n, total = steps.index(step) + 1, len(steps)
    return f"<b>مرحله {fa(n)} از {fa(total)}</b>  " + "🟣" * n + "⚪️" * (total - n)


async def _show(target: Message, text: str, markup, edit: bool):
    if edit:
        await safe_edit(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup)


# ---------- step renderers ----------
async def ask_style(target: Message, edit: bool = False):
    lines = [f"{_progress('style')}\n", await setting("art_spec") + "\n", "🎨 <b>چه نوع اثری</b> می‌خواهید؟\n"]
    lines += [f"▫️ <b>{s.title}</b>\n     <i>{s.description}</i>" for s in catalog.styles if s.description]
    await _show(target, "\n".join(lines), kb.options_kb("style", catalog.styles, with_back=False), edit)


async def ask_faces(target: Message, edit: bool = False):
    text = f"{_progress('faces')}\n\n"
    if _single_style():
        text += await setting("art_spec") + "\n\n"
    text += "👤 <b>چند نفر</b> در نقاشی باشند؟"
    await _show(target, text, kb.options_kb("faces", catalog.faces, with_back=not _single_style()), edit)


def _photos_text() -> str:
    return (
        f"{_progress('photos')}\n\n"
        f"📸 حالا <b>عکس یا عکس‌های مورد نظر</b> را بفرستید (حداکثر {fa(catalog.max_reference_photos)} عکس).\n\n"
        "💡 <i>هر چه عکس واضح‌تر و با نور بهتری باشد، نتیجه زیباتر می‌شود. "
        "برای حفظ کیفیت، بهتر است عکس را به صورت «فایل» ارسال کنید.</i>"
    )


async def ask_photos(target: Message, count: int = 0, edit: bool = False):
    await _show(target, _photos_text(), kb.photos_kb(count), edit)


async def ask_description(target: Message, edit: bool = False):
    text = (
        f"{_progress('description')}\n\n"
        "📝 اگر توضیح خاصی دارید بنویسید.\n"
        "<i>مثلاً: «پس‌زمینه ساده باشد»، «فقط چهره سمت راست»، «یک متن کوتاه پایین کار نوشته شود» و ...</i>"
    )
    await _show(target, text, kb.skip_kb(), edit)


# ---------- entry ----------
async def start_order(message: Message, state: FSMContext, is_admin: bool):
    if await setting("orders_open") != "1" and not is_admin:
        await message.answer(
            "🙏 در حال حاضر به دلیل حجم بالای سفارش‌ها، ثبت سفارش موقتاً بسته است.\n"
            "به‌زودی دوباره باز می‌شود؛ اطلاع‌رسانی از طریق کانال انجام خواهد شد 🤍"
        )
        return
    await state.clear()
    await message.answer("✨ بزن بریم! فقط چند قدم تا اثر هنری اختصاصی شما فاصله است.", reply_markup=kb.cancel_menu())
    await _begin(message, state)


async def _begin(message: Message, state: FSMContext, edit: bool = False):
    if _single_style():
        await state.update_data(style=catalog.styles[0].id)
        await state.set_state(OrderFlow.faces)
        await ask_faces(message, edit=edit)
    else:
        await state.set_state(OrderFlow.style)
        await ask_style(message, edit=edit)


# ---------- picks ----------
@router.callback_query(OrderFlow.style, Pick.filter(F.field == "style"))
async def pick_style(call: CallbackQuery, callback_data: Pick, state: FSMContext):
    if not catalog.style(callback_data.value):
        await call.answer("این گزینه دیگر موجود نیست.", show_alert=True)
        await ask_style(call.message, edit=True)
        return
    await state.update_data(style=callback_data.value)
    await state.set_state(OrderFlow.faces)
    await ask_faces(call.message, edit=True)
    await call.answer()


@router.callback_query(OrderFlow.faces, Pick.filter(F.field == "faces"))
async def pick_faces(call: CallbackQuery, callback_data: Pick, state: FSMContext):
    if not catalog.face(callback_data.value):
        await call.answer("این گزینه دیگر موجود نیست.", show_alert=True)
        await ask_faces(call.message, edit=True)
        return
    await state.update_data(faces=callback_data.value)
    data = await state.get_data()
    await state.set_state(OrderFlow.photos)
    await ask_photos(call.message, count=len(data.get("photos", [])), edit=True)
    await call.answer()


# ---------- back ----------
@router.callback_query(OrderFlow.faces, Nav.filter(F.action == "back"))
async def back_to_style(call: CallbackQuery, state: FSMContext):
    await _begin(call.message, state, edit=True)
    await call.answer()


@router.callback_query(OrderFlow.photos, Nav.filter(F.action == "back"))
async def back_to_faces(call: CallbackQuery, state: FSMContext):
    await state.set_state(OrderFlow.faces)
    await ask_faces(call.message, edit=True)
    await call.answer()


@router.callback_query(OrderFlow.description, Nav.filter(F.action == "back"))
async def back_to_photos(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.set_state(OrderFlow.photos)
    await ask_photos(call.message, count=len(data.get("photos", [])), edit=True)
    await call.answer()


# ---------- photos ----------
@router.message(OrderFlow.photos, F.photo | F.document)
async def got_photo(message: Message, state: FSMContext):
    if message.document and not (message.document.mime_type or "").startswith("image/"):
        await message.answer("⚠️ لطفاً فقط عکس یا فایل تصویری (jpg / png / heic) ارسال کنید.")
        return
    file_id, file_type = extract_file(message)
    async with user_lock(message.from_user.id):
        data = await state.get_data()
        photos = data.get("photos", [])
        if len(photos) >= catalog.max_reference_photos:
            if not data.get("max_warned"):
                await state.update_data(max_warned=True)
                await message.answer(
                    f"⚠️ حداکثر {fa(catalog.max_reference_photos)} عکس قابل ارسال است؛ عکس‌های اضافه در نظر گرفته نشدند.",
                    reply_markup=kb.photos_kb(len(photos)),
                )
            return
        photos.append([file_id, file_type])
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
    data = await state.get_data()
    if not data.get("photos"):
        await call.answer("حداقل یک عکس بفرستید.", show_alert=True)
        return
    await state.set_state(OrderFlow.description)
    await ask_description(call.message, edit=True)
    await call.answer()


# ---------- description ----------
@router.message(OrderFlow.description, F.text)
async def got_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip()[:1000])
    await show_summary(message, state)


@router.callback_query(OrderFlow.description, Nav.filter(F.action == "skip_desc"))
async def skip_description(call: CallbackQuery, state: FSMContext):
    await state.update_data(description=None)
    await show_summary(call.message, state, edit=True)
    await call.answer()


@router.message(OrderFlow.description)
async def description_wrong(message: Message):
    await message.answer("📝 لطفاً توضیحات را به صورت متن بنویسید یا «توضیحی ندارم» را بزنید.", reply_markup=kb.skip_kb())


# ---------- summary / confirm ----------
async def show_summary(message: Message, state: FSMContext, edit: bool = False):
    data = await state.get_data()
    await state.set_state(OrderFlow.confirm)
    preview = {"style": data["style"], "faces": data["faces"], "description": data.get("description"), "price": None}
    text = "\n".join(
        ["📋 <b>خلاصه سفارش شما</b>", ""]
        + order_lines(preview)
        + [
            f"🖼 تعداد عکس: <b>{fa(len(data.get('photos', [])))}</b>",
            "",
            await setting("art_spec"),
            "",
            f"💡 قیمت بسته به حجم کار بین <b>{price_range()}</b> است و بعد از بررسی عکس‌ها برایتان ارسال می‌شود. "
            "تا قیمت را تایید و پرداخت نکنید، تعهدی ندارید.",
            "",
            "اگر همه‌چیز درست است، ثبت نهایی را بزنید 👇",
        ]
    )
    await _show(message, text, kb.confirm_kb(), edit)


@router.callback_query(OrderFlow.confirm, Nav.filter(F.action == "edit"))
async def edit_order(call: CallbackQuery, state: FSMContext):
    await state.set_data({})
    await _begin(call.message, state, edit=True)
    await call.answer("از اول شروع کنیم ✏️")


@router.callback_query(OrderFlow.confirm, Nav.filter(F.action == "confirm"))
async def confirm_order(call: CallbackQuery, state: FSMContext, bot: Bot, is_admin: bool):
    async with user_lock(call.from_user.id):  # guards against double-tap creating two orders
        if await state.get_state() != OrderFlow.confirm.state:
            await call.answer()
            return
        data = await state.get_data()
        await state.clear()
    if not data.get("style") or not data.get("faces") or not data.get("photos") \
            or not catalog.style(data["style"], include_hidden=True):
        await safe_edit(call.message, "⚠️ اطلاعات سفارش ناقص بود. لطفاً دوباره ثبت سفارش کنید.")
        await call.answer()
        return

    order_id = await db.create_order(call.from_user.id, data["style"], data["faces"], data.get("description"))
    for file_id, file_type in data["photos"]:
        await db.add_file(order_id, "reference", file_id, file_type)

    user = await db.get_user(call.from_user.id)
    credit_note = ""
    if user and user["referral_credits"] > 0:
        credit_note = f"\n\n🎁 شما کد تخفیف دعوت دارید؛ {fa(await referral_percent())}٪ تخفیف روی این سفارش اعمال می‌شود."

    await safe_edit(
        call.message,
        f"🎉 سفارش <b>#{fa(order_id)}</b> با موفقیت ثبت شد!\n\n"
        "🧮 عکس‌ها را بررسی می‌کنیم و به‌زودی <b>قیمت دقیق</b> و اطلاعات پرداخت را همین‌جا برایتان می‌فرستیم."
        + credit_note,
    )
    await call.message.answer("از «📦 سفارش‌های من» هم می‌توانید وضعیت را ببینید 👇", reply_markup=kb.main_menu(is_admin))
    await call.answer()

    order = await db.get_order(order_id)
    files = await db.get_files(order_id, "reference")
    await notify_admins(
        bot,
        "🆕 <b>سفارش جدید — لطفاً قیمت را تعیین کنید</b>\n\n" + order_card_admin(order),
        kb.admin_order_kb(order),
        files=files,
    )


@router.message(OrderFlow.style)
@router.message(OrderFlow.faces)
@router.message(OrderFlow.confirm)
async def use_buttons(message: Message):
    await message.answer("👆 لطفاً از دکمه‌های پیام بالا استفاده کنید (یا «❌ انصراف» برای لغو).")
