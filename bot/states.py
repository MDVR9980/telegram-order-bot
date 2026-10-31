from aiogram.fsm.state import State, StatesGroup


class OrderFlow(StatesGroup):
    style = State()
    size = State()
    faces = State()
    delivery = State()
    photos = State()
    description = State()
    phone = State()
    address = State()
    confirm = State()


class ReceiptFlow(StatesGroup):
    waiting = State()          # data: order_id


class RevisionFlow(StatesGroup):
    text = State()             # data: order_id


class SupportFlow(StatesGroup):
    text = State()


class AdminFlow(StatesGroup):
    reject_reason = State()    # data: order_id
    upload = State()           # data: order_id, kind, files
    message_user = State()     # data: user_id, order_id
    broadcast = State()
    broadcast_confirm = State()
    setting_value = State()    # data: key
    add_admin = State()
    find_order = State()
