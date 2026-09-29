import asyncio
from collections import defaultdict, deque
from pathlib import Path
from typing import Awaitable, Callable

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaDocument,
    Message,
    ReactionTypeEmoji,
)

import CAsh
import NAMe
import Reply
import yTFMe


router = Router()

BOT_TAKEOFF = ""

REACTIONS = (
    "😭",
    "🥰",
    "❤️",
    "😘",
    "🤣",
)

REACTION_DELAYS = (
    2.4,
    4.2,
    4.8,
    3.6,
    3.9,
    2.2,
)

DEVELOPER_STYLES = (
    "danger",
    "success",
    "primary",
)

reaction_delay_index = 0
reaction_emoji_index = 0

developer_index = 0
developer_label_index = 0
developer_style_index = 0

reaction_lock = asyncio.Lock()
developer_lock = asyncio.Lock()


class DownloadQueue:
    def __init__(
        self,
        limit: int = 3,
        waiting_limit: int = 3,
    ) -> None:
        self.limit = limit
        self.waiting_limit = waiting_limit
        self.running = 0
        self.waiting: deque[
            tuple[
                Callable[[], Awaitable[None]],
                asyncio.Future[None],
            ]
        ] = deque()
        self.lock = asyncio.Lock()

    async def submit(
        self,
        job: Callable[[], Awaitable[None]],
    ) -> bool:
        async with self.lock:
            if self.running < self.limit:
                self.running += 1
                run_now = True
            elif len(self.waiting) < self.waiting_limit:
                future = (
                    asyncio.get_running_loop()
                    .create_future()
                )
                self.waiting.append(
                    (
                        job,
                        future,
                    )
                )
                run_now = False
            else:
                return False

        if run_now:
            asyncio.create_task(
                self._run(job)
            )

        return True

    async def _run(
        self,
        job: Callable[[], Awaitable[None]],
    ) -> None:
        try:
            await job()
        finally:
            await self._next()

    async def _next(self) -> None:
        async with self.lock:
            if not self.waiting:
                self.running -= 1
                return

            job, future = (
                self.waiting.popleft()
            )

        if not future.done():
            future.set_result(None)

        asyncio.create_task(
            self._run(job)
        )


queues: defaultdict[
    str,
    DownloadQueue,
] = defaultdict(
    DownloadQueue
)


def configure(
    bot_takeoff: str | None,
) -> None:
    global BOT_TAKEOFF
    BOT_TAKEOFF = bot_takeoff or ""


def context_key(
    message: Message,
) -> str:
    if (
        message.chat.type
        == ChatType.PRIVATE
    ):
        return (
            f"private:{message.chat.id}"
        )

    if (
        message.chat.type
        == ChatType.SUPERGROUP
        and message.message_thread_id
    ):
        return (
            f"topic:{message.chat.id}:"
            f"{message.message_thread_id}"
        )

    return f"chat:{message.chat.id}"


def is_group(
    message: Message,
) -> bool:
    return message.chat.type in {
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    }


async def is_admin(
    message: Message,
) -> bool:
    if not message.from_user:
        return False

    if (
        message.chat.type
        == ChatType.PRIVATE
    ):
        return True

    member = (
        await message.bot.get_chat_member(
            message.chat.id,
            message.from_user.id,
        )
    )

    return member.status in {
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
    }


async def next_reaction_values() -> tuple[
    float,
    str,
]:
    global reaction_delay_index
    global reaction_emoji_index

    async with reaction_lock:
        delay = REACTION_DELAYS[
            reaction_delay_index
        ]

        emoji = REACTIONS[
            reaction_emoji_index
        ]

        reaction_delay_index = (
            reaction_delay_index + 1
        ) % len(REACTION_DELAYS)

        reaction_emoji_index = (
            reaction_emoji_index + 1
        ) % len(REACTIONS)

        return delay, emoji


async def react_to_message(
    message: Message,
) -> None:
    delay, emoji = (
        await next_reaction_values()
    )

    await asyncio.sleep(delay)

    try:
        await message.bot.set_message_reaction(
            chat_id=message.chat.id,
            message_id=message.message_id,
            reaction=[
                ReactionTypeEmoji(
                    emoji=emoji
                )
            ],
        )
    except Exception:
        pass


def schedule_reaction(
    message: Message,
) -> None:
    asyncio.create_task(
        react_to_message(message)
    )


def developer_ids() -> list[int]:
    if not BOT_TAKEOFF:
        return []

    result = []

    for item in BOT_TAKEOFF.split("/"):
        item = item.strip()

        if not item:
            continue

        try:
            result.append(int(item))
        except ValueError:
            continue

    return result


async def next_developer_button() -> (
    InlineKeyboardButton | None
):
    global developer_index
    global developer_label_index
    global developer_style_index

    ids = developer_ids()

    if not ids:
        return None

    async with developer_lock:
        user_id = ids[
            developer_index % len(ids)
        ]

        label = Reply.DEVELOPER_LABELS[
            developer_label_index
            % len(Reply.DEVELOPER_LABELS)
        ]

        style = DEVELOPER_STYLES[
            developer_style_index
            % len(DEVELOPER_STYLES)
        ]

        developer_index += 1
        developer_label_index += 1
        developer_style_index += 1

    return InlineKeyboardButton(
        text=label,
        url=f"tg://user?id={user_id}",
        style=style,
    )


async def developer_markup() -> (
    InlineKeyboardMarkup | None
):
    button = (
        await next_developer_button()
    )

    if button is None:
        return None

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button],
        ]
    )


async def send_text(
    message: Message,
    text: str,
) -> Message:
    markup = (
        await developer_markup()
    )

    sent = await message.reply(
        text,
        reply_markup=markup,
    )

    schedule_reaction(sent)

    return sent


def mode_keyboard(
    mode: str,
) -> InlineKeyboardMarkup:
    if mode == "normal":
        voice_style = "danger"
        normal_style = "success"
    else:
        voice_style = "success"
        normal_style = "danger"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=Reply.VOICE_BUTTON,
                    callback_data="mode_toggle",
                    style=voice_style,
                ),
                InlineKeyboardButton(
                    text=Reply.NORMAL_BUTTON,
                    callback_data="mode_toggle",
                    style=normal_style,
                ),
            ]
        ]
    )


async def show_edit_menu(
    message: Message,
) -> None:
    key = context_key(message)
    mode = CAsh.get_mode(key)

    sent = await message.reply(
        Reply.EDIT_MESSAGE,
        reply_markup=mode_keyboard(
            mode
        ),
    )

    schedule_reaction(sent)


@router.callback_query(
    F.data == "mode_toggle"
)
async def mode_toggle(
    callback: CallbackQuery,
) -> None:
    if not callback.message:
        await callback.answer()
        return

    message = callback.message

    allowed = False

    if (
        message.chat.type
        == ChatType.PRIVATE
    ):
        allowed = True
    else:
        member = (
            await message.bot.get_chat_member(
                message.chat.id,
                callback.from_user.id,
            )
        )

        allowed = member.status in {
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
        }

    if not allowed:
        await callback.answer(
            Reply.EDIT_PERMISSION_DENIED,
            show_alert=True,
        )
        return

    key = context_key(message)
    new_mode = CAsh.toggle_mode(key)

    try:
        await message.edit_reply_markup(
            reply_markup=mode_keyboard(
                new_mode
            )
        )
    except TelegramBadRequest:
        pass

    await callback.answer()


async def alternating_reply(
    message: Message,
) -> None:
    if not message.from_user:
        return

    text = CAsh.get_next_reply(
        message.from_user.id
    )

    await send_text(
        message,
        text,
    )


def cache_key(
    url: str,
    mode: str,
    item_id: str | None = None,
) -> str:
    identity = item_id or url
    return f"{mode}:{identity}"


async def send_voice_file(
    message: Message,
    file_path: Path,
    key: str,
) -> None:
    cached_id = CAsh.get_file_id(key)

    if cached_id:
        sent = await message.reply_voice(
            cached_id
        )
    else:
        sent = await message.reply_voice(
            FSInputFile(file_path)
        )

        if sent.voice:
            CAsh.set_file_id(
                key,
                sent.voice.file_id,
            )

    schedule_reaction(sent)


async def send_normal_files(
    message: Message,
    files: list[Path],
    prefix: str,
) -> None:
    media = []

    for index, file_path in enumerate(
        files
    ):
        key = cache_key(
            prefix,
            "normal",
            str(index),
        )

        cached_id = CAsh.get_file_id(key)

        if cached_id:
            media.append(
                InputMediaDocument(
                    media=cached_id
                )
            )
        else:
            media.append(
                InputMediaDocument(
                    media=FSInputFile(
                        file_path
                    )
                )
            )

    for start in range(
        0,
        len(media),
        10,
    ):
        batch = media[
            start:start + 10
        ]

        sent_messages = (
            await message.bot.send_media_group(
                chat_id=message.chat.id,
                media=batch,
                reply_to_message_id=(
                    message.message_id
                ),
            )
        )

        for index, sent in enumerate(
            sent_messages
        ):
            schedule_reaction(sent)

            if sent.document:
                key = cache_key(
                    prefix,
                    "normal",
                    str(
                        start + index
                    ),
                )

                CAsh.set_file_id(
                    key,
                    sent.document.file_id,
                )


async def run_download(
    message: Message,
    url: str,
) -> None:
    mode = CAsh.get_mode(
        context_key(message)
    )

    folder = NAMe.context_folder(
        message.chat.id
    )

    try:
        await send_text(
            message,
            Reply.DOWNLOAD_STARTING,
        )

        info = await yTFMe.download(
            url,
            folder,
            mode,
        )

        entries = info.get(
            "entries"
        )

        if entries:
            entries = [
                entry
                for entry in entries
                if entry
            ]
        else:
            entries = [info]

        files = (
            yTFMe.find_downloaded_files(
                folder
            )
        )

        if not files:
            raise RuntimeError(
                "No downloaded files"
            )

        if mode == "voice":
            for index, entry in enumerate(
                entries
            ):
                entry_id = str(
                    entry.get(
                        "id",
                        index,
                    )
                )

                source_file = None

                for file_path in files:
                    if entry_id in file_path.stem:
                        source_file = file_path
                        break

                if source_file is None:
                    source_file = files[
                        min(
                            index,
                            len(files) - 1,
                        )
                    ]

                output_file = (
                    folder
                    / f"{source_file.stem}.ogg"
                )

                await yTFMe.convert_to_voice(
                    source_file,
                    output_file,
                )

                key = cache_key(
                    url,
                    "voice",
                    entry_id,
                )

                await send_voice_file(
                    message,
                    output_file,
                    key,
                )

        else:
            await send_normal_files(
                message,
                files,
                url,
            )

    except Exception:
        await send_text(
            message,
            Reply.DOWNLOAD_FAILURE,
        )

    finally:
        for file_path in (
            yTFMe.find_downloaded_files(
                folder
            )
        ):
            NAMe.cleanup_file(
                file_path
            )


async def handle_download(
    message: Message,
    url: str,
) -> None:
    key = context_key(message)

    await queues[key].submit(
        lambda: run_download(
            message,
            url,
        )
    )


@router.message()
async def all_messages(
    message: Message,
) -> None:
    if not message.from_user:
        return

    text = (
        message.text
        or message.caption
        or ""
    )

    if (
        message.chat.type
        == ChatType.PRIVATE
    ):
        schedule_reaction(message)

    elif (
        is_group(message)
        and text == Reply.BOT_WORD
    ):
        schedule_reaction(message)

    if text == Reply.EDIT_COMMAND:
        if (
            message.chat.type
            == ChatType.PRIVATE
        ):
            await show_edit_menu(message)
            return

        if await is_admin(message):
            await show_edit_menu(message)

        return

    if text == Reply.BOT_WORD:
        await alternating_reply(message)
        return

    allowed_urls = NAMe.get_allowed_urls(
        text
    )

    if allowed_urls:
        for url in allowed_urls:
            await handle_download(
                message,
                url,
            )

        return

    if (
        message.chat.type
        == ChatType.PRIVATE
    ):
        await alternating_reply(message)


async def send_startup_messages(
    bot,
) -> None:
    for chat_id in developer_ids():
        markup = (
            await developer_markup()
        )

        sent = await bot.send_message(
            chat_id=chat_id,
            text=Reply.STARTUP_MESSAGE,
            reply_markup=markup,
        )

        schedule_reaction(sent)