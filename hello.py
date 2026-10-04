import asyncio
from collections import defaultdict

from aiogram import (
    Bot,
    Dispatcher,
    F,
    Router,
)
from aiogram.enums import ButtonStyle
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import CAsh
import Reply
import SeTTiNGS
import bToN


router = Router()

response_indexes = defaultdict(int)

button_name_index = 0
button_style_index = 0
button_id_index = 0


def _dynamic_button():
    global button_name_index
    global button_style_index
    global button_id_index

    names = Reply.DYNAMIC_BUTTON_NAMES
    ids = bToN.get_takeoff_ids()

    if not ids:
        return None

    styles = (
        ButtonStyle.PRIMARY,
        ButtonStyle.DANGER,
        ButtonStyle.SUCCESS,
    )

    name = names[
        button_name_index
        % len(names)
    ]

    style = styles[
        button_style_index
        % len(styles)
    ]

    user_id = ids[
        button_id_index
        % len(ids)
    ]

    button_name_index += 1
    button_style_index += 1
    button_id_index += 1

    return InlineKeyboardButton(
        text=name,
        url=f"tg://user?id={user_id}",
        style=style,
    )


def _dynamic_markup():
    button = _dynamic_button()

    if button is None:
        return None

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button]
        ]
    )


def _next_response(user_id):
    responses = Reply.ROTATING_RESPONSES

    if not responses:
        return ""

    index = response_indexes[user_id]

    response_indexes[user_id] = (
        index + 1
    ) % len(responses)

    return responses[index]


def _settings_key(message):
    return bToN.settings_key(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        thread_id=message.message_thread_id,
        chat_type=message.chat.type,
    )


async def _authorized(
    bot,
    chat_id,
    user_id,
    chat_type,
):
    if chat_type == "private":
        return True

    member = await bot.get_chat_member(
        chat_id,
        user_id,
    )

    return (
        member.status.value
        in bToN.ADMIN_STATUSES
    )


def _settings_keyboard(mode):
    voice_style = (
        ButtonStyle.PRIMARY
        if mode == bToN.MODE_VOICE
        else ButtonStyle.DANGER
    )

    normal_style = (
        ButtonStyle.PRIMARY
        if mode == bToN.MODE_NORMAL
        else ButtonStyle.DANGER
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=Reply.MODE_VOICE,
                    callback_data=bToN.mode_callback(
                        bToN.MODE_VOICE
                    ),
                    style=voice_style,
                ),
                InlineKeyboardButton(
                    text=Reply.MODE_NORMAL,
                    callback_data=bToN.mode_callback(
                        bToN.MODE_NORMAL
                    ),
                    style=normal_style,
                ),
            ]
        ]
    )


async def _show_settings(
    message,
    mode,
):
    await message.reply(
        Reply.SETTINGS_TEXT,
        reply_markup=_settings_keyboard(
            mode
        ),
    )


@router.message(
    F.text == Reply.COMMAND_SETTINGS
)
async def settings_handler(
    message: Message,
    bot: Bot,
):
    if not await _authorized(
        bot,
        message.chat.id,
        message.from_user.id,
        message.chat.type,
    ):
        return

    key = _settings_key(message)

    mode = await CAsh.get_mode(
        key,
        bToN.MODE_NORMAL,
    )

    await _show_settings(
        message,
        mode,
    )


@router.callback_query(
    F.data.startswith(
        bToN.CALLBACK_PREFIX
    )
)
async def mode_handler(
    callback: CallbackQuery,
    bot: Bot,
):
    message = callback.message

    if message is None:
        return

    if not await _authorized(
        bot,
        message.chat.id,
        callback.from_user.id,
        message.chat.type,
    ):
        await callback.answer(
            Reply.SETTINGS_UNAUTHORIZED,
            show_alert=True,
        )
        return

    selected_mode = (
        bToN.parse_mode_callback(
            callback.data
        )
    )

    if selected_mode not in {
        bToN.MODE_NORMAL,
        bToN.MODE_VOICE,
    }:
        await callback.answer()
        return

    key = bToN.settings_key(
        chat_id=message.chat.id,
        user_id=callback.from_user.id,
        thread_id=message.message_thread_id,
        chat_type=message.chat.type,
    )

    current_mode = await CAsh.get_mode(
        key,
        bToN.MODE_NORMAL,
    )

    if selected_mode == current_mode:
        selected_mode = bToN.next_mode(
            current_mode
        )

    await CAsh.save_mode(
        key,
        selected_mode,
    )

    await message.edit_reply_markup(
        reply_markup=_settings_keyboard(
            selected_mode
        )
    )

    await callback.answer()


@router.message(
    F.text == Reply.COMMAND_BOT
)
async def bot_command_handler(
    message: Message,
):
    if message.chat.type in {
        "private",
        "group",
        "supergroup",
    }:
        await _send_rotating_response(
            message
        )


async def _send_rotating_response(
    message,
):
    text = _next_response(
        message.from_user.id
    )

    if not text:
        return

    await message.reply(
        text,
        reply_markup=_dynamic_markup(),
    )


@router.message(F.text)
async def text_handler(
    message: Message,
    bot: Bot,
):
    text = message.text.strip()

    if text in {
        Reply.COMMAND_SETTINGS,
        Reply.COMMAND_BOT,
    }:
        return

    if bToN.is_telegram_url(text):
        return

    if not (
        text.startswith("http://")
        or text.startswith("https://")
    ):
        if message.chat.type == "private":
            await _send_rotating_response(
                message
            )

        return

    key = _settings_key(message)

    mode = await CAsh.get_mode(
        key,
        bToN.MODE_NORMAL,
    )

    accepted = await SeTTiNGS.submit(
        bot,
        message,
        text,
        mode,
    )

    if (
        accepted
        and Reply.DOWNLOAD_STARTED
    ):
        await message.reply(
            Reply.DOWNLOAD_STARTED
        )


async def _startup(bot):
    for user_id in bToN.get_takeoff_ids():
        await bot.send_message(
            chat_id=user_id,
            text=Reply.STARTUP_TEXT,
            reply_markup=_dynamic_markup(),
        )


async def main():
    token = bToN.get_bot_token()

    if not token:
        raise RuntimeError(
            "BOT_TOKEN is not set"
        )

    await CAsh.configure(
        bToN.get_db_path()
    )

    bot = Bot(token)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    await _startup(bot)

    try:
        await dispatcher.start_polling(
            bot
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())