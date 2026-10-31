from .context import catalog, referral_percent, setting, support_username
from .utils import esc, fa, money, price_lines

DEFAULT_WELCOME = (
    "سلام {name} عزیز 🤍\n"
    "به ربات سفارش <b>استودیو هنری لینوریا</b> خوش آمدید!\n\n"
    "ما اینجا لحظات، خاطرات و چهره‌های مورد علاقه شما را به اثر هنری تبدیل می‌کنیم:\n"
    "▫️ طراحی چهره اختصاصی (مناسب کادو، پروفایل، قاب و یادگاری)\n"
    "▫️ اجرای نقاشی‌های احساسی و کانسپت‌های دلخواه\n"
    "▫️ تحویل فایل با رزولوشن فوق‌العاده بالا، آماده چاپ\n\n"
    "برای شروع، از منوی پایین <b>«🎨 ثبت سفارش جدید»</b> را بزنید 👇"
)


async def welcome_text(name: str) -> str:
    """Admin can override the text from settings; {name} is replaced with the customer's first name."""
    template = await setting("welcome_text") or DEFAULT_WELCOME
    return template.replace("{name}", esc(name))


def price_range() -> str:
    return f"{money(catalog.price_min)} تا {money(catalog.price_max)}"


async def help_text() -> str:
    delivery_time = esc(await setting("delivery_time"))
    percent = fa(await referral_percent())
    support = await support_username()
    ref_when = "که ربات را با لینک شما استارت کند" if await setting("referral_mode") == "join" else "که اولین سفارشش را ثبت و پرداخت کند"
    return (
        "📌 <b>راهنمای جامع سفارش در لینوریا</b>\n\n"
        "<b>🛒 مراحل سفارش:</b>\n"
        "۱. «🎨 ثبت سفارش جدید» را بزنید، نوع اثر و تعداد افراد را انتخاب کنید.\n"
        "۲. عکس یا عکس‌های مورد نظرتان را بفرستید و اگر توضیحی دارید بنویسید.\n"
        "۳. ما عکس‌ها را بررسی می‌کنیم و <b>قیمت دقیق</b> را برایتان می‌فرستیم.\n"
        "۴. مبلغ را کارت‌به‌کارت کنید و <b>عکس رسید</b> را در ربات بفرستید.\n"
        "۵. بعد از تایید پرداخت، کار شروع می‌شود و ابتدا <b>پیش‌نمایش</b> برایتان ارسال می‌شود.\n"
        "۶. اگر راضی بودید تایید کنید؛ در غیر این صورت درخواست اصلاح بدهید.\n"
        "۷. <b>فایل نهایی</b> با کیفیت بالا همین‌جا تحویل داده می‌شود.\n\n"
        "<b>💰 قیمت:</b>\n"
        f"بسته به حجم کار (تعداد افراد، جزئیات و پس‌زمینه) بین <b>{price_range()}</b>.\n\n"
        "<b>📸 کیفیت عکس:</b>\n"
        "هر چه عکس شما واضح‌تر و با نور بهتر باشد، جزئیات نقاشی دقیق‌تر و زیباتر می‌شود. "
        "برای بهترین کیفیت، عکس را به صورت <b>فایل (File)</b> بفرستید.\n\n"
        "<b>📁 نحوه تحویل:</b>\n"
        "تحویل فقط به صورت <b>فایل دیجیتال با کیفیت بسیار بالا</b> است (ارسال پستی نداریم). "
        "فایل هم برای پروفایل و شبکه‌های اجتماعی مناسب است و هم قابلیت <b>چاپ</b> روی کاغذ عکس، تخته‌شاسی و بوم را دارد.\n\n"
        f"<b>⏱ زمان آماده‌سازی:</b> {delivery_time} بعد از تایید پرداخت\n\n"
        f"<b>🎁 تخفیف:</b> از «دعوت دوستان» لینک خودتان را بگیرید؛ به ازای هر دوستی {ref_when}، یک تخفیف {percent}٪ می‌گیرید.\n\n"
        "<b>📦 پیگیری:</b> از «📦 سفارش‌های من» وضعیت سفارش‌ها را ببینید. هر تغییری هم خودکار به شما اطلاع داده می‌شود.\n\n"
        + (f"❓ سوالی دارید؟ به @{support} پیام دهید." if support else "❓ سوالی دارید؟ از «💬 پشتیبانی» پیام دهید.")
    )


async def prices_text() -> str:
    percent = fa(await referral_percent())
    styles = "\n".join(f"▫️ {s.title}" + (f"\n     <i>{esc(s.description)}</i>" if s.description else "") for s in catalog.styles)
    return (
        "💰 <b>تعرفه‌های لینوریا</b>\n\n"
        f"قیمت هر اثر <b>بسته به حجم کار</b> بین <b>{price_range()}</b> است.\n\n"
        "عوامل موثر در قیمت:\n"
        "▫️ تعداد افراد در نقاشی\n"
        "▫️ میزان جزئیات (مو، لباس، زیورآلات و ...)\n"
        "▫️ پس‌زمینه و المان‌های اضافه\n\n"
        f"<b>🎨 خدمات ما:</b>\n{styles}\n\n"
        "📁 تحویل: فایل دیجیتال با کیفیت بالا و قابل چاپ\n\n"
        "💡 بعد از ثبت سفارش و ارسال عکس، قیمت دقیق برایتان اعلام می‌شود. "
        "تا وقتی قیمت را تایید و پرداخت نکنید، هیچ تعهدی ندارید.\n\n"
        f"🎁 با دعوت دوستان {percent}٪ تخفیف بگیرید!"
    )


async def payment_text(order: dict) -> str:
    card = esc(await setting("card_number"))
    holder = esc(await setting("card_holder"))
    bank = esc(await setting("bank_name"))
    return "\n".join(
        [f"🧾 <b>پرداخت سفارش #{fa(order['id'])}</b>", ""]
        + price_lines(order)
        + [
            "",
            "لطفاً مبلغ را به کارت زیر واریز کنید:",
            f"💳 <code>{card}</code>",
            f"👤 به نام: <b>{holder}</b>",
            f"🏦 {bank}",
            "",
            "<i>(روی شماره کارت بزنید تا کپی شود)</i>",
            "",
            "📸 بعد از واریز، دکمه «ارسال عکس رسید» را بزنید و <b>عکس رسید</b> را بفرستید.",
        ]
    )
