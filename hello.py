import asyncio
import logging
import unicodedata
from collections import defaultdict

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ButtonStyle
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from googletrans import Translator

import AUdio
import CAsh
import Reply
import SeTTiNGS
import bToN
import ediT

router = Router()
logger = logging.getLogger(__name__)

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

    name = names[button_name_index % len(names)]
    style = styles[button_style_index % len(styles)]
    user_id = ids[button_id_index % len(ids)]

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
        inline_keyboard=[[button]]
    )


def _next_response(user_id):
    responses = Reply.ROTATING_RESPONSES

    if not responses:
        return ""

    index = response_indexes[user_id]
    response_indexes[user_id] = (index + 1) % len(responses)

    return responses[index]


def _settings_key(message, user_id=None):
    if user_id is None:
        user_id = message.from_user.id

    return bToN.settings_key(
        chat_id=message.chat.id,
        user_id=user_id,
        thread_id=message.message_thread_id,
        chat_type=message.chat.type,
    )


def _language_enabled_key(key):
    return f"{bToN.LANGUAGE_ENABLED_KEY_PREFIX}{key}"


def _language_target_key(key):
    return f"{bToN.LANGUAGE_TARGET_KEY_PREFIX}{key}"


def _sticker_landscape_key(key):
    return f"{bToN.STICKER_LANDSCAPE_KEY_PREFIX}{key}"


def _sticker_portrait_key(key):
    return f"{bToN.STICKER_PORTRAIT_KEY_PREFIX}{key}"


def _sticker_flip_horizontal_key(key):
    return f"{bToN.STICKER_FLIP_HORIZONTAL_KEY_PREFIX}{key}"


def _sticker_flip_vertical_key(key):
    return f"{bToN.STICKER_FLIP_VERTICAL_KEY_PREFIX}{key}"


def _sticker_previous_mode_key(key):
    return f"{bToN.STICKER_PREVIOUS_MODE_KEY_PREFIX}{key}"


async def _get_language_enabled(key):
    value = await CAsh.get_setting(
        _language_enabled_key(key),
        bToN.LANGUAGE_DISABLED,
    )

    return value == bToN.LANGUAGE_ENABLED


async def _get_language_target(key):
    value = await CAsh.get_setting(
        _language_target_key(key),
        bToN.LANGUAGE_DEFAULT_TARGET,
    )

    if value not in {
        bToN.LANGUAGE_TARGET_ENGLISH,
        bToN.LANGUAGE_TARGET_RUSSIAN,
    }:
        return bToN.LANGUAGE_DEFAULT_TARGET

    return value


async def _get_sticker_option_states(key):
    defaults = bToN.STICKER_OPTION_DISABLED

    values = await asyncio.gather(
        CAsh.get_setting(_sticker_landscape_key(key), defaults),
        CAsh.get_setting(_sticker_portrait_key(key), defaults),
        CAsh.get_setting(_sticker_flip_horizontal_key(key), defaults),
        CAsh.get_setting(_sticker_flip_vertical_key(key), defaults),
    )

    return {
        bToN.STICKER_LANDSCAPE: (
            values[0] == bToN.STICKER_OPTION_ENABLED
        ),
        bToN.STICKER_PORTRAIT: (
            values[1] == bToN.STICKER_OPTION_ENABLED
        ),
        bToN.STICKER_FLIP_HORIZONTAL: (
            values[2] == bToN.STICKER_OPTION_ENABLED
        ),
        bToN.STICKER_FLIP_VERTICAL: (
            values[3] == bToN.STICKER_OPTION_ENABLED
        ),
    }


async def _get_sticker_options(key):
    states = await _get_sticker_option_states(key)

    if states[bToN.STICKER_LANDSCAPE]:
        orientation = bToN.STICKER_LANDSCAPE
    elif states[bToN.STICKER_PORTRAIT]:
        orientation = bToN.STICKER_PORTRAIT
    else:
        orientation = bToN.STICKER_OPTION_NONE

    if states[bToN.STICKER_FLIP_HORIZONTAL]:
        flip = bToN.STICKER_FLIP_HORIZONTAL
    elif states[bToN.STICKER_FLIP_VERTICAL]:
        flip = bToN.STICKER_FLIP_VERTICAL
    else:
        flip = bToN.STICKER_OPTION_NONE

    return orientation, flip


async def _settings_mode(key):
    mode = await CAsh.get_mode(key, bToN.MODE_NORMAL)

    if mode != bToN.MODE_STICKER:
        return mode, False

    previous_mode = await CAsh.get_setting(
        _sticker_previous_mode_key(key),
        bToN.MODE_NORMAL,
    )

    if previous_mode not in {
        bToN.MODE_NORMAL,
        bToN.MODE_VOICE,
    }:
        previous_mode = bToN.MODE_NORMAL

    return previous_mode, True


async def _authorized(bot, chat_id, user_id, chat_type):
    if chat_type == "private":
        return True

    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        return False

    return member.status.value in bToN.ADMIN_STATUSES


async def _edit_reply_markup(message, reply_markup):
    try:
        await message.edit_reply_markup(
            reply_markup=reply_markup
        )
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):
            raise


def _settings_keyboard(
    mode,
    language_enabled=False,
    sticker_active=False,
):
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

    sticker_style = (
        ButtonStyle.PRIMARY
        if sticker_active
        else ButtonStyle.DANGER
    )

    language_style = (
        ButtonStyle.PRIMARY
        if language_enabled
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
            ],
            [
                InlineKeyboardButton(
                    text=Reply.MODE_STICKER,
                    callback_data=bToN.STICKER_OPEN_CALLBACK,
                    style=sticker_style,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=Reply.BUTTON_LANGUAGE,
                    callback_data=bToN.LANGUAGE_TOGGLE_CALLBACK,
                    style=language_style,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=Reply.BUTTON_CHANGE_LANGUAGE,
                    callback_data=bToN.LANGUAGE_CHOOSE_CALLBACK,
                    style=ButtonStyle.SUCCESS,
                ),
            ],
        ]
    )


def _language_keyboard(target):
    english_style = (
        ButtonStyle.PRIMARY
        if target == bToN.LANGUAGE_TARGET_ENGLISH
        else ButtonStyle.DANGER
    )

    russian_style = (
        ButtonStyle.PRIMARY
        if target == bToN.LANGUAGE_TARGET_RUSSIAN
        else ButtonStyle.DANGER
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=Reply.BUTTON_LANGUAGE_ENGLISH,
                    callback_data=(
                        f"{bToN.LANGUAGE_TARGET_CALLBACK_PREFIX}"
                        f"{bToN.LANGUAGE_TARGET_ENGLISH}"
                    ),
                    style=english_style,
                ),
                InlineKeyboardButton(
                    text=Reply.BUTTON_LANGUAGE_RUSSIAN,
                    callback_data=(
                        f"{bToN.LANGUAGE_TARGET_CALLBACK_PREFIX}"
                        f"{bToN.LANGUAGE_TARGET_RUSSIAN}"
                    ),
                    style=russian_style,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=Reply.BUTTON_LANGUAGE_BACK,
                    callback_data=bToN.LANGUAGE_BACK_CALLBACK,
                    style=ButtonStyle.SUCCESS,
                ),
            ],
        ]
    )


async def _sticker_keyboard(key, sticker_active):
    states = await _get_sticker_option_states(key)

    def option_button(option, label):
        return InlineKeyboardButton(
            text=label,
            callback_data=(
                f"{bToN.STICKER_OPTION_CALLBACK_PREFIX}"
                f"{option}"
            ),
            style=(
                ButtonStyle.PRIMARY
                if states[option]
                else ButtonStyle.DANGER
            ),
        )

    activation_label = (
        Reply.STICKER_DISABLE
        if sticker_active
        else Reply.STICKER_ENABLE
    )

    activation_style = (
        ButtonStyle.PRIMARY
        if sticker_active
        else ButtonStyle.DANGER
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                option_button(
                    bToN.STICKER_LANDSCAPE,
                    Reply.STICKER_LANDSCAPE,
                ),
                option_button(
                    bToN.STICKER_PORTRAIT,
                    Reply.STICKER_PORTRAIT,
                ),
            ],
            [
                option_button(
                    bToN.STICKER_FLIP_HORIZONTAL,
                    Reply.STICKER_FLIP_HORIZONTAL,
                ),
                option_button(
                    bToN.STICKER_FLIP_VERTICAL,
                    Reply.STICKER_FLIP_VERTICAL,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=activation_label,
                    callback_data=bToN.STICKER_ACTIVATE_CALLBACK,
                    style=activation_style,
                ),
            ],
        ]
    )


async def _show_settings(
    message,
    mode,
    language_enabled=False,
    sticker_active=False,
):
    await message.reply(
        Reply.SETTINGS_TEXT,
        reply_markup=_settings_keyboard(
            mode,
            language_enabled,
            sticker_active,
        ),
    )


@router.message(F.text == Reply.COMMAND_SETTINGS)
async def settings_handler(message: Message, bot: Bot):
    if not await _authorized(
        bot,
        message.chat.id,
        message.from_user.id,
        message.chat.type,
    ):
        return

    key = _settings_key(message)
    mode, sticker_active = await _settings_mode(key)
    language_enabled = await _get_language_enabled(key)

    await _show_settings(
        message,
        mode,
        language_enabled,
        sticker_active,
    )


@router.callback_query(
    F.data.startswith(bToN.STICKER_CALLBACK_PREFIX)
)
async def sticker_handler(callback: CallbackQuery, bot: Bot):
    message = callback.message

    if message is None:
        await callback.answer()
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

    key = _settings_key(message, callback.from_user.id)
    data = callback.data
    mode, sticker_active = await _settings_mode(key)

    if data == bToN.STICKER_OPEN_CALLBACK:
        await _edit_reply_markup(
            message,
            await _sticker_keyboard(key, sticker_active),
        )

    elif data == bToN.STICKER_ACTIVATE_CALLBACK:
        current_mode = await CAsh.get_mode(
            key,
            bToN.MODE_NORMAL,
        )

        if current_mode == bToN.MODE_STICKER:
            previous_mode = await CAsh.get_setting(
                _sticker_previous_mode_key(key),
                bToN.MODE_NORMAL,
            )

            if previous_mode not in {
                bToN.MODE_NORMAL,
                bToN.MODE_VOICE,
            }:
                previous_mode = bToN.MODE_NORMAL

            await CAsh.save_mode(key, previous_mode)
            mode = previous_mode
            sticker_active = False

        else:
            previous_mode = (
                current_mode
                if current_mode in {
                    bToN.MODE_NORMAL,
                    bToN.MODE_VOICE,
                }
                else bToN.MODE_NORMAL
            )

            await CAsh.save_setting(
                _sticker_previous_mode_key(key),
                previous_mode,
            )
            await CAsh.save_mode(key, bToN.MODE_STICKER)

            mode = previous_mode
            sticker_active = True

        language_enabled = await _get_language_enabled(key)

        await _edit_reply_markup(
            message,
            _settings_keyboard(
                mode,
                language_enabled,
                sticker_active,
            ),
        )

    elif data.startswith(
        bToN.STICKER_OPTION_CALLBACK_PREFIX
    ):
        option = data[
            len(bToN.STICKER_OPTION_CALLBACK_PREFIX):
        ]

        key_map = {
            bToN.STICKER_LANDSCAPE: (
                _sticker_landscape_key,
                _sticker_portrait_key,
            ),
            bToN.STICKER_PORTRAIT: (
                _sticker_portrait_key,
                _sticker_landscape_key,
            ),
            bToN.STICKER_FLIP_HORIZONTAL: (
                _sticker_flip_horizontal_key,
                _sticker_flip_vertical_key,
            ),
            bToN.STICKER_FLIP_VERTICAL: (
                _sticker_flip_vertical_key,
                _sticker_flip_horizontal_key,
            ),
        }

        if option not in key_map:
            await callback.answer()
            return

        selected_key, opposite_key = key_map[option]
        states = await _get_sticker_option_states(key)

        if states[option]:
            await CAsh.save_setting(
                selected_key(key),
                bToN.STICKER_OPTION_DISABLED,
            )
        else:
            await CAsh.save_setting(
                selected_key(key),
                bToN.STICKER_OPTION_ENABLED,
            )
            await CAsh.save_setting(
                opposite_key(key),
                bToN.STICKER_OPTION_DISABLED,
            )

        await _edit_reply_markup(
            message,
            await _sticker_keyboard(key, sticker_active),
        )

    await callback.answer()


@router.callback_query(
    F.data.startswith(bToN.CALLBACK_PREFIX)
)
async def mode_handler(callback: CallbackQuery, bot: Bot):
    message = callback.message

    if message is None:
        await callback.answer()
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

    selected_mode = bToN.parse_mode_callback(callback.data)

    if selected_mode not in {
        bToN.MODE_NORMAL,
        bToN.MODE_VOICE,
    }:
        await callback.answer()
        return

    key = _settings_key(message, callback.from_user.id)
    current_mode = await CAsh.get_mode(
        key,
        bToN.MODE_NORMAL,
    )

    if (
        current_mode != bToN.MODE_STICKER
        and selected_mode == current_mode
    ):
        selected_mode = bToN.next_mode(current_mode)

    await CAsh.save_mode(key, selected_mode)

    language_enabled = await _get_language_enabled(key)

    await _edit_reply_markup(
        message,
        _settings_keyboard(
            selected_mode,
            language_enabled,
            False,
        ),
    )

    await callback.answer()


@router.callback_query(
    F.data.startswith(bToN.LANGUAGE_CALLBACK_PREFIX)
)
async def language_handler(callback: CallbackQuery, bot: Bot):
    message = callback.message

    if message is None:
        await callback.answer()
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

    key = _settings_key(message, callback.from_user.id)
    data = callback.data

    if data == bToN.LANGUAGE_TOGGLE_CALLBACK:
        enabled = await _get_language_enabled(key)

        value = (
            bToN.LANGUAGE_DISABLED
            if enabled
            else bToN.LANGUAGE_ENABLED
        )

        await CAsh.save_setting(
            _language_enabled_key(key),
            value,
        )

        mode, sticker_active = await _settings_mode(key)

        await _edit_reply_markup(
            message,
            _settings_keyboard(
                mode,
                not enabled,
                sticker_active,
            ),
        )

    elif data == bToN.LANGUAGE_CHOOSE_CALLBACK:
        target = await _get_language_target(key)

        await _edit_reply_markup(
            message,
            _language_keyboard(target),
        )

    elif data == bToN.LANGUAGE_BACK_CALLBACK:
        mode, sticker_active = await _settings_mode(key)
        enabled = await _get_language_enabled(key)

        await _edit_reply_markup(
            message,
            _settings_keyboard(
                mode,
                enabled,
                sticker_active,
            ),
        )

    elif data.startswith(
        bToN.LANGUAGE_TARGET_CALLBACK_PREFIX
    ):
        target = data[
            len(bToN.LANGUAGE_TARGET_CALLBACK_PREFIX):
        ]

        if target not in {
            bToN.LANGUAGE_TARGET_ENGLISH,
            bToN.LANGUAGE_TARGET_RUSSIAN,
        }:
            await callback.answer()
            return

        current_target = await _get_language_target(key)

        if target == current_target:
            target = (
                bToN.LANGUAGE_TARGET_RUSSIAN
                if current_target == bToN.LANGUAGE_TARGET_ENGLISH
                else bToN.LANGUAGE_TARGET_ENGLISH
            )

        await CAsh.save_setting(
            _language_target_key(key),
            target,
        )

        await _edit_reply_markup(
            message,
            _language_keyboard(target),
        )

    await callback.answer()


@router.message(F.text == Reply.COMMAND_BOT)
async def bot_command_handler(message: Message):
    if message.chat.type in {
        "private",
        "group",
        "supergroup",
    }:
        await _send_rotating_response(message)


@router.message(F.text == Reply.COMMAND_EDIT)
async def edit_handler(message: Message, bot: Bot):
    await ediT.start_edit(bot, message)


@router.message(F.video | F.audio | F.voice | F.document)
async def audio_media_handler(message: Message, bot: Bot):
    await AUdio.inspect_message(message, bot)


def _is_script_letter(char, script):
    return char.isalpha() and script in unicodedata.name(char, "")


def _contains_script(text, script):
    return any(
        _is_script_letter(char, script)
        for char in text
    )


def _format_letter_case(text):
    result = []

    for char in text:
        if _is_script_letter(char, "LATIN"):
            if char.upper() in bToN.LANGUAGE_UPPER_EXCEPTIONS:
                result.append(char.upper())
            else:
                result.append(char.lower())

        elif _is_script_letter(char, "CYRILLIC"):
            if char.upper() in bToN.RUSSIAN_UPPER_EXCEPTIONS:
                result.append(char.upper())
            else:
                result.append(char.lower())

        else:
            result.append(char)

    return "".join(result)


async def _translate_text(text, target):
    async with Translator() as translator:
        result = await translator.translate(
            text,
            src="auto",
            dest=target,
        )

    return result.text


async def _language_response_text(text, target):
    has_latin = _contains_script(text, "LATIN")
    has_cyrillic = _contains_script(text, "CYRILLIC")

    if has_latin or has_cyrillic:
        return _format_letter_case(text)

    if _contains_script(text, "ARABIC"):
        translated = await _translate_text(text, target)

        if not translated:
            return None

        return _format_letter_case(translated)

    return _format_letter_case(text)


@router.message(F.text)
async def text_handler(message: Message, bot: Bot):
    if await ediT.handle_duration(bot, message):
        return

    text = message.text.strip()

    if text == Reply.COMMAND_AUDIO_START:
        handled = await AUdio.handle_start(message, bot)

        if handled:
            return

        if message.reply_to_message is not None:
            await _send_rotating_response(message)
        elif message.chat.type == "private":
            await _send_rotating_response(message)

        return

    if text in {
        Reply.COMMAND_SETTINGS,
        Reply.COMMAND_BOT,
        Reply.COMMAND_EDIT,
    }:
        return

    if bToN.is_telegram_url(text):
        return

    if not (
        text.startswith("http://")
        or text.startswith("https://")
    ):
        if message.chat.type == "private":
            key = _settings_key(message)

            if await _get_language_enabled(key):
                target = await _get_language_target(key)

                try:
                    result = await _language_response_text(
                        text,
                        target,
                    )
                except Exception:
                    logger.exception("Language translation failed")
                    return

                if result is not None:
                    await message.reply(result)

                return

            await _send_rotating_response(message)

        return

    key = _settings_key(message)
    mode = await CAsh.get_mode(key, bToN.MODE_NORMAL)

    if mode == bToN.MODE_STICKER:
        sticker_options = await _get_sticker_options(key)
    else:
        sticker_options = (
            bToN.STICKER_OPTION_NONE,
            bToN.STICKER_OPTION_NONE,
        )

    await SeTTiNGS.submit(
        bot,
        message,
        text,
        mode,
        sticker_options,
    )


async def _send_rotating_response(message):
    text = _next_response(message.from_user.id)

    if not text:
        return

    await message.reply(
        text,
        reply_markup=_dynamic_markup(),
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
        raise RuntimeError("BOT_TOKEN is not set")

    await CAsh.configure(bToN.get_db_path())
    await AUdio.configure(bToN.get_db_path())

    bot = Bot(token)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    try:
        await _startup(bot)
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())