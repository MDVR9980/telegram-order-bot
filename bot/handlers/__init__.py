from aiogram import Router

from . import admin, admin_manage, common, order, user


def setup_routers() -> Router:
    root = Router()
    # order matters: global cancel first, generic fallbacks last
    root.include_routers(common.router, admin.router, admin_manage.router, order.router, user.router, common.fallback)
    return root
