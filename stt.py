"""Распознавание речи через faster-whisper. Если видеокарта не завелась — автоматически уходит на CPU."""
import gc
import glob
import threading
import logging
import os
import sys

import config

log = logging.getLogger("jarvis.stt")


def _add_cuda_dlls():
    """Подключает DLL из pip-пакетов nvidia-cublas/cudnn, чтобы не ставить CUDA Toolkit вручную."""
    if os.name != "nt":
        return
    for sp in sys.path:
        for d in glob.glob(os.path.join(sp, "nvidia", "*", "bin")):
            try:
                os.add_dll_directory(d)
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            except OSError:
                pass


class STT:
    def __init__(self):
        self.lock = threading.Lock()
        self.device = config.WHISPER_DEVICE
        self.gpu_ok = self.device != "cpu"
        self.model = None

    def _ensure_loaded(self):
        if self.model is not None:
            return
        if self.device == "cpu" and config.WHISPER_DEVICE != "cpu":
            self._fallback_cpu()
            return
        _add_cuda_dlls()
        try:
            self._load(config.WHISPER_MODEL, self.device, config.WHISPER_COMPUTE)
        except Exception as e:
            if self.device == "cpu":
                raise
            log.warning("Whisper на %s не запустился (%s), перехожу на CPU", self.device, e)
            self.gpu_ok = False
            self._fallback_cpu()

    def _load(self, name, device, compute):
        from faster_whisper import WhisperModel
        from huggingface_hub.errors import LocalEntryNotFoundError
        try:
            self.model = WhisperModel(name, device=device, compute_type=compute, local_files_only=True)
        except LocalEntryNotFoundError:
            self.model = WhisperModel(name, device=device, compute_type=compute)
        self.device = device
        log.info("Whisper: %s на %s", name, device)

    def _fallback_cpu(self):
        self._load(config.WHISPER_CPU_MODEL, "cpu", "int8")

    def _run(self, audio):
        segments, _ = self.model.transcribe(
            audio, language=config.LANGUAGE, beam_size=1, vad_filter=True,
        )
        return " ".join(s.text.strip() for s in segments).strip()

    def set_gpu(self, on: bool):
        """Игровой режим: перенести Whisper на процессор (освободить видеопамять) и обратно."""
        with self.lock:
            if self.model is None:
                self.device = config.WHISPER_DEVICE if on and self.gpu_ok else "cpu"
                return
            if on and self.device == "cpu" and self.gpu_ok:
                try:
                    self._load(config.WHISPER_MODEL, config.WHISPER_DEVICE, config.WHISPER_COMPUTE)
                except Exception:
                    log.exception("Не удалось вернуть Whisper на видеокарту")
            elif not on and self.device != "cpu":
                self.model = None
                self.device = "cpu"
                gc.collect()
                self._fallback_cpu()

    def warmup(self):
        """Один прогон на тихом шуме: на RTX 50 первый запуск компилирует ядра CUDA (это и есть «долгий первый ответ»)."""
        import numpy as np
        noise = (np.random.default_rng(0).standard_normal(16000 * 2) * 0.003).astype(np.float32)
        with self.lock:
            self._ensure_loaded()
            try:
                segs, _ = self.model.transcribe(noise, language=config.LANGUAGE, beam_size=1, vad_filter=False)
                list(segs)
            except Exception as e:
                if self.device != "cpu":
                    log.warning("Whisper на GPU упал при прогреве (%s), перехожу на CPU", e)
                    self.gpu_ok = False
                    self._fallback_cpu()

    def transcribe(self, audio) -> str:
        with self.lock:
            self._ensure_loaded()
            return self._transcribe(audio)

    def _transcribe(self, audio) -> str:
        try:
            return self._run(audio)
        except Exception as e:
            if self.device == "cpu":
                raise
            self.gpu_ok = False
            # частый случай: модель загрузилась, но cuDNN/cuBLAS падает на первом распознавании
            log.warning("Ошибка распознавания на GPU (%s), перехожу на CPU", e)
            self._fallback_cpu()
            return self._run(audio)
