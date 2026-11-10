import logging  
import re  
  
from aiogram import Bot  
from aiogram.types import Message  
  
from Reply import (  
    ADMIN_COMMAND,  
    ANIMATION,  
    ANIMATION_MSG,  
    BOT_TRIGGER,  
    DEFAULT,  
    EDIT_KEYWORDS,  
    LANG_MSG,  
    MODE_MSG,  
    NOTE,  
    RANDOM_REPLIES,  
    VOICE,  
)  
from Nookie import get_random_reply_markup  
from bToN import (  
    build_animation_markup,  
    build_default_markup,  
    build_lang_markup,  
    build_mode_markup,  
    build_note_markup,  
)  
from cAsh import (  
    AdtStorage,  
    AllowedStorage,  
    ButtonCycleStorage,  
    LangCodeStorage,  
    LangStorage,  
    ModeStorage,  
    NotifStorage,  
    PendingStorage,  
    ReplyCounter,  
    get_mode_key,  
)  
from cAsh_Two import (  
    AnimationSettings,  
    DefaultSettings,  
    FileIdCache,  
    NoteSettings,  
)  
from ediT import handle_pending_edit, set_edit_state  
from MesSA import handle_admin_logic, handle_translation_logic, process_url  
from MesSA_Two import handle_media_request  
from perM import authorize  
  
log = logging.getLogger("voicebot")  
URL_RE = re.compile(r"https?://\S+")  
  
  
def _build_menu_for(  
    last_menu: str,  
    current_mode: str,  
    lang_active: bool,  
    lang_code: str,  
    animation_settings: dict,  
    note_settings: dict,  
    default_settings: dict,  
    owner_id: int,  
    mode_key: str,  
    notif_active: bool,  
) -> tuple[str, object]:  
    if last_menu == "animation":  
        return (  
            ANIMATION_MSG.format(ANIMATION),  
            build_animation_markup(  
                animation_settings, owner_id, mode_key, current_mode == "animation"  
            ),  
        )  
    if last_menu == "note":  
        return (  
            ANIMATION_MSG.format(NOTE),  
            build_note_markup(  
                note_settings, owner_id, mode_key, current_mode == "note"  
            ),  
        )  
    if last_menu == "default":  
        return (  
            ANIMATION_MSG.format(DEFAULT),  
            build_default_markup(  
                default_settings, owner_id, mode_key, current_mode == "default"  
            ),  
        )  
    if last_menu == "lang":  
        return (  
            LANG_MSG,  
            build_lang_markup(lang_active, lang_code, owner_id, mode_key),  
        )  
    return (  
        MODE_MSG,  
        build_mode_markup(  
            current_mode, lang_active, owner_id, mode_key, notif_active  
        ),  
    )  
  
  
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
        chat_id, user_id, mode_key = get_mode_key(message)  
  
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
                last_menu = await modes.get_last_menu(mode_key)  
                notif_active = await notif.get(mode_key)  
                text_to_send, markup = _build_menu_for(  
                    last_menu,  
                    await modes.get(mode_key),  
                    await lang.get(mode_key),  
                    await lang_code.get(mode_key),  
                    await animation.get(mode_key),  
                    await note.get(mode_key),  
                    await default.get(mode_key),  
                    user_id,  
                    mode_key,  
                    notif_active,  
                )  
                await message.reply(text_to_send, reply_markup=markup)  
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