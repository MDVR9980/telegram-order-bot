"""Admin: promo codes and the editable service catalog (types, people options, prices)."""
import re
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import keyboards as kb
from ..callbacks import Adm
from ..context import catalog, db, save_catalog
from ..filters import IsAdmin
from ..services import promo_label
from ..states import AdminFlow
from ..utils import esc, fa, fmt_time, money, parse_price, safe_edit, to_en_digits

router = Router(name="admin_manage")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

KIND_TITLES = {"style": "🎨 نوع آثار", "faces": "👤 گزینه‌های تعداد افراد"}


def _back(action: str, text: str = "🔙 بازگشت", arg: str = "") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=text, callback_data=Adm(action=action, arg=arg))
    return b.as_markup()


# =====================================================================
# promo codes
# =====================================================================
def _promo_status(p: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if not p["active"]:
        return "⏸ غیرفعال"
    if p["expires_at"] and p["expires_at"] <= now:
        return "⌛️ منقضی"
    if p["max_uses"] is not None and p["used"] >= p["max_uses"]:
        return "🈵 تکمیل"
    return "🟢 فعال"


def _promo_text(p: dict) -> str:
    uses = f"{fa(p['used'])} از {fa(p['max_uses'])}" if p["max_uses"] is not None else f"{fa(p['used'])} (نامحدود)"
    expires = fmt_time(p["expires_at"]) if p["expires_at"] else "بدون انقضا"
    return (
        f"🎟 <b>کد تخفیف</b> <code>{esc(p['code'])}</code>\n\n"
        f"وضعیت: {_promo_status(p)}\n"
        f"💸 مقدار: <b>{promo_label(p)}</b>\n"
        f"👥 استفاده: {uses}\n"
        f"⏳ انقضا: {expires}\n\n"
        "<i>هر مشتری فقط یک بار می‌تواند از هر کد استفاده کند. مشتری کد را در مرحله پرداخت وارد می‌کند.</i>"
    )


@router.callback_query(Adm.filter(F.action == "promos"))
async def promos(call: CallbackQuery, state: FSMContext):
    await state.clear()
    items = await db.list_promos()
    b = InlineKeyboardBuilder()
    for p in items[:40]:
        b.button(text=f"{p['code']} • {promo_label(p)} • {_promo_status(p)}", callback_data=Adm(action="promo_view", arg=p["code"]))
    b.button(text="➕ ساخت کد تخفیف جدید", callback_data=Adm(action="promo_new"))
    b.button(text="🔙 پنل مدیریت", callback_data=Adm(action="panel"))
    b.adjust(1)
    text = "🎟 <b>کدهای تخفیف</b>\n\n" + ("هنوز کدی نساخته‌اید." if not items else "برای مدیریت روی هر کد بزنید:")
    await safe_edit(call.message, text, b.as_markup())
    await call.answer()


async def _promo_view(target: Message, code: str, edit: bool = True):
    p = await db.get_promo(code)
    if not p:
        await target.answer("کد پیدا نشد.")
        return
    b = InlineKeyboardBuilder()
    b.button(text="⏸ غیرفعال کردن" if p["active"] else "▶️ فعال کردن", callback_data=Adm(action="promo_toggle", arg=p["code"]))
    b.button(text="🗑 حذف", callback_data=Adm(action="promo_del", arg=p["code"]))
    b.button(text="🔙 لیست کدها", callback_data=Adm(action="promos"))
    b.adjust(2, 1)
    if edit:
        await safe_edit(target, _promo_text(p), b.as_markup())
    else:
        await target.answer(_promo_text(p), reply_markup=b.as_markup())


@router.callback_query(Adm.filter(F.action == "promo_view"))
async def promo_view(call: CallbackQuery, callback_data: Adm):
    await _promo_view(call.message, callback_data.arg)
    await call.answer()


@router.callback_query(Adm.filter(F.action == "promo_toggle"))
async def promo_toggle(call: CallbackQuery, callback_data: Adm):
    await db.toggle_promo(callback_data.arg)
    await _promo_view(call.message, callback_data.arg)
    await call.answer("انجام شد")


@router.callback_query(Adm.filter(F.action == "promo_del"))
async def promo_del(call: CallbackQuery, callback_data: Adm):
    b = InlineKeyboardBuilder()
    b.button(text="✅ بله، حذف شود", callback_data=Adm(action="promo_del_yes", arg=callback_data.arg))
    b.button(text="🔙 خیر", callback_data=Adm(action="promo_view", arg=callback_data.arg))
    await safe_edit(call.message, f"❓ کد <code>{esc(callback_data.arg)}</code> حذف شود؟\n"
                    "<i>(سفارش‌هایی که قبلاً با این کد ثبت شده‌اند تغییری نمی‌کنند.)</i>", b.as_markup())
    await call.answer()


@router.callback_query(Adm.filter(F.action == "promo_del_yes"))
async def promo_del_yes(call: CallbackQuery, callback_data: Adm, state: FSMContext):
    await db.delete_promo(callback_data.arg)
    await call.answer("حذف شد")
    await promos(call, state)


# ----- new promo wizard -----
@router.callback_query(Adm.filter(F.action == "promo_new"))
async def promo_new(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlow.promo_code)
    await call.message.answer(
        "➕ <b>ساخت کد تخفیف — مرحله ۱ از ۴</b>\n\n"
        "متن کد را بفرستید (حروف انگلیسی، عدد، - یا _ ، بین ۳ تا ۲۰ کاراکتر).\n"
        "مثال: <code>YALDA1404</code> یا <code>NOROOZ</code>",
        reply_markup=kb.abort_kb(),
    )
    await call.answer()


@router.message(AdminFlow.promo_code, F.text)
async def promo_code_got(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    if not re.fullmatch(r"[A-Z0-9_-]{3,20}", code):
        await message.answer("⚠️ کد نامعتبر است. فقط حروف انگلیسی، عدد، - و _ (۳ تا ۲۰ کاراکتر).")
        return
    if await db.get_promo(code):
        await message.answer("⚠️ این کد از قبل وجود دارد. کد دیگری بفرستید.")
        return
    await state.update_data(code=code)
    await state.set_state(AdminFlow.promo_value)
    await message.answer(
        "<b>مرحله ۲ از ۴ — مقدار تخفیف</b>\n\n"
        "▫️ برای تخفیف درصدی، عدد را با ٪ بفرستید: <code>15%</code>\n"
        "▫️ برای مبلغ ثابت، مبلغ را به تومان بفرستید: <code>50000</code> (یا <code>50</code> یعنی ۵۰ هزار)",
        reply_markup=kb.abort_kb(),
    )


@router.message(AdminFlow.promo_value, F.text)
async def promo_value_got(message: Message, state: FSMContext):
    text = to_en_digits(message.text.strip())
    if "%" in text or "٪" in text:
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits or not 1 <= int(digits) <= 90:
            await message.answer("⚠️ درصد باید بین ۱ تا ۹۰ باشد.")
            return
        kind, value = "percent", int(digits)
    else:
        value = parse_price(text)
        if not value:
            await message.answer("⚠️ مقدار نامعتبر است. مثال: <code>15%</code> یا <code>50000</code>")
            return
        kind = "amount"
    await state.update_data(kind=kind, value=value)
    await state.set_state(AdminFlow.promo_uses)
    b = InlineKeyboardBuilder()
    b.button(text="♾ نامحدود", callback_data=Adm(action="promo_unlimited"))
    b.button(text="✖️ انصراف", callback_data=Adm(action="abort"))
    b.adjust(1)
    await message.answer(
        "<b>مرحله ۳ از ۴ — تعداد دفعات استفاده</b>\n\nحداکثر چند نفر بتوانند از این کد استفاده کنند؟ (یک عدد بفرستید)",
        reply_markup=b.as_markup(),
    )


async def _ask_days(message: Message, state: FSMContext):
    await state.set_state(AdminFlow.promo_days)
    b = InlineKeyboardBuilder()
    b.button(text="♾ بدون انقضا", callback_data=Adm(action="promo_noexpiry"))
    b.button(text="✖️ انصراف", callback_data=Adm(action="abort"))
    b.adjust(1)
    await message.answer(
        "<b>مرحله ۴ از ۴ — مدت اعتبار</b>\n\nکد چند روز معتبر باشد؟ (مثلاً <code>7</code>)",
        reply_markup=b.as_markup(),
    )


@router.message(AdminFlow.promo_uses, F.text)
async def promo_uses_got(message: Message, state: FSMContext):
    text = to_en_digits(message.text.strip())
    if not text.isdigit() or int(text) < 1:
        await message.answer("⚠️ یک عدد بزرگ‌تر از صفر بفرستید یا «نامحدود» را بزنید.")
        return
    await state.update_data(max_uses=int(text))
    await _ask_days(message, state)


@router.callback_query(AdminFlow.promo_uses, Adm.filter(F.action == "promo_unlimited"))
async def promo_unlimited(call: CallbackQuery, state: FSMContext):
    await state.update_data(max_uses=None)
    await call.message.edit_reply_markup(reply_markup=None)
    await _ask_days(call.message, state)
    await call.answer()


async def _create_promo(target: Message, state: FSMContext, days: int | None):
    data = await state.get_data()
    await state.clear()
    expires = None
    if days:
        expires = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    if not await db.create_promo(data["code"], data["kind"], data["value"], data.get("max_uses"), expires):
        await target.answer("⚠️ این کد از قبل وجود دارد.")
        return
    await target.answer("✅ کد تخفیف ساخته شد! می‌توانید آن را در کانال اعلام کنید 👇")
    await _promo_view(target, data["code"], edit=False)


@router.message(AdminFlow.promo_days, F.text)
async def promo_days_got(message: Message, state: FSMContext):
    text = to_en_digits(message.text.strip())
    if not text.isdigit() or not 1 <= int(text) <= 3650:
        await message.answer("⚠️ تعداد روز را به عدد بفرستید (مثلاً 7) یا «بدون انقضا» را بزنید.")
        return
    await _create_promo(message, state, int(text))


@router.callback_query(AdminFlow.promo_days, Adm.filter(F.action == "promo_noexpiry"))
async def promo_noexpiry(call: CallbackQuery, state: FSMContext):
    await call.message.edit_reply_markup(reply_markup=None)
    await _create_promo(call.message, state, None)
    await call.answer()


# =====================================================================
# catalog: prices & options
# =====================================================================
def _catalog_text() -> str:
    quick = "، ".join(fa(f"{p // 1000:,}") for p in catalog.quick_prices) or "—"
    styles = "\n".join(f"   ▫️ {esc(o.title)}" for o in catalog.styles)
    faces = "\n".join(f"   ▫️ {esc(o.title)}" for o in catalog.faces)
    return (
        "🎨 <b>خدمات و قیمت‌ها</b>\n\n"
        f"💰 بازه قیمت (نمایش به مشتری): <b>{money(catalog.price_min)} تا {money(catalog.price_max)}</b>\n"
        f"⚡️ دکمه‌های قیمت سریع (هزار تومان): {quick}\n"
        f"🖼 حداکثر عکس در هر سفارش: {fa(catalog.max_reference_photos)}\n\n"
        f"<b>نوع آثار:</b>\n{styles}\n\n<b>تعداد افراد:</b>\n{faces}"
    )


def _catalog_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💰 تغییر بازه قیمت", callback_data=Adm(action="cat_set", arg="price_range"))
    b.button(text="⚡️ دکمه‌های قیمت سریع", callback_data=Adm(action="cat_set", arg="quick_prices"))
    b.button(text="🖼 حداکثر تعداد عکس", callback_data=Adm(action="cat_set", arg="max_photos"))
    b.button(text="🎨 مدیریت نوع آثار", callback_data=Adm(action="opts", arg="style"))
    b.button(text="👤 مدیریت تعداد افراد", callback_data=Adm(action="opts", arg="faces"))
    b.button(text="🔙 پنل مدیریت", callback_data=Adm(action="panel"))
    b.adjust(1)
    return b.as_markup()


@router.callback_query(Adm.filter(F.action == "catalog"))
async def catalog_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(call.message, _catalog_text(), _catalog_kb())
    await call.answer()


CAT_PROMPTS = {
    "price_range": "💰 بازه قیمت را به صورت «کمترین - بیشترین» به هزار تومان بفرستید.\nمثال: <code>250-500</code>",
    "quick_prices": "⚡️ مبلغ دکمه‌های قیمت سریع را به هزار تومان و با کاما جدا کنید.\nمثال: <code>250, 300, 350, 400, 450, 500</code>",
    "max_photos": "🖼 حداکثر تعداد عکسی که مشتری می‌تواند بفرستد (۱ تا ۱۰):",
}


@router.callback_query(Adm.filter(F.action == "cat_set"))
async def cat_set(call: CallbackQuery, callback_data: Adm, state: FSMContext):
    if callback_data.arg not in CAT_PROMPTS:
        await call.answer()
        return
    await state.set_state(AdminFlow.catalog_value)
    await state.update_data(field=callback_data.arg)
    await call.message.answer(CAT_PROMPTS[callback_data.arg], reply_markup=kb.abort_kb())
    await call.answer()


def _numbers(text: str) -> list[int]:
    return [int(n) for n in re.findall(r"\d+", to_en_digits(text))]


@router.message(AdminFlow.catalog_value, F.text)
async def cat_value(message: Message, state: FSMContext):
    field = (await state.get_data())["field"]
    nums = _numbers(message.text)
    to_toman = lambda n: n * 1000 if n < 10_000 else n  # noqa: E731
    if field == "price_range":
        if len(nums) != 2 or not 0 < nums[0] <= nums[1]:
            await message.answer("⚠️ فرمت درست: <code>250-500</code>")
            return
        catalog.price_min, catalog.price_max = to_toman(nums[0]), to_toman(nums[1])
    elif field == "quick_prices":
        if not nums or len(nums) > 12 or any(n <= 0 for n in nums):
            await message.answer("⚠️ بین ۱ تا ۱۲ مبلغ با کاما بفرستید. مثال: <code>250, 300, 350</code>")
            return
        catalog.quick_prices = sorted({to_toman(n) for n in nums})
    elif field == "max_photos":
        if len(nums) != 1 or not 1 <= nums[0] <= 10:
            await message.answer("⚠️ یک عدد بین ۱ تا ۱۰ بفرستید.")
            return
        catalog.max_reference_photos = nums[0]
    await save_catalog()
    await state.clear()
    await message.answer("✅ ذخیره شد.\n\n" + _catalog_text(), reply_markup=_catalog_kb())


# ----- options (types of work / number of people) -----
def _options_kb(kind: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for o in catalog.all_options(kind):
        b.button(text=("🙈 " if o.hidden else "👁 ") + o.title, callback_data=Adm(action="opt", arg=f"{kind}~{o.id}"))
    b.button(text="➕ افزودن گزینه جدید", callback_data=Adm(action="opt_add", arg=kind))
    b.button(text="🔙 خدمات و قیمت‌ها", callback_data=Adm(action="catalog"))
    b.adjust(1)
    return b.as_markup()


@router.callback_query(Adm.filter(F.action == "opts"))
async def opts(call: CallbackQuery, callback_data: Adm, state: FSMContext):
    await state.clear()
    kind = callback_data.arg
    if kind not in KIND_TITLES:
        await call.answer()
        return
    await safe_edit(
        call.message,
        f"{KIND_TITLES[kind]}\n\n👁 = نمایش برای مشتری   🙈 = مخفی\nبرای ویرایش روی هر گزینه بزنید:",
        _options_kb(kind),
    )
    await call.answer()


def _parse_option(text: str) -> tuple[str, str] | None:
    title, _, desc = text.partition("|")
    title, desc = title.strip()[:60], desc.strip()[:150]
    return (title, desc) if title else None


@router.callback_query(Adm.filter(F.action == "opt"))
async def opt_view(call: CallbackQuery, callback_data: Adm):
    kind, _, oid = callback_data.arg.partition("~")
    if kind not in KIND_TITLES:
        await call.answer()
        return
    o = next((x for x in catalog.all_options(kind) if x.id == oid), None)
    if not o:
        await call.answer("گزینه پیدا نشد", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    b.button(text="✏️ ویرایش متن", callback_data=Adm(action="opt_edit", arg=callback_data.arg))
    b.button(text="👁 نمایش برای مشتری" if o.hidden else "🙈 مخفی کردن", callback_data=Adm(action="opt_toggle", arg=callback_data.arg))
    b.button(text="🔙 بازگشت", callback_data=Adm(action="opts", arg=kind))
    b.adjust(2, 1)
    text = (
        f"<b>{esc(o.title)}</b>\n{esc(o.description)}\n\n"
        f"وضعیت: {'🙈 مخفی' if o.hidden else '👁 قابل انتخاب برای مشتری'}\n\n"
        "<i>به جای حذف، گزینه را مخفی کنید تا سفارش‌های قبلی درست نمایش داده شوند.</i>"
    )
    await safe_edit(call.message, text, b.as_markup())
    await call.answer()


@router.callback_query(Adm.filter(F.action == "opt_toggle"))
async def opt_toggle(call: CallbackQuery, callback_data: Adm):
    kind, _, oid = callback_data.arg.partition("~")
    if kind not in KIND_TITLES:
        await call.answer()
        return
    try:
        catalog.toggle_option(kind, oid)
    except ValueError:
        await call.answer("حداقل یک گزینه باید برای مشتری قابل انتخاب بماند.", show_alert=True)
        return
    await save_catalog()
    await opt_view(call, callback_data)


@router.callback_query(Adm.filter(F.action == "opt_add"))
async def opt_add(call: CallbackQuery, callback_data: Adm, state: FSMContext):
    if callback_data.arg not in KIND_TITLES:
        await call.answer()
        return
    await state.set_state(AdminFlow.option_add)
    await state.update_data(kind=callback_data.arg)
    await call.message.answer(
        "➕ عنوان گزینه جدید را بفرستید. اگر توضیح هم می‌خواهید، با | جدا کنید:\n"
        "<code>🐾 طراحی حیوان خانگی | پرتره حیوان شما با مداد سیاه</code>",
        reply_markup=kb.abort_kb(),
    )
    await call.answer()


@router.message(AdminFlow.option_add, F.text)
async def opt_add_got(message: Message, state: FSMContext):
    parsed = _parse_option(message.text)
    if not parsed:
        await message.answer("⚠️ عنوان نمی‌تواند خالی باشد.")
        return
    kind = (await state.get_data())["kind"]
    catalog.add_option(kind, *parsed)
    await save_catalog()
    await state.clear()
    await message.answer(f"✅ اضافه شد.\n\n{KIND_TITLES[kind]}:", reply_markup=_options_kb(kind))


@router.callback_query(Adm.filter(F.action == "opt_edit"))
async def opt_edit(call: CallbackQuery, callback_data: Adm, state: FSMContext):
    kind, _, oid = callback_data.arg.partition("~")
    await state.set_state(AdminFlow.option_edit)
    await state.update_data(kind=kind, option_id=oid)
    await call.message.answer(
        "✏️ متن جدید را بفرستید (عنوان | توضیح):", reply_markup=kb.abort_kb()
    )
    await call.answer()


@router.message(AdminFlow.option_edit, F.text)
async def opt_edit_got(message: Message, state: FSMContext):
    parsed = _parse_option(message.text)
    if not parsed:
        await message.answer("⚠️ عنوان نمی‌تواند خالی باشد.")
        return
    data = await state.get_data()
    catalog.edit_option(data["kind"], data["option_id"], *parsed)
    await save_catalog()
    await state.clear()
    await message.answer("✅ ویرایش شد.", reply_markup=_options_kb(data["kind"]))
