import logging

import redis.asyncio as aioredis
from aiogram.fsm.storage.redis import RedisStorage

from cAsh import (
    CACHE_PREFIX,
    FILE_ID_TTL,
    AdtStorage,
    ButtonCycleStorage,
    LangCodeStorage,
    LangStorage,
    ModeStorage,
    RedisBase,
    ReplyCounter,
    _hash_key,
    _parse_bool,
    _ser_bool,
)

log = logging.getLogger("voicebot")


class AnimationSettings(RedisBase):
    DEFAULT = {
        "enabled": False,
        "landscape": False,
        "portrait": False,
        "flip_left": False,
        "flip_right": False,
        "double_rotate": False,
        "crop_ratio": "none",
        "crop_type": "none",
    }

    async def get(self, mode_key: str) -> dict:
        value = await self._get(CACHE_PREFIX + f"animation:{mode_key}")
        if not value:
            return dict(self.DEFAULT)
        parts = value.split(",")
        return {
            "enabled": _parse_bool(parts, 0),
            "landscape": _parse_bool(parts, 1),
            "portrait": _parse_bool(parts, 2),
            "flip_left": _parse_bool(parts, 3),
            "flip_right": _parse_bool(parts, 4),
            "double_rotate": _parse_bool(parts, 5),
            "crop_ratio": parts[6] if len(parts) > 6 else "none",
            "crop_type": parts[7] if len(parts) > 7 else "none",
        }

    async def set(self, mode_key: str, settings: dict) -> None:
        value = ",".join(
            [
                _ser_bool(settings["enabled"]),
                _ser_bool(settings["landscape"]),
                _ser_bool(settings["portrait"]),
                _ser_bool(settings["flip_left"]),
                _ser_bool(settings["flip_right"]),
                _ser_bool(settings.get("double_rotate")),
                settings.get("crop_ratio", "none"),
                settings.get("crop_type", "none"),
            ]
        )
        await self._set(CACHE_PREFIX + f"animation:{mode_key}", value)


class NoteSettings(RedisBase):
    DEFAULT = {
        "enabled": False,
        "landscape": False,
        "portrait": False,
        "flip_left": False,
        "flip_right": False,
        "double_rotate": False,
        "crop_align": "center",
        "muted": False,
    }

    async def get(self, mode_key: str) -> dict:
        value = await self._get(CACHE_PREFIX + f"note:{mode_key}")
        if not value:
            return dict(self.DEFAULT)
        parts = value.split(",")
        return {
            "enabled": _parse_bool(parts, 0),
            "landscape": _parse_bool(parts, 1),
            "portrait": _parse_bool(parts, 2),
            "flip_left": _parse_bool(parts, 3),
            "flip_right": _parse_bool(parts, 4),
            "double_rotate": _parse_bool(parts, 5),
            "crop_align": parts[6] if len(parts) > 6 else "center",
            "muted": _parse_bool(parts, 7),
        }

    async def set(self, mode_key: str, settings: dict) -> None:
        value = ",".join(
            [
                _ser_bool(settings["enabled"]),
                _ser_bool(settings["landscape"]),
                _ser_bool(settings["portrait"]),
                _ser_bool(settings["flip_left"]),
                _ser_bool(settings["flip_right"]),
                _ser_bool(settings.get("double_rotate")),
                settings.get("crop_align", "center"),
                _ser_bool(settings.get("muted")),
            ]
        )
        await self._set(CACHE_PREFIX + f"note:{mode_key}", value)


class DefaultSettings(RedisBase):
    async def get(self, mode_key: str) -> dict:
        value = await self._get(CACHE_PREFIX + f"default:{mode_key}")
        if not value:
            return {"enabled": False, "send_as": "document"}
        parts = value.split(",")
        return {
            "enabled": _parse_bool(parts, 0),
            "send_as": (
                parts[1]
                if len(parts) > 1 and parts[1] in ("document", "video")
                else "document"
            ),
        }

    async def set(self, mode_key: str, settings: dict) -> None:
        value = ",".join(
            [
                _ser_bool(settings["enabled"]),
                "video" if settings.get("send_as") == "video" else "document",
            ]
        )
        await self._set(CACHE_PREFIX + f"default:{mode_key}", value)


class FileIdCache(RedisBase):
    @staticmethod
    def _signature(mode: str, settings: dict | None) -> str:
        if mode == "animation" and settings:
            parts = [
                _ser_bool(settings.get(key))
                for key in (
                    "landscape",
                    "portrait",
                    "flip_left",
                    "flip_right",
                    "double_rotate",
                )
            ]
            parts.append(settings.get("crop_ratio", "none"))
            parts.append(settings.get("crop_type", "none"))
            return f"animation:{'_'.join(parts)}"
        if mode == "note" and settings:
            parts = [
                _ser_bool(settings.get(key))
                for key in (
                    "landscape",
                    "portrait",
                    "flip_left",
                    "flip_right",
                    "double_rotate",
                )
            ]
            parts.append(settings.get("crop_align", "center"))
            parts.append(_ser_bool(settings.get("muted")))
            return f"note:{'_'.join(parts)}"
        if mode == "default" and settings:
            return f"default:{settings.get('send_as', 'document')}"
        return mode

    @staticmethod
    def key(url: str, mode: str, settings: dict | None = None) -> str:
        signature = FileIdCache._signature(mode, settings)
        return CACHE_PREFIX + "file_id:" + _hash_key(f"{url}|{signature}")

    async def get(
        self, url: str, mode: str, settings: dict | None = None
    ) -> str | None:
        return await self._get(self.key(url, mode, settings))

    async def set(
        self, url: str, mode: str, file_id: str, settings: dict | None = None
    ) -> None:
        await self._set(self.key(url, mode, settings), file_id, ttl=FILE_ID_TTL)

    async def delete(self, url: str, mode: str, settings: dict | None = None) -> None:
        await self._del(self.key(url, mode, settings))

    @staticmethod
    def source_key(source_file_id: str, action: str, detail: str) -> str:
        return CACHE_PREFIX + "src_id:" + _hash_key(
            f"{source_file_id}|{action}|{detail}"
        )

    async def get_by_source(
        self, source_file_id: str, action: str, detail: str
    ) -> str | None:
        return await self._get(self.source_key(source_file_id, action, detail))

    async def set_by_source(
        self, source_file_id: str, action: str, detail: str, file_id: str
    ) -> None:
        await self._set(
            self.source_key(source_file_id, action, detail), file_id, ttl=FILE_ID_TTL
        )

    async def delete_by_source(
        self, source_file_id: str, action: str, detail: str
    ) -> None:
        await self._del(self.source_key(source_file_id, action, detail))


def _redis_client(url: str | None) -> aioredis.Redis | None:
    if not url:
        return None
    return aioredis.from_url(url, health_check_interval=48, socket_keepalive=True)


def build_storage(url: str | None) -> RedisStorage | None:
    return (
        RedisStorage.from_url(url, health_check_interval=48, socket_keepalive=True)
        if url
        else None
    )


def build_counter(url: str | None) -> ReplyCounter:
    return ReplyCounter(_redis_client(url))


def build_modes(url: str | None) -> ModeStorage:
    return ModeStorage(_redis_client(url))


def build_adt(url: str | None) -> AdtStorage:
    return AdtStorage(_redis_client(url))


def build_lang(url: str | None) -> LangStorage:
    return LangStorage(_redis_client(url))


def build_lang_code(url: str | None) -> LangCodeStorage:
    return LangCodeStorage(_redis_client(url))


def build_btn_cycle(url: str | None) -> ButtonCycleStorage:
    return ButtonCycleStorage(_redis_client(url))


def build_animation(url: str | None) -> AnimationSettings:
    return AnimationSettings(_redis_client(url))


def build_note(url: str | None) -> NoteSettings:
    return NoteSettings(_redis_client(url))


def build_default(url: str | None) -> DefaultSettings:
    return DefaultSettings(_redis_client(url))


def build_file_cache(url: str | None) -> FileIdCache:
    return FileIdCache(_redis_client(url))