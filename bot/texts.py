from .config import config
from .context import catalog, setting
from .utils import esc, fa, money

WELCOME = (
    "سلام {name} عزیز 🤍\n"
    "به ربات سفارش <b>استودیو هنری لینوریا</b> خوش آمدید!\n\n"
    "ما اینجا لحظات، خاطرات و چهره‌های مورد علاقه شما را به اثر هنری تبدیل می‌کنیم:\n"
    "▫️ طراحی چهره اختصاصی (مناسب کادو، پروفایل، قاب و یادگاری)\n"
    "▫️ اجرای نقاشی‌های احساسی و کانسپت‌های دلخواه\n"
    "▫️ تحویل فایل با رزولوشن بالا همراه با موکاپ آماده چاپ\n\n"
    "برای شروع، از منوی پایین <b>«🎨 ثبت سفارش جدید»</b> را بزنید 👇"
)


async def help_text() -> str:
    delivery_time = esc(await setting("delivery_time"))
    return (
        "📌 <b>راهنمای جامع سفارش در لینوریا</b>\n\n"
        "<b>🛒 مراحل سفارش:</b>\n"
        "۱. «🎨 ثبت سفارش جدید» را بزنید.\n"
        "۲. سبک، سایز، تعداد چهره و نوع تحویل را انتخاب کنید.\n"
        "۳. عکس یا عکس‌های مورد نظرتان را بفرستید.\n"
        "۴. مبلغ را کارت‌به‌کارت کنید و <b>عکس رسید</b> را در ربات بفرستید.\n"
        "۵. بعد از تایید پرداخت، کار شروع می‌شود و ابتدا <b>پیش‌نمایش</b> برایتان ارسال می‌شود.\n"
        "۶. اگر راضی بودید تایید کنید؛ در غیر این صورت درخواست اصلاح بدهید.\n"
        "۷. <b>فایل نهایی</b> با کیفیت بالا مستقیماً در همین ربات تحویل داده می‌شود.\n\n"
        "<b>📸 کیفیت عکس:</b>\n"
        "هر چه عکس شما واضح‌تر و با نور بهتر باشد، جزئیات نقاشی دقیق‌تر و زیباتر می‌شود. "
        "برای بهترین کیفیت، عکس را به صورت <b>فایل (Document)</b> بفرستید.\n\n"
        "<b>📁 نحوه تحویل:</b>\n"
        "فایل با کیفیت، هم برای تصویر پروفایل و شبکه‌های اجتماعی مناسب است و هم قابلیت چاپ روی تخته‌شاسی و بوم را دارد.\n\n"
        f"<b>⏱ زمان آماده‌سازی:</b> {delivery_time}\n\n"
        "<b>📦 پیگیری سفارش:</b>\n"
        "از دکمه «📦 سفارش‌های من» وضعیت لحظه‌ای سفارش‌ها را ببینید. هر تغییری هم خودکار به شما اطلاع داده می‌شود.\n\n"
        f"❓ سوالی دارید؟ به @{config.support_username} پیام دهید."
    )


async def prices_text() -> str:
    lines = ["💰 <b>تعرفه‌های لینوریا</b>", "", "<b>🎨 سبک‌ها (پایه — سایز A5، یک نفر):</b>"]
    for s in catalog.styles:
        lines.append(f"▫️ {s.title}: <b>{money(s.price)}</b>")
        if s.description:
            lines.append(f"     <i>{esc(s.description)}</i>")
    lines += ["", "<b>📐 سایز:</b>"]
    for s in catalog.sizes:
        lines.append(f"▫️ {s.title}: ×{fa(s.multiplier)}")
    lines += ["", "<b>👤 تعداد چهره:</b>"]
    for s in catalog.faces:
        lines.append(f"▫️ {s.title}: ×{fa(s.multiplier)}")
    lines += ["", "<b>🚚 نوع تحویل:</b>"]
    for s in catalog.deliveries:
        extra = f"+{money(s.price)}" if s.price else "رایگان"
        lines.append(f"▫️ {s.title}: {extra}")
    lines += ["", "💡 قیمت دقیق، هنگام ثبت سفارش به‌صورت خودکار محاسبه و نمایش داده می‌شود."]
    return "\n".join(lines)


async def payment_text(order_id: int, price: int) -> str:
    card = esc(await setting("card_number"))
    holder = esc(await setting("card_holder"))
    bank = esc(await setting("bank_name"))
    return (
        f"🧾 سفارش <b>#{fa(order_id)}</b> ثبت شد!\n\n"
        f"💰 مبلغ قابل پرداخت: <b>{money(price)}</b>\n\n"
        "لطفاً مبلغ را به کارت زیر واریز کنید:\n"
        f"💳 <code>{card}</code>\n"
        f"👤 به نام: <b>{holder}</b>\n"
        f"🏦 {bank}\n\n"
        "<i>(روی شماره کارت بزنید تا کپی شود)</i>\n\n"
        "📸 بعد از واریز، <b>عکس رسید</b> را همین‌جا بفرستید."
    )
