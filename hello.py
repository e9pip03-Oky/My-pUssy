import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from Nookie import register
from Reply import BOOT_TEXT
from bToN import build_buttons, build_markup, parse_ids
from cAsh import build_storage
from cAsh_Two import (
    build_adt,
    build_allowed,
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
    build_pending,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
REDIS_URL = os.environ.get("REDIS_URL", "")
BOT_NOTICE = os.environ.get("boT_NoTice", "")
API_ID = os.environ.get("API_ID", "")
API_HASH = os.environ.get("API_HASH", "")
API_URL = os.environ.get("API_URL", "http://127.0.0.1:8081")

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
    if not REDIS_URL:
        raise RuntimeError("REDIS_URL is required")
    session = AiohttpSession(api=TelegramAPIServer.from_base(API_URL))
    bot = Bot(token=BOT_TOKEN, session=session)
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
        build_allowed(REDIS_URL),
        build_pending(REDIS_URL),
        BOT_NOTICE,
    )
    await send_boot_notice(bot)
    await dispatcher.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())