from aiogram.fsm.state import State, StatesGroup


class OrderFlow(StatesGroup):
    style = State()
    faces = State()
    photos = State()
    description = State()
    confirm = State()


class ReceiptFlow(StatesGroup):
    waiting = State()          # data: order_id


class PromoFlow(StatesGroup):
    code = State()             # data: order_id


class RevisionFlow(StatesGroup):
    text = State()             # data: order_id


class SupportFlow(StatesGroup):
    text = State()


class AdminFlow(StatesGroup):
    custom_price = State()     # data: order_id
    promo_code = State()       # new promo wizard: code
    promo_value = State()      # data: code
    promo_uses = State()       # data: code, kind, value
    promo_days = State()       # data: code, kind, value, max_uses
    catalog_value = State()    # data: field (price_range | quick_prices | max_photos)
    option_add = State()       # data: kind
    option_edit = State()      # data: kind, option_id
    reject_reason = State()    # data: order_id
    upload = State()           # data: order_id, kind, files, caption
    message_user = State()     # data: user_id, order_id
    broadcast = State()
    broadcast_confirm = State()
    setting_value = State()    # data: key
    add_admin = State()
    find_order = State()
