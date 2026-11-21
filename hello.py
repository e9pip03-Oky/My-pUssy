import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher

from Nookie import register
from Reply import BOOT_TEXT
from bToN import build_buttons, build_markup, parse_ids
from cAsh_Two import build_all

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
    dispatcher = Dispatcher(storage=build_all.storage(REDIS_URL))
    register(
        dispatcher,
        build_all.counter(REDIS_URL),
        build_all.modes(REDIS_URL),
        build_all.adt(REDIS_URL),
        build_all.lang(REDIS_URL),
        build_all.lang_code(REDIS_URL),
        build_all.btn_cycle(REDIS_URL),
        build_all.animation(REDIS_URL),
        build_all.note(REDIS_URL),
        build_all.default(REDIS_URL),
        build_all.file_cache(REDIS_URL),
        build_all.notif(REDIS_URL),
        build_all.allowed(REDIS_URL),
        build_all.pending(REDIS_URL),
        BOT_NOTICE,
    )
    await send_boot_notice(bot)
    await dispatcher.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
