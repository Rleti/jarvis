"""Push-to-talk: держишь клавишу (или боковую кнопку мыши) — говоришь, отпустил — команда выполняется.

Состояние клавиши опрашивается напрямую у Windows (GetAsyncKeyState) — без перехвата клавиатуры,
поэтому работает в любом окне, в том числе поверх игр, и не требует сторонних библиотек.
"""
import ctypes
import logging

log = logging.getLogger("jarvis.ptt")

VK = {
    "ctrl_r": 0xA3, "ctrl_l": 0xA2, "alt_r": 0xA5, "alt_l": 0xA4,
    "shift_r": 0xA1, "shift_l": 0xA0, "caps_lock": 0x14, "tab": 0x09,
    "mouse_x1": 0x05, "mouse_x2": 0x06, "mouse_middle": 0x04,
    "insert": 0x2D, "home": 0x24, "end": 0x23, "page_up": 0x21, "page_down": 0x22,
    "pause": 0x13, "scroll_lock": 0x91,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},          # f1..f12
    **{f"num{i}": 0x60 + i for i in range(10)},           # цифры на цифровом блоке
}


def vk_code(name: str) -> int:
    name = name.strip().lower()
    if name in VK:
        return VK[name]
    if len(name) == 1 and name.isalnum():
        return ord(name.upper())                           # буквы и цифры
    raise ValueError(f"Неизвестная клавиша PTT_KEY = {name!r}")


class PushToTalk:
    def __init__(self, key_name: str):
        self.vk = vk_code(key_name)
        self._get = ctypes.windll.user32.GetAsyncKeyState
        log.info("Push-to-talk: держи %s", key_name)

    def is_down(self) -> bool:
        return bool(self._get(self.vk) & 0x8000)
