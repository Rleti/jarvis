"""Микрофон: один постоянный поток, из которого читают и детектор кодового слова, и запись команды."""
import logging
import queue

import numpy as np
import sounddevice as sd

log = logging.getLogger("jarvis.audio")

SAMPLE_RATE = 16000
CHUNK = 1280  # 80 мс — размер кадра, который ждёт openWakeWord


def input_devices():
    """[(номер, название)] всех микрофонов."""
    return [(i, d["name"]) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]


def pick_device(wanted):
    """MIC_DEVICE: '' — микрофон Windows по умолчанию; число — номер; текст — часть названия."""
    if wanted in ("", None):
        return None
    if isinstance(wanted, int) or str(wanted).isdigit():
        return int(wanted)
    for i, name in input_devices():
        if str(wanted).lower() in name.lower():
            return i
    log.warning("Микрофон «%s» не найден, беру микрофон по умолчанию", wanted)
    return None


class Mic:
    def __init__(self, device=None):
        self.q: queue.Queue = queue.Queue()
        self.device = pick_device(device)
        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16",
            blocksize=CHUNK, callback=self._callback, device=self.device,
        )
        try:
            name = sd.query_devices(self.device if self.device is not None else sd.default.device[0])["name"]
        except Exception:
            name = "?"
        log.info("Микрофон: %s", name)

    def log_devices(self):
        log.info("Доступные микрофоны (номер — название, впиши в MIC_DEVICE в config.py):")
        for i, name in input_devices():
            log.info("  %d — %s", i, name)

    def _callback(self, indata, frames, time_info, status):
        self.q.put(indata[:, 0].copy())

    def start(self):
        self.stream.start()

    def stop(self):
        self.stream.stop()
        self.stream.close()

    def read(self, timeout=None) -> np.ndarray:
        return self.q.get(timeout=timeout)

    def clear(self):
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                return

    def record_command(self, silence_s=1.0, max_s=12.0, start_timeout=5.0):
        """Пишет фразу до паузы. Возвращает float32-массив или None, если ничего не сказали."""
        self.clear()
        chunk_s = CHUNK / SAMPLE_RATE
        frames, noise = [], []
        started, silent, waited, total = False, 0.0, 0.0, 0.0

        while total < max_s:
            try:
                c = self.read(timeout=1.0)
            except queue.Empty:
                continue
            frames.append(c)
            total += chunk_s
            rms = float(np.sqrt(np.mean(c.astype(np.float32) ** 2)))

            if len(noise) < 4:          # первые 0,3 с — замер фонового шума
                noise.append(rms)
                continue
            threshold = max(400.0, 2.5 * float(np.median(noise)))

            if rms > threshold:
                started, silent = True, 0.0
            elif started:
                silent += chunk_s
                if silent >= silence_s:
                    break
            else:
                waited += chunk_s
                if waited >= start_timeout:
                    return None

        if not started:
            return None
        return np.concatenate(frames).astype(np.float32) / 32768.0
