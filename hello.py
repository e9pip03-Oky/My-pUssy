import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher

from Nookie import register
from Reply import BOOT_TEXT
from bToN import build_buttons, build_markup, parse_ids
from cAsh_Two import (
    build_adt,
    build_animation,
    build_btn_cycle,
    build_counter,
    build_default,
    build_file_cache,
    build_lang,
    build_lang_code,
    build_modes,
    build_note,
    build_notif,
    build_storage,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
REDIS_URL = os.environ.get("REDIS_URL")
BOT_NOTICE = os.environ.get("boT_NoTice", "")

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
log = logging.getLogger("voicebot")


async def send_boot_notice(bot: Bot) -> None:
    for user_id, name, style in build_buttons(parse_ids(BOT_NOTICE)):
        try:
            await bot.send_message(
                user_id, BOOT_TEXT, reply_markup=build_markup(name, user_id, style)
            )
        except Exception as exc:
            log.warning("boot notice to %s failed: %s", user_id, exc)


async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    dispatcher = Dispatcher(storage=build_storage(REDIS_URL))
    register(
        dispatcher,
        build_counter(REDIS_URL),
        build_modes(REDIS_URL),
        build_adt(REDIS_URL),
        build_lang(REDIS_URL),
        build_lang_code(REDIS_URL),
        build_btn_cycle(REDIS_URL),
        build_animation(REDIS_URL),
        build_note(REDIS_URL),
        build_default(REDIS_URL),
        build_file_cache(REDIS_URL),
        build_notif(REDIS_URL),
    )
    await send_boot_notice(bot)
    await dispatcher.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
