from aiogram.filters.callback_data import CallbackData


class Pick(CallbackData, prefix="pick"):
    field: str       # style | faces
    value: str


class Nav(CallbackData, prefix="nav"):
    action: str      # back | cancel | photos_done | skip_desc | confirm | edit


class MyOrder(CallbackData, prefix="my"):
    action: str      # view | pay | cancel | cancel_yes | files | list | receipt_for
    order_id: int = 0


class Preview(CallbackData, prefix="pv"):
    action: str      # ok | revise
    order_id: int


class Rate(CallbackData, prefix="rate"):
    order_id: int
    stars: int


class Adm(CallbackData, prefix="adm"):
    action: str
    order_id: int = 0
    arg: str = ""
