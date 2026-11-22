import logging
import re
from typing import Final

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
from cAsh import get_mode_context
from cAsh_Two import (
    AdtStorage,
    AllowedStorage,
    AnimationSettings,
    ButtonCycleStorage,
    DefaultSettings,
    FileIdCache,
    LangCodeStorage,
    LangStorage,
    ModeStorage,
    NoteSettings,
    NotifStorage,
    PendingStorage,
    ReplyCounter,
)
from ediT import handle_pending_edit, set_edit_state
from MesSA import handle_admin_logic, handle_translation_logic, process_url
from MesSA_Two import handle_media_request
from perM import authorize

log = logging.getLogger("voicebot")
URL_RE: Final = re.compile(r"https?://\S+")


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
    notif: NotifStorage,
    allowed: AllowedStorage,
    pending: PendingStorage,
    boot_notice: str,
):
    async def _random_reply(message: Message, chat_id: int, user_id: int):
        index = await counter.next_index(user_id, len(RANDOM_REPLIES))
        markup = await get_random_reply_markup(chat_id, btn_cycle, boot_notice)
        await message.reply(RANDOM_REPLIES[index], reply_markup=markup)

    async def _process(message: Message, bot: Bot):
        ctx = get_mode_context(message)
        chat_id, user_id, mode_key = ctx.chat_id, ctx.user_id, ctx.mode_key

        if message.chat.type == "private":
            if not await authorize(message, allowed, pending, bot, boot_notice):
                return

        if not message.text:
            return
        text = message.text.strip()

        if message.from_user is not None:
            if await handle_pending_edit(message, bot, file_cache):
                return

        if message.reply_to_message and text in (NOTE, VOICE, ANIMATION):
            if await handle_media_request(
                message, bot, text, animation, note, file_cache
            ):
                return

        if (
            message.from_user is not None
            and message.reply_to_message
            and text.startswith(EDIT_KEYWORDS)
        ):
            reply = message.reply_to_message
            if reply.voice or reply.video_note or reply.video or reply.animation:
                await set_edit_state(message)
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
                sent = await message.reply(
                    MODE_MSG,
                    reply_markup=build_mode_markup(
                        await modes.get(mode_key),
                        await lang.get(mode_key),
                        user_id,
                        mode_key,
                        await notif.get(mode_key),
                    ),
                )
                await handle_admin_logic(
                    message, bot, mode_key, adt, new_message_id=sent.message_id
                )
                return

        if await lang.get(mode_key):
            translated = await handle_translation_logic(text, mode_key, lang_code)
            if translated:
                await message.reply(translated)
                return

        if message.chat.type == "private" or text == BOT_TRIGGER:
            await _random_reply(message, chat_id, user_id)

    async def on_message(message: Message, bot: Bot):
        await _process(message, bot)

    async def on_channel_post(message: Message, bot: Bot):
        await _process(message, bot)

    return on_message, on_channel_post
