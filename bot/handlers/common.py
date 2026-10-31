from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from . import admin, order, user
from ..callbacks import Nav
from ..filters import IsAdmin
from ..services import register_referral
from ..context import setting
from ..texts import help_text, prices_text, welcome_text
from ..utils import safe_edit

router = Router(name="common")
fallback = Router(name="fallback")


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, bot: Bot, command: CommandObject, is_admin: bool, is_new_user: bool):
    await state.clear()
    if command.args:
        await register_referral(bot, message.from_user.id, command.args, is_new_user)
    await message.answer(
        await welcome_text(message.from_user.first_name),
        reply_markup=kb.main_menu(is_admin),
    )


@router.message(Command("cancel"))
@router.message(F.text == kb.BTN_CANCEL)
async def cancel(message: Message, state: FSMContext, is_admin: bool):
    await state.clear()
    await message.answer("❎ عملیات لغو شد. به منوی اصلی برگشتید.", reply_markup=kb.main_menu(is_admin))


@router.callback_query(Nav.filter(F.action == "cancel"))
async def cancel_cb(call: CallbackQuery, state: FSMContext, is_admin: bool):
    await state.clear()
    await safe_edit(call.message, "❎ ثبت سفارش لغو شد.")
    await call.message.answer("به منوی اصلی برگشتید 👇", reply_markup=kb.main_menu(is_admin))
    await call.answer()


@router.message(Command("help"))
@router.message(F.text == kb.BTN_HELP)
async def help_cmd(message: Message):
    await message.answer(await help_text(), reply_markup=kb.samples_kb(await setting("channel_url")))


@router.message(F.text == kb.BTN_PRICES)
async def prices(message: Message):
    await message.answer(await prices_text())


@router.message(F.text == kb.BTN_SAMPLES)
async def samples(message: Message):
    markup = kb.samples_kb(await setting("channel_url"))
    if markup:
        await message.answer("🖼 نمونه‌کارهای ما را در کانال لینوریا ببینید 👇", reply_markup=markup)
    else:
        await message.answer("🖼 به‌زودی نمونه‌کارها اینجا قرار می‌گیرد.")


# ---------- main-menu entry points ----------
# Registered here (first router) so menu buttons work from any step of any flow.
@router.message(F.text == kb.BTN_ORDER)
async def menu_order(message: Message, state: FSMContext, is_admin: bool):
    await order.start_order(message, state, is_admin)


@router.message(F.text == kb.BTN_MY_ORDERS)
async def menu_my_orders(message: Message, state: FSMContext):
    await user.my_orders(message, state)


@router.message(F.text == kb.BTN_INVITE)
async def menu_invite(message: Message, state: FSMContext, bot: Bot):
    await user.invite(message, state, bot)


@router.message(F.text == kb.BTN_SUPPORT)
async def menu_support(message: Message, state: FSMContext):
    await user.support(message, state)


@router.message(F.text == kb.BTN_ADMIN, IsAdmin())
async def menu_admin(message: Message, state: FSMContext):
    await admin.panel(message, state)


# ---------- fallbacks (registered last) ----------
@fallback.message(StateFilter(None))
async def unknown(message: Message, is_admin: bool):
    await message.answer("🤔 متوجه نشدم! لطفاً از دکمه‌های منو استفاده کنید 👇", reply_markup=kb.main_menu(is_admin))


@fallback.callback_query()
async def stale_callback(call: CallbackQuery):
    await call.answer("این دکمه منقضی شده است. لطفاً دوباره از منو شروع کنید.", show_alert=True)
