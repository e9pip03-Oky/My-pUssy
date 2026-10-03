import os
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from Reply import BTN_VOICE, BTN_NORMAL, BTN_NAMES

class ButtonManager:
    def __init__(self):
        self.btn_name_idx = 0
        self.btn_style_idx = 0
        self.takeoff_id_idx = 0
        self.styles = ["danger", "success", "primary"]

    def _get_takeoff_ids(self) -> list:
        raw_env = os.getenv("boT_TAkeoFF", "")
        if not raw_env:
            return []
        return [id_str.strip() for id_str in raw_env.split("/") if id_str.strip()]

    def get_edit_keyboard(self, current_mode: str) -> InlineKeyboardMarkup:
        if current_mode == "voice":
            voice_style = "success"
            normal_style = "danger"
        else:
            voice_style = "danger"
            normal_style = "success"

        btn_voice = InlineKeyboardButton(
            text=BTN_VOICE,
            callback_data="mode_voice",
            style=voice_style
        )
        btn_normal = InlineKeyboardButton(
            text=BTN_NORMAL,
            callback_data="mode_normal",
            style=normal_style
        )

        return InlineKeyboardMarkup(inline_keyboard=[[btn_voice], [btn_normal]])

    def get_rotating_button(self) -> InlineKeyboardMarkup:
        takeoff_ids = self._get_takeoff_ids()
        if not takeoff_ids:
            return None

        target_id = takeoff_ids[self.takeoff_id_idx % len(takeoff_ids)]
        btn_name = BTN_NAMES[self.btn_name_idx % len(BTN_NAMES)]
        btn_style = self.styles[self.btn_style_idx % len(self.styles)]

        self.takeoff_id_idx = (self.takeoff_id_idx + 1) % len(takeoff_ids)
        self.btn_name_idx = (self.btn_name_idx + 1) % len(BTN_NAMES)
        self.btn_style_idx = (self.btn_style_idx + 1) % len(self.styles)

        user_url = f"tg://user?id={target_id}"
        btn = InlineKeyboardButton(
            text=btn_name,
            url=user_url,
            style=btn_style
        )

        return InlineKeyboardMarkup(inline_keyboard=[[btn]])

btn_mgr = ButtonManager()
