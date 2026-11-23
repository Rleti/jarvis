"""Кодовая фраза на русском без обучения модели.

В тишине только считается громкость микрофона (почти ноль нагрузки). Когда кто-то говорит,
короткий отрезок речи прогоняется через Whisper и в тексте ищется «привет, Джарвис».
Всё, что сказано после кодовой фразы, сразу считается командой.
"""
import logging
import re

import numpy as np

import config
from audio import CHUNK, SAMPLE_RATE

log = logging.getLogger("jarvis.wake")

# Whisper может услышать «Джарвис», «Жарвис», «Джервис», «Jarvis» — ловим всё похожее
JARVIS = r"(?:(?:дж|ж|ч)[ауэея]рв[иыэе]с\w*|jarvis)"
GREETING = r"(?:привет|превет|прив)\w*"
CHUNK_S = CHUNK / SAMPLE_RATE


def find_phrase(text: str):
    """Возвращает текст после кодовой фразы ('' если команды нет) или None, если фразы нет."""
    low = text.lower().replace("ё", "е")
    pattern = GREETING + r"[\s,.!?-]*" + JARVIS if config.WAKE_REQUIRE_GREETING else JARVIS
    m = re.search(pattern, low)
    if not m:
        return None
    return text[m.end():].strip(" ,.!?-—")


class PhraseWake:
    def __init__(self, stt):
        self.stt = stt
        self.floor = None      # уровень фонового шума, подстраивается сам
        self.pre = []          # 0,3 с до начала речи, чтобы не отрезать начало
        self.reset()

    def reset(self):
        self.buf, self.active, self.silent = [], False, 0.0

    def feed(self, chunk):
        """Кормим кадрами по 80 мс. Возвращает строку (возможно пустую), если услышали фразу, иначе None."""
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
        if self.floor is None:
            self.floor = rms

        if not self.active:
            k = 0.05 if rms < self.floor * 3 else 0.002   # к тишине — быстро, к шуму — медленно
            self.floor = (1 - k) * self.floor + k * rms
            self.pre = (self.pre + [chunk])[-4:]
            if rms > max(config.WAKE_MIN_LEVEL, self.floor * 3):
                self.active, self.buf, self.silent = True, list(self.pre), 0.0
            return None

        self.buf.append(chunk)
        if rms > max(config.WAKE_MIN_LEVEL * 0.8, self.floor * 2.5):
            self.silent = 0.0
        else:
            self.silent += CHUNK_S

        duration = len(self.buf) * CHUNK_S
        if self.silent < config.WAKE_SILENCE_SECONDS and duration < config.WAKE_MAX_SECONDS:
            return None

        audio = np.concatenate(self.buf).astype(np.float32) / 32768.0
        self.reset()
        if duration < 0.6:          # щелчок, кашель
            return None
        text = self.stt.transcribe(audio)
        log.debug("Слышу: %s", text)
        return find_phrase(text) if text else None
