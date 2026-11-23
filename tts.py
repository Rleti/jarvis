"""Звук реплик: короткие сигналы визуальной новеллы или синтез речи."""
import logging
import os
import re

import numpy as np
import sounddevice as sd

import config

log = logging.getLogger("jarvis.tts")

try:
    from num2words import num2words
except ImportError:
    num2words = None


MOUTH_STEP = 0.06       # шаг липсинка, секунды


def mouth_envelope(audio, sr=None):
    """Громкость голоса по кусочкам 60 мс -> строка '0' (рот закрыт), '1' (приоткрыт), '2' (открыт)."""
    try:
        import numpy as np
        sr = sr or SR
        n = max(1, int(sr * MOUTH_STEP))
        k = len(audio) // n
        if k == 0:
            return ""
        rms = np.sqrt((np.asarray(audio[:k * n], np.float32).reshape(k, n) ** 2).mean(1))
        ref = np.percentile(rms, 90) + 1e-6
        lvl = rms / ref
        return "".join("2" if v > 0.62 else "1" if v > 0.22 else "0" for v in lvl)
    except Exception:
        return ""


def _clean(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\*[^*]{1,80}\*", " ", text)                 # ремарки *затягивается* не читаем
    text = re.sub(r"\([^)]{1,80}\)", " ", text)                 # и (в скобках) тоже
    text = re.sub(r"\.{2,}|…", ",", text)                        # многоточия синтезатор тянет и коверкает
    text = re.sub(r",\s*([.!?])", r"\1", text)
    text = re.sub(r",\s*$", ".", text.strip())
    text = re.sub(r"(\w)(?:-\1)+\b", r"\1", text)               # ну-у-у -> ну
    text = re.sub(r"([а-яёa-z])\1{2,}", r"\1", text, flags=re.I)   # аааа, ммм -> а, м
    text = re.sub(r"\s[—–-]\s", ", ", text)                     # тире -> короткая пауза
    text = re.sub(r"(?i)(?<![\w-])(хм+|м+|кхе(?:-кхе)*|пф+|э+|тьфу)(?![\w-])[,!.]?\s*", "", text)   # звукоподражания
    text = re.sub(r"\s+([.,!?])", r"\1", text)
    text = re.sub(r"^[,\s]+", "", text)
    text = re.sub(r"[*_#`>\[\]~]", "", text)
    text = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]", "", text)   # эмодзи
    text = text.replace("%", " процентов")
    if num2words:
        text = re.sub(r"\d+", lambda m: num2words(int(m.group()), lang="ru"), text)
    return re.sub(r"\s+", " ", text).strip()


def _chunks(text: str, limit: int = 700):
    """Silero не любит длинные тексты — режем по предложениям."""
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?…])\s+", text):
        if len(cur) + len(sent) > limit and cur:
            parts.append(cur)
            cur = ""
        cur = (cur + " " + sent).strip()
    if cur:
        parts.append(cur)
    return parts


SR = 48000


def _blip_audio(text):
    """Темп печати постоянный, пробелы и знаки препинания дают паузы."""
    samples_per_char = max(1, round(SR / max(1, config.BLIP_CHARS_PER_SECOND)))
    tone_length = min(round(SR * 0.034), samples_per_char)
    t = np.arange(tone_length) / SR
    envelope = np.minimum(t / 0.004, 1) * np.minimum((t[-1] - t) / 0.012, 1)
    volume = np.clip(config.BLIP_VOLUME, 0, 1)
    tones = []
    for pitch in (510, 440, 485, 390, 460):
        phase = 2 * np.pi * (pitch * t - 320 * t ** 2)
        tones.append(volume * envelope * (0.82 * np.sin(phase) + 0.18 * np.sin(2 * phase)))

    audio = np.zeros(len(text) * samples_per_char, dtype=np.float32)
    next_blip = 0
    for index, char in enumerate(text):
        if index >= next_blip and char.isalnum():
            start = index * samples_per_char
            audio[start:start + tone_length] = tones[ord(char.lower()[0]) % len(tones)]
            next_blip = index + 2
    return audio


def silero_dir():
    """Папка с кодом Silero в кэше torch hub, если она скачана."""
    path = os.path.join(os.path.expanduser("~"), ".cache", "torch", "hub", "snakers4_silero-models_master")
    return path if os.path.isfile(os.path.join(path, "hubconf.py")) else None


def _speed(a, k):
    """Ускоряет (k>1, голос выше) или замедляет (k<1, голос ниже)."""
    n = int(len(a) / k)
    return np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a)


def _ring(a, freq, mix=1.0):
    """Кольцевая модуляция — металлический «роботный» звук."""
    t = np.arange(len(a)) / SR
    return a * (1 - mix) + a * np.sin(2 * np.pi * freq * t) * mix


def _echo(a, delay_s, decay, repeats=3):
    d = int(delay_s * SR)
    out = np.concatenate([a, np.zeros(d * repeats)])
    for i in range(1, repeats + 1):
        out[d * i: d * i + len(a)] += a * decay ** i
    return out


def _vibrato(a, depth=0.004, freq=5.0):
    """Плавающая высота тона — «пьяный» или «старый магнитофон»."""
    t = np.arange(len(a))
    shift = depth * SR * np.sin(2 * np.pi * freq * t / SR)
    return np.interp(np.clip(t + shift, 0, len(a) - 1), t, a)


def _rasp(a, drive=2.2, grit=0.12, seed=7):
    """Хрипотца: мягкий перегруз + шум, который идёт за громкостью голоса."""
    env = np.convolve(np.abs(a), np.ones(240) / 240, mode="same")
    noise = np.random.default_rng(seed).normal(0, 1, len(a)) * env * grit
    return np.tanh((a + noise) * drive) / np.tanh(drive)


def _eq(a, bands):
    """Эквалайзер через FFT: bands = [(частота Гц, усиление дБ), ...], между точками — плавно."""
    spec = np.fft.rfft(a)
    freqs = np.fft.rfftfreq(len(a), 1 / SR)
    fx, gx = zip(*bands)
    gain_db = np.interp(freqs, fx, gx)
    return np.fft.irfft(spec * 10 ** (gain_db / 20), n=len(a))


def _room(a, wet=0.18):
    """Мягкое короткое пространство — голос звучит «объёмнее», без эха."""
    out = np.concatenate([a, np.zeros(int(0.12 * SR))])
    for delay, k in ((0.019, 1.0), (0.031, 0.8), (0.047, 0.6), (0.071, 0.4), (0.097, 0.25)):
        d = int(delay * SR)
        out[d:d + len(a)] += a * wet * k
    return out


def _velvet(a):
    """Бархат: чуть ниже и медленнее, тёплый низ, мягкий верх, лёгкое пространство."""
    a = _speed(a, 0.95)
    a = _eq(a, [(0, 0), (60, 2), (150, 4), (300, 2.5), (800, 0), (2500, -1.5),
                (4500, -3), (8000, -6), (24000, -9)])
    a = np.tanh(a * 1.3) / np.tanh(1.3)            # едва заметное «ламповое» сглаживание
    return _room(a, 0.16)


EFFECTS = {
    "none":     lambda a: a,
    "velvet":   _velvet,                                               # бархатный, томный
    "smoker":   lambda a: _rasp(_speed(a, 0.88)),                      # прокуренный бас с хрипотцой
    "chipmunk": lambda a: _speed(a, 1.5),                              # бурундук
    "demon":    lambda a: _echo(_speed(a, 0.72), 0.08, 0.4, 2),        # демон из подвала
    "giant":    lambda a: _speed(a, 0.82),                             # здоровяк
    "robot":    lambda a: _echo(_ring(a, 55, 0.7), 0.025, 0.5, 2),     # робот
    "alien":    lambda a: _ring(_speed(a, 1.15), 420, 1.0),            # пришелец
    "drunk":    lambda a: _vibrato(_speed(a, 0.9), 0.006, 3.0),        # подвыпивший
    "cave":     lambda a: _echo(a, 0.22, 0.45, 4),                     # в пещере
}


def apply_effect(a, name):
    out = EFFECTS.get(name, EFFECTS["none"])(np.asarray(a, dtype=np.float32))
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    return (out / peak * 0.9).astype(np.float32) if peak > 0 else out


def voice():
    """(голос, эффект) с учётом характера, если в config стоит auto."""
    import personas
    p = personas.get(config.PERSONA, config.PROFANITY, config.CUSTOM_PERSONA)
    speaker = p["speaker"] if config.SILERO_SPEAKER == "auto" else config.SILERO_SPEAKER
    effect = p["effect"] if config.VOICE_EFFECT == "auto" else config.VOICE_EFFECT
    if config.TTS_ENGINE == "xtts" and config.VOICE_EFFECT == "auto":
        effect = config.XTTS_EFFECT   # для своего голоса — свой эффект (по умолчанию бархат)
    return speaker, effect


XTTS_SR = 24000


class TTS:
    def __init__(self):
        if config.TTS_ENGINE == "blips":
            self.engine = "blips"
            log.info("Озвучка: сигналы визуальной новеллы")
            return
        self.engine = None
        if config.TTS_ENGINE == "xtts":
            try:
                self._load_xtts()
                self.engine = "xtts"
            except FileNotFoundError:
                log.info("Своего голоса нет (voices\\my_voice.wav) — говорю голосом Silero")
            except Exception as e:
                log.warning("XTTS не загрузился (%s), перехожу на Silero", e)
        if self.engine is None and config.TTS_ENGINE in ("silero", "xtts"):
            path = silero_dir()
            if not path:
                # не качаем с GitHub при запуске: при медленном соединении это зависает на часы
                log.warning("Silero не скачан (запусти setup.bat с VPN), использую голос Windows")
            else:
                try:
                    import torch
                    torch.set_num_threads(4)
                    self.model, _ = torch.hub.load(
                        path, "silero_tts", source="local", language="ru", speaker="v4_ru",
                    )
                    self.engine = "silero"
                except Exception as e:
                    log.warning("Silero не загрузился (%s), использую голос Windows", e)
        if self.engine is None:
            import pyttsx3
            self.sapi = pyttsx3.init()
            for v in self.sapi.getProperty("voices"):
                if "ru" in (v.id + v.name).lower() or "irina" in v.name.lower():
                    self.sapi.setProperty("voice", v.id)
                    break
            self.engine = "sapi"
        log.info("Озвучка: %s", self.engine)

    def _load_xtts(self):
        """Клон голоса из записи config.XTTS_VOICE (запускать install_xtts.bat один раз)."""
        voice_file = os.path.abspath(config.XTTS_VOICE)
        if not os.path.isfile(voice_file):
            raise FileNotFoundError(f"нет файла с голосом {voice_file}")
        os.environ["COQUI_TOS_AGREED"] = "1"     # некоммерческая лицензия XTTS-v2 — для личного использования
        import torch
        from TTS.api import TTS as CoquiTTS
        device = "cuda" if config.XTTS_DEVICE == "cuda" and torch.cuda.is_available() else "cpu"
        api = CoquiTTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
        self.xtts = api.synthesizer.tts_model
        # «отпечаток» голоса считаем один раз при старте, а не на каждую фразу
        # по умолчанию XTTS берёт из записи лишь 6 секунд — даём ему всю запись (до 60 с) кусками по 4 с
        refs = [voice_file]
        extra_dir = os.path.splitext(voice_file)[0]          # можно положить ещё записи в папку с тем же именем
        if os.path.isdir(extra_dir):
            refs += [os.path.join(extra_dir, f) for f in sorted(os.listdir(extra_dir)) if f.lower().endswith(".wav")]
        self.xtts_latent, self.xtts_speaker = self.xtts.get_conditioning_latents(
            audio_path=refs,
            gpt_cond_len=config.XTTS_COND_SECONDS,
            gpt_cond_chunk_len=4,
            max_ref_length=60,
            sound_norm_refs=True,
        )
        log.info("XTTS: голос из %s, %s", voice_file, device)

    def _xtts_audio(self, text):
        out = self.xtts.inference(text, "ru", self.xtts_latent, self.xtts_speaker,
                                  temperature=config.XTTS_TEMPERATURE, top_p=0.8, top_k=50,
                                  repetition_penalty=5.0, speed=config.XTTS_SPEED,
                                  enable_text_splitting=False)
        wav = np.asarray(out["wav"], dtype=np.float32)
        return _speed(wav, XTTS_SR / SR)          # 24 кГц -> 48 кГц без изменения высоты

    def synth(self, text: str):
        """Текст -> готовый звук (48 кГц, с эффектом) или None. Для голоса Windows — None."""
        if self.engine == "blips":
            return _blip_audio(text) if text.strip() else None
        text = _clean(text)
        if not text or self.engine == "sapi":
            return None
        if self.engine == "xtts":
            _, effect = voice()
            parts = [self._xtts_audio(p) for p in _chunks(text, limit=200)]  # XTTS устойчивее на коротких кусках
        else:
            speaker, effect = voice()
            parts = [self.model.apply_tts(text=p, speaker=speaker, sample_rate=SR).numpy() for p in _chunks(text)]
        return apply_effect(np.concatenate(parts), effect) if parts else None

    def warmup(self):
        """Синтез одной фразы «вхолостую»: первый прогон XTTS на видеокарте самый медленный."""
        if self.engine in ("xtts", "silero"):
            try:
                self.synth("Привет, я уже проснулась.")
            except Exception as e:
                log.warning("Прогрев озвучки не удался: %s", e)

    def _free_vram(self):
        if self.engine == "xtts":
            import torch
            torch.cuda.empty_cache()                # не держать видеопамять между ответами

    def say(self, text: str, on_start=None, on_end=None):
        """on_start(текст) — в момент, когда звук реально начинает играть; on_end() — когда закончил."""
        if self.engine == "sapi":
            text = _clean(text)
            if text:
                if on_start:
                    on_start(text)
                self.sapi.say(text)
                self.sapi.runAndWait()
            if on_end:
                on_end()
            return
        audio = self.synth(text)
        if audio is not None:
            if on_start:
                on_start(text, len(audio) / SR, mouth_envelope(audio))
            sd.play(audio, SR)
            sd.wait()
        if on_end:
            on_end()
        self._free_vram()

    def speak_queue(self, q, on_start=None, on_gap=None, on_end=None):
        """Озвучивает предложения из очереди (None — конец). Следующее синтезируется,
        пока играет предыдущее, — поэтому паузы между предложениями почти нет.
        on_start(текст) — звук этого предложения пошёл; on_gap() — предыдущее доиграло,
        а следующее ещё готовится; on_end() — всё сказано."""
        import threading
        import time
        play_end = 0.0
        gap_timer = None
        while True:
            text = q.get()
            if text is None:
                break
            if self.engine == "sapi":
                self.say(text, on_start=on_start)
                continue
            try:
                audio = self.synth(text)
            except Exception:
                log.exception("Ошибка синтеза")
                continue
            if audio is None:
                continue
            if play_end and play_end - time.time() > 0:
                sd.wait()                      # дождаться конца предыдущего предложения
            if gap_timer:
                gap_timer.cancel()
            duration = len(audio) / SR
            if on_start:
                on_start(text, duration, mouth_envelope(audio))
            sd.play(audio, SR)
            play_end = time.time() + duration
            if on_gap:                         # доиграло, а следующее ещё не готово — закрыть рот
                gap_timer = threading.Timer(duration + 0.05, on_gap)
                gap_timer.daemon = True
                gap_timer.start()
        if play_end:
            sd.wait()
        if gap_timer:
            gap_timer.cancel()
        if on_end:
            on_end()
        self._free_vram()
