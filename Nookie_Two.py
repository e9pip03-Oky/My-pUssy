import logging
import re

from aiogram import Bot
from aiogram.types import Message

from Reply import (
    ADMIN_COMMAND,
    ANIMATION,
    BOT_TRIGGER,
    EDIT_KEYWORDS,
    MODE_MSG,
    NOTE,
    RANDOM_REPLIES,
    VOICE,
)
from Nookie import get_random_reply_markup
from bToN import build_mode_markup
from cAsh import get_mode_key
from cAsh_Two import (
    AdtStorage,
    AnimationSettings,
    ButtonCycleStorage,
    DefaultSettings,
    FileIdCache,
    LangCodeStorage,
    LangStorage,
    ModeStorage,
    NoteSettings,
    ReplyCounter,
)
from ediT import handle_pending_edit, set_edit_state
from MesSA import handle_admin_logic, handle_translation_logic, process_url
from MesSA_Two import handle_media_request

log = logging.getLogger("voicebot")
URL_RE = re.compile(r"https?://\S+")


def make_message_handler(
    counter: ReplyCounter,
    modes: ModeStorage,
    adt: AdtStorage,
    lang: LangStorage,
    lang_code: LangCodeStorage,
    btn_cycle: ButtonCycleStorage,
    animation: AnimationSettings,
    note: NoteSettings,
    default: DefaultSettings,
    file_cache: FileIdCache,
):
    async def _random_reply(message: Message, chat_id: int, user_id: int):
        index = await counter.next_index(user_id, len(RANDOM_REPLIES))
        markup = await get_random_reply_markup(chat_id, btn_cycle)
        await message.reply(RANDOM_REPLIES[index], reply_markup=markup)

    async def on_message(message: Message, bot: Bot):
        if not message.text:
            return
        text = message.text.strip()
        chat_id, user_id, mode_key = get_mode_key(message)

        if await handle_pending_edit(message, bot, file_cache):
            return

        if message.reply_to_message and text in (NOTE, VOICE, ANIMATION):
            if await handle_media_request(
                message, bot, text, animation, note, file_cache
            ):
                return

        if message.reply_to_message and text.startswith(EDIT_KEYWORDS):
            reply = message.reply_to_message
            if reply.voice or reply.video_note or reply.video or reply.animation:
                await set_edit_state(message, bot)
                return

        if url_match := URL_RE.search(text):
            url = url_match.group(0)
            if "t.me/" in url or "telegram.me/" in url:
                if message.chat.type == "private":
                    await _random_reply(message, chat_id, user_id)
                return
            await process_url(
                message,
                bot,
                url,
                mode_key,
                await modes.get(mode_key),
                animation,
                note,
                default,
                file_cache,
            )
            return

        if text == ADMIN_COMMAND:
            if await handle_admin_logic(message, bot, mode_key, adt):
                markup = build_mode_markup(
                    await modes.get(mode_key),
                    await lang.get(mode_key),
                    user_id,
                    mode_key,
                )
                sent = await message.reply(MODE_MSG, reply_markup=markup)
                if message.chat.type != "private":
                    old = await adt.get_messages(mode_key)
                    old.append(sent.message_id)
                    await adt.save_messages(mode_key, old)
                return

        if await lang.get(mode_key):
            translated = await handle_translation_logic(text, mode_key, lang_code)
            if translated:
                await message.reply(translated)
                return

        if message.chat.type == "private" or text == BOT_TRIGGER:
            await _random_reply(message, chat_id, user_id)

    return on_message