import re
from pathlib import Path

from aiogram import Bot
from aiogram.types import (
    FSInputFile,
    InputMediaDocument,
    Message,
    ReplyParameters,
)

import CAsh
import Reply
import bToN


UPPER_EXCEPTIONS = set(
    "ATFGUJNML"
)


def clean_name(value):
    value = value or ""

    value = re.sub(
        r"[^\w\s]",
        "",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    result = []

    for char in value:
        if char.isascii() and char.isalpha():
            if char.upper() in UPPER_EXCEPTIONS:
                result.append(char.upper())
            else:
                result.append(char.lower())
        else:
            result.append(char)

    return "".join(result)


def get_publisher(info):
    return clean_name(
        info.get("uploader")
        or info.get("channel")
        or ""
    )


def get_title(info):
    return clean_name(
        info.get("title")
        or info.get("id")
        or "media"
    )


def build_filename(
    info,
    extension,
):
    publisher = get_publisher(info)
    title = get_title(info)

    if publisher and title:
        name = (
            f"{publisher} - {title}"
        )
    elif publisher:
        name = publisher
    else:
        name = title or "media"

    return f"{name}.{extension}"


def unique_filename(
    directory,
    filename,
):
    path = Path(directory) / filename

    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    number = 2

    while True:
        candidate = (
            Path(directory)
            / f"{stem} {number}{suffix}"
        )

        if not candidate.exists():
            return candidate

        number += 1


def reply_parameters(message):
    return ReplyParameters(
        message_id=message.message_id
    )


async def send_status_message(message):
    if not Reply.DOWNLOAD_STARTED:
        return None

    return await message.reply(
        Reply.DOWNLOAD_STARTED
    )


async def delete_status_message(
    status_message,
):
    if status_message is None:
        return

    try:
        await status_message.delete()
    except Exception:
        pass


async def show_failure(
    status_message,
    message,
):
    if status_message is not None:
        if Reply.DOWNLOAD_FAILED:
            try:
                await status_message.edit_text(
                    Reply.DOWNLOAD_FAILED
                )
            except Exception:
                pass

        return

    if Reply.DOWNLOAD_FAILED:
        await message.reply(
            Reply.DOWNLOAD_FAILED
        )


async def send_documents(
    bot: Bot,
    message: Message,
    items,
):
    for start in range(
        0,
        len(items),
        bToN.ALBUM_BATCH_SIZE,
    ):
        batch = items[
            start:start
            + bToN.ALBUM_BATCH_SIZE
        ]

        if len(batch) == 1:
            await _send_document(
                bot,
                message,
                batch[0],
            )
        else:
            await _send_document_album(
                bot,
                message,
                batch,
            )


async def _send_document_album(
    bot,
    message,
    items,
):
    media = []

    for item in items:
        if item.file_id:
            media.append(
                InputMediaDocument(
                    media=item.file_id
                )
            )
        else:
            media.append(
                InputMediaDocument(
                    media=FSInputFile(
                        item.file_path,
                        filename=item.filename,
                    )
                )
            )

    result = await bot.send_media_group(
        chat_id=message.chat.id,
        media=media,
        reply_parameters=reply_parameters(
            message
        ),
    )

    for sent, item in zip(
        result,
        items,
    ):
        if sent.document:
            item.file_id = (
                sent.document.file_id
            )

            await CAsh.save_file_id(
                item.cache_key,
                item.file_id,
            )


async def _send_document(
    bot,
    message,
    item,
):
    if item.file_id:
        result = await bot.send_document(
            chat_id=message.chat.id,
            document=item.file_id,
            reply_parameters=reply_parameters(
                message
            ),
        )
    else:
        result = await bot.send_document(
            chat_id=message.chat.id,
            document=FSInputFile(
                item.file_path,
                filename=item.filename,
            ),
            reply_parameters=reply_parameters(
                message
            ),
            disable_content_type_detection=True,
        )

    if result.document:
        item.file_id = (
            result.document.file_id
        )

        await CAsh.save_file_id(
            item.cache_key,
            item.file_id,
        )


async def send_voices(
    bot,
    message,
    items,
):
    for item in items:
        await _send_voice(
            bot,
            message,
            item,
        )


async def _send_voice(
    bot,
    message,
    item,
):
    if item.file_id:
        result = await bot.send_voice(
            chat_id=message.chat.id,
            voice=item.file_id,
            reply_parameters=reply_parameters(
                message
            ),
        )
    else:
        result = await bot.send_voice(
            chat_id=message.chat.id,
            voice=FSInputFile(
                item.file_path,
                filename=item.filename,
            ),
            reply_parameters=reply_parameters(
                message
            ),
        )

    if result.voice:
        item.file_id = (
            result.voice.file_id
        )

        await CAsh.save_file_id(
            item.cache_key,
            item.file_id,
        )