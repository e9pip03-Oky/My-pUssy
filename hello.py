import asyncio
import logging
import os

from aiogram import Bot, Dispatcher

import bToN
import CAsh
import NAMe


BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_TAKEOFF = os.getenv("boT_TAkeoFF")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")

    CAsh.initialize_database()
    NAMe.initialize_base_folder()

    bot = Bot(token=BOT_TOKEN)
    dispatcher = Dispatcher()

    bToN.configure(BOT_TAKEOFF)
    dispatcher.include_router(bToN.router)

    await bToN.send_startup_messages(bot)

    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())