import logging

from aiogram import Bot
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.markdown import hlink

from Reply import (
    MODE_DENIED,
    PERM_ALLOW_BTN,
    PERM_ALLOWED_MSG,
    PERM_DENY_BTN,
    PERM_DENIED_MSG,
    PERM_REQUEST_MSG,
)
from bToN import parse_ids
from cAsh import AllowedStorage, PendingStorage

log = logging.getLogger("voicebot")


def _boot_ids(boot_notice: str) -> list[int]:
    return parse_ids(boot_notice)


async def authorize(
    message: Message,
    allowed: AllowedStorage,
    pending: PendingStorage,
    bot: Bot,
    boot_notice: str,
) -> bool:
    user_id = message.from_user.id
    if user_id in _boot_ids(boot_notice):
        return True
    allowed_state = await allowed.get(user_id)
    if allowed_state is True:
        return True
    if allowed_state is False:
        return False
    if await pending.get(user_id):
        return False
    await pending.set(user_id, True)
    await _send_requests(message, bot, boot_notice)
    return False


async def _send_requests(message: Message, bot: Bot, boot_notice: str) -> None:
    user = message.from_user
    text = hlink(PERM_REQUEST_MSG, f"tg://user?id={user.id}")
    for notice_id in _boot_ids(boot_notice):
        if notice_id == user.id:
            continue
        try:
            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=PERM_ALLOW_BTN,
                            callback_data=f"perm:allow|{user.id}|0",
                            style="primary",
                        ),
                        InlineKeyboardButton(
                            text=PERM_DENY_BTN,
                            callback_data=f"perm:deny|{user.id}|0",
                            style="danger",
                        ),
                    ]
                ]
            )
            await bot.send_message(
                notice_id,
                text,
                parse_mode="HTML",
                reply_markup=markup,
            )
        except Exception as exc:
            log.warning("perm request to %s failed: %s", notice_id, exc)


async def handle_perm_callback(
    callback: CallbackQuery,
    field: str,
    target_id: int,
    allowed: AllowedStorage,
    pending: PendingStorage,
    boot_notice: str,
) -> None:
    user_id = callback.from_user.id
    if user_id not in _boot_ids(boot_notice):
        await callback.answer(MODE_DENIED, show_alert=True)
        return
    if field == "allow":
        await allowed.set(target_id, True)
        await pending.set(target_id, False)
        new_text = PERM_ALLOWED_MSG
    else:
        await allowed.set(target_id, False)
        await pending.set(target_id, False)
        new_text = PERM_DENIED_MSG
    await callback.message.edit_text(
        new_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[]),
    )
    await callback.answer()
