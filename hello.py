import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher

import NoKi
from bToN import build_buttons, build_markup, parse_ids
from cAsh import (
    build_adt,
    build_btn_cycle,
    build_counter,
    build_file_cache,
    build_lang,
    build_lang_code,
    build_manager,
    build_modes,
    build_sticker,
    build_storage,
)
from Reply import BOOT_TEXT

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
REDIS_URL = os.environ.get("REDIS_URL")
BOT_NOTICE = os.environ.get("boT_NoTice", "")

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
log = logging.getLogger("voicebot")


async def send_boot_notice(bot: Bot) -> None:
    entries = build_buttons(parse_ids(BOT_NOTICE))

    for user_id, name, style in entries:
        try:
            markup = build_markup(name, user_id, style)
            await bot.send_message(user_id, BOOT_TEXT, reply_markup=markup)
        except Exception as exc:
            log.warning("boot notice to %s failed: %s", user_id, exc)


async def shutdown(
    bot: Bot,
    manager,
    fsm_storage,
) -> None:
    try:
        await bot.session.close()
        log.info("bot session closed")
    except Exception as exc:
        log.warning("bot close failed: %s", exc)

    try:
        redis_attr = getattr(fsm_storage, "redis", None) if fsm_storage else None
        if redis_attr:
            await redis_attr.aclose()
            log.info("fsm redis closed")
    except Exception as exc:
        log.warning("fsm redis close failed: %s", exc)

    try:
        await manager.close()
    except Exception as exc:
        log.warning("redis manager close failed: %s", exc)


async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    manager = build_manager(REDIS_URL)
    fsm_storage = build_storage(REDIS_URL)

    dispatcher = Dispatcher(storage=fsm_storage)
    NoKi.register(
        dispatcher,
        build_counter(manager),
        build_modes(manager),
        build_adt(manager),
        build_lang(manager),
        build_lang_code(manager),
        build_btn_cycle(manager),
        build_sticker(manager),
        build_file_cache(manager),
    )

    try:
        await send_boot_notice(bot)
        await dispatcher.start_polling(bot, drop_pending_updates=True)
    finally:
        await shutdown(bot, manager, fsm_storage)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("shutdown complete")