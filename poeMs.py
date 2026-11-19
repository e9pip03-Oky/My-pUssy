import logging

from aiogram import Bot
from aiogram.types import Message

from cAsh import get_mode_key
from cAsh_Two import NotifStorage

log = logging.getLogger("voicebot")

SERVICE_FIELDS = (
    "new_chat_members",
    "left_chat_member",
    "chat_owner_left",
    "chat_owner_changed",
    "new_chat_title",
    "new_chat_photo",
    "delete_chat_photo",
    "message_auto_delete_timer_changed",
    "pinned_message",
    "successful_payment",
    "refunded_payment",
    "users_shared",
    "chat_shared",
    "forum_topic_edited",
    "forum_topic_closed",
    "forum_topic_reopened",
    "general_forum_topic_hidden",
    "general_forum_topic_unhidden",
    "video_chat_started",
    "video_chat_ended",
    "video_chat_participants_invited",
    "video_chat_scheduled",
)


def _is_service_message(message: Message) -> bool:
    return any(getattr(message, field, None) for field in SERVICE_FIELDS)


async def on_service_message(message: Message, bot: Bot, notif: NotifStorage) -> None:
    if not message.chat:
        return
    if not _is_service_message(message):
        return
    chat_id, _, mode_key = get_mode_key(message)
    if not await notif.get(mode_key):
        return
    try:
        await bot.delete_message(chat_id, message.message_id)
    except Exception:
        pass


def make_service_cleaner(notif: NotifStorage):
    async def handler(message: Message, bot: Bot):
        await on_service_message(message, bot, notif)

    return handler
