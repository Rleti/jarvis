"""Джарвис: кодовое слово -> распознавание -> Ollama с функциями -> озвучка. Значок в трее."""
import os
import sys

# pythonw.exe запускается без консоли — некоторые библиотеки падают, если им некуда писать
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# RTX 50-й серии: ядра CUDA собираются при запуске; кэш по умолчанию мал (256 МБ),
# и Whisper пересобирается каждый раз. Увеличиваем кэш до 4 ГБ — пересборка будет только один раз.
os.environ.setdefault("CUDA_CACHE_MAXSIZE", "4294967296")

import ctypes
import logging
import queue
import re
import collections
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
LOG_FILE = os.path.join(BASE, "jarvis.log")

handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
if sys.stdout and getattr(sys.stdout, "name", "") != os.devnull:
    handlers.append(logging.StreamHandler(sys.stdout))
logging.basicConfig(level=logging.INFO, handlers=handlers,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("jarvis")
logging.getLogger("faster_whisper").setLevel(logging.WARNING)  # не засорять лог каждой фразой
logging.getLogger("httpx").setLevel(logging.WARNING)

import config  # noqa: E402

YES = {"да", "давай", "подтверждаю", "выполняй", "конечно", "ага", "угу", "делай"}
NO = {"нет", "не", "отмена", "отмени", "стоп"}
CANCEL = {"отмена", "ничего", "стоп"}
EMOJI_EMOTIONS = (
    ("😊😄😁😃😆🥰😍✨🎉👍❤♡💕🤗😺", "happy"),
    ("😢😭😞😔🥺😿💔", "sad"),
    ("😠😡😤💢👿😾", "angry"),
    ("😮😲😱😯❗‼🙀", "surprised"),
    ("😳☺🙈😚", "shy"),
    ("😉😜😏", "wink"),
    ("🤔💭❓", "think"),
    ("👋", "wave"),
)
HALLUCINATIONS = ("продолжение следует", "субтитры", "спасибо за просмотр", "редактор субтитров",
                  "подписывайтесь на канал", "ставьте лайк")


def beep(freq=880, ms=120):
    try:
        import winsound
        winsound.Beep(freq, ms)
    except Exception:
        pass


def ensure_ollama():
    """Запускает сервер Ollama, если он не работает (например, его закрыли из трея)."""
    import subprocess
    import time
    import urllib.request

    def up():
        try:
            urllib.request.urlopen(config.OLLAMA_HOST + "/api/version", timeout=2)
            return True
        except Exception:
            return False

    if up():
        return
    exe = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")
    if not os.path.isfile(exe):
        exe = "ollama"
    try:
        subprocess.Popen([exe, "serve"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        log.error("Ollama не найдена — запусти setup.bat")
        return
    for _ in range(20):
        if up():
            log.info("Сервер Ollama запущен")
            return
        time.sleep(1)
    log.error("Сервер Ollama не отвечает")


def single_instance():
    """Не даёт запустить второго Джарвиса (например, автозапуск + вручную)."""
    if os.name != "nt":
        return True
    ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\JarvisAssistantMutex")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


class Assistant(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.paused = threading.Event()
        self.stopped = threading.Event()
        self.ready = threading.Event()
        self.tts_lock = threading.RLock()  # говорить может и основной поток, и напоминания
        self.ptt = None
        self.status = "loading"            # для веб-интерфейса: loading / idle / listen / think / talk
        self.chat = collections.deque(maxlen=120)   # последние реплики (голос и веб) для веб-интерфейса

    def note(self, who, text, src="voice"):
        if text:
            self.chat.append({"who": who, "text": text, "src": src, "ts": time.time()})

    # ---------- загрузка ----------
    def _load(self):
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass

        t0 = time.time()
        ensure_ollama()
        import face_link
        face_link.start()                      # окно с Джарвис-тян (если включено)
        self.face = face_link
        self.face.state("think")
        warmup = getattr(config, "WARMUP", True)
        self.face.reply("Загружаю модели…" if warmup else "Запускаюсь…", 1)
        from audio import Mic
        from brain import Brain
        from stt import STT
        from tts import TTS
        import tools

        self.brain = Brain(tools.TOOLS)
        self.stt = STT()

        self.oww = self.wake = None
        if config.WAKE_ENGINE == "none":
            pass
        elif config.WAKE_ENGINE == "openwakeword":
            log.info("Загрузка кодового слова…")
            import openwakeword.utils
            from openwakeword.model import Model
            if not os.path.isfile(config.WAKE_MODEL):
                try:
                    openwakeword.utils.download_models(model_names=[config.WAKE_MODEL])
                except TypeError:
                    openwakeword.utils.download_models()
            self.oww = Model(wakeword_models=[config.WAKE_MODEL], inference_framework="onnx")
        else:
            from wake import PhraseWake
            self.wake = PhraseWake(self.stt)

        log.info("Загрузка озвучки…")
        self.tts = TTS()
        if warmup:
            log.info("Прогрев моделей…")
            self.stt.warmup()
            self.tts.warmup()
            self.brain.preload()
        log.info("Инициализация Jarvis: %.1f с", time.time() - t0)
        tools.set_confirm_handler(self.confirm)
        self.mic = Mic(config.MIC_DEVICE)

        from reminders import Reminders
        tools.reminders = Reminders(self.announce)

        import minecraft_tools
        minecraft_tools.announce = self.say     # бот сам сообщает: «добыл…», «мало здоровья»

        if config.PTT_KEY:
            try:
                from ptt import PushToTalk
                self.ptt = PushToTalk(config.PTT_KEY)
            except Exception:
                log.exception("Push-to-talk не запустился — проверь PTT_KEY в config.py")

        if config.GAME_MODE:
            from gamemode import GameMode
            GameMode(self.on_game).start()

    # ---------- основной цикл ----------
    def run(self):
        try:
            self._load()
        except Exception:
            log.exception("Не удалось запуститься")
            return
        self.mic.start()
        self.ready.set()
        self.status = "idle"
        if getattr(config, "WEB_ENABLED", True):
            try:
                import web
                self.web_url = web.start(self)
            except Exception:
                log.exception("Веб-интерфейс не запустился")
        try:
            import telegram_bot
            if telegram_bot.start(self) and telegram_bot.PAIR_CODE:
                self.face.reply(f"Код для Telegram-бота: {telegram_bot.PAIR_CODE}", 10)
        except Exception:
            log.exception("Telegram-бот не запустился")
        hints = []
        if self.ptt:
            hints.append(f"держи {config.PTT_KEY} и говори")
        if self.oww is not None:
            hints.append("скажи «Hey Jarvis»")
        elif self.wake is not None:
            hints.append("скажи «Привет, Джарвис»")
        log.info("Готов: %s.", " или ".join(hints) or "нет способа вызова — проверь PTT_KEY и WAKE_ENGINE")
        self.face.state("idle")
        if not config.GREETING:
            self.face.reply("Готова! Держи правый Ctrl и говори.", 3)
        if config.GREETING:
            self.say(config.GREETING)
            self.mic.clear()

        while not self.stopped.is_set():
            try:
                chunk = self.mic.read(timeout=1.0)
            except queue.Empty:
                continue
            if self.paused.is_set():
                continue
            if self.ptt and self.ptt.is_down():
                try:
                    self.handle_ptt(chunk)
                except Exception:
                    log.exception("Ошибка push-to-talk")
                self._after_command()
                continue
            if self.oww is not None:
                triggered = max(self.oww.predict(chunk).values()) >= config.WAKE_THRESHOLD
                rest = ""
            elif self.wake is None:
                continue                      # только push-to-talk
            else:
                rest = self.wake.feed(chunk)
                triggered = rest is not None
            if not triggered:
                continue
            try:
                self.session(rest)
            except Exception:
                log.exception("Ошибка в режиме разговора")
            self._after_command()
        self.mic.stop()

    def _after_command(self):
        self.status = "idle"
        self.mic.clear()
        if self.oww is not None:
            self.oww.reset()
        elif self.wake is not None:
            self.wake.reset()

    # ---------- озвучка, напоминания, игровой режим ----------
    def _talk_start(self, text, duration=None, mouth=None):
        self.face.reply(text, duration, mouth)   # текст печатается в темп голоса, рот — по громкости
        self.face.state("talk")
        self.status = "talk"

    def say(self, text):
        with self.tts_lock:
            try:
                self.tts.say(text, on_start=self._talk_start)
            finally:
                self.face.state("idle")

    def announce(self, text, missed=False):
        """Вызывается из потока напоминаний."""
        with self.tts_lock:
            for _ in range(3):
                beep(1320, 150)
                beep(990, 150)
            prefix = "Пропущенное напоминание. " if missed else "Напоминание. "
            try:
                import telegram_bot
                threading.Thread(target=telegram_bot.notify, args=("⏰ " + prefix + (text or "Время вышло!"),),
                                 daemon=True).start()
            except Exception:
                pass
            self.tts.say(prefix + text if text else "Время вышло!", on_start=self._talk_start,
                         on_end=lambda: self.face.state("idle"))
        self.mic.clear()

    def on_game(self, active, game):
        import tools
        tools.GAME_MODE = active
        self.brain.game_mode = active
        if active:
            self.brain.unload()
            if config.GAME_MODE_WHISPER_CPU:
                self.stt.set_gpu(False)
        else:
            self.stt.set_gpu(True)
            self.brain.preload()

    def _clean(self, text):
        low = text.lower()
        if len(low.strip(" .,!?")) < 2 or any(h in low for h in HALLUCINATIONS):
            return ""
        return text

    def answer(self, text, mode="pc", on_part=None, src="voice"):
        """Спрашиваем модель и озвучиваем ответ по предложениям, пока он ещё пишется.
        mode: "pc" — говорить на компьютере; "quiet" — только текст (веб-интерфейс сам решает, озвучивать ли).
        on_part(текст) — каждое готовое предложение (для веб-интерфейса)."""
        t0 = time.time()
        first = []
        q = queue.Queue()
        self.note("user", text, src)

        def on_sentence(part):
            tags = re.findall(r"\[(\w+)\]", part)
            if not tags:                       # метки нет — угадываем эмоцию по эмодзи
                for emo_chars, emo in EMOJI_EMOTIONS:
                    if any(ch in part for ch in emo_chars):
                        tags = [emo]
                        break
            part = re.sub(r"\s*\[\w+\]\s*", " ", part).strip()   # метки эмоций не озвучиваем
            if tags:
                self.face.emotion(tags[-1].lower())
            if not part:
                return
            if not first:
                first.append(time.time() - t0)
            if on_part:
                on_part(part)
            if mode == "pc":
                q.put(part)

        with self.tts_lock:
            self.face.state("think")       # пока готовится голос — «думает»
            self.status = "think"
            speaker = threading.Thread(
                target=self.tts.speak_queue, args=(q,), daemon=True,
                kwargs=dict(on_start=self._talk_start, on_gap=lambda: self.face.state("idle")))
            speaker.start()
            try:
                reply = self.brain.ask(text, on_sentence=on_sentence)
            except Exception as e:
                log.exception("Ollama")
                reply = "Не могу связаться с моделью. Проверь, запущена ли Оллама." \
                    if "connect" in str(e).lower() else "Произошла ошибка, подробности в логе."
                q.put(reply)
                if on_part:
                    on_part(reply)
            q.put(None)
            speaker.join()
            if mode != "pc":               # без голоса — просто показать ответ в окне
                clean = re.sub(r"\s*\[\w+\]\s*", " ", reply).strip()
                self.face.reply(clean, max(2.0, len(clean) / 18))
            self.face.state("idle")
            self.status = "idle"
        reply = re.sub(r"\s*\[\w+\]\s*", " ", reply).strip()
        self.note("jarvis", reply, src)
        log.info("Джарвис: %s", reply)
        log.info("Время: первое предложение через %.1f с, всего %.1f с",
                 first[0] if first else -1, time.time() - t0)

    def handle_ptt(self, first_chunk):
        """Пока клавиша зажата — пишем, отпустил — распознаём и выполняем."""
        import numpy as np
        beep(1200, 40)
        self.face.state("listen")
        self.status = "listen"
        frames, limit = [first_chunk], int(config.PTT_MAX_SECONDS / 0.08)
        while self.ptt.is_down() and len(frames) < limit:
            try:
                frames.append(self.mic.read(timeout=0.5))
            except queue.Empty:
                pass
        # пара кадров «хвоста»: люди часто отпускают кнопку, договаривая последний слог
        for _ in range(3):
            try:
                frames.append(self.mic.read(timeout=0.2))
            except queue.Empty:
                break
        beep(700, 40)
        self.face.state("think")
        if len(frames) < 8:
            self.face.state("idle")            # меньше ~0,4 с речи — случайное нажатие
            return
        audio = np.concatenate(frames).astype(np.float32) / 32768.0
        level = float(np.sqrt(np.mean(audio ** 2)))
        if level < 0.002:              # практически тишина — микрофон выключен или выбран не тот
            log.warning("Микрофон молчит (уровень %.4f). Проверь микрофон в Windows или MIC_DEVICE в config.py", level)
            self.mic.log_devices()
            self.say("Не слышу тебя. Проверь микрофон.")
            return
        import time
        t0 = time.time()
        text = self._clean(self.stt.transcribe(audio))
        log.info("Распознавание: %.1f с (громкость %.3f)", time.time() - t0, level)
        if not text:
            log.info("Речь не распознана")
            self.face.state("idle")
            beep(440, 120)
            return
        log.info("Ты (PTT): %s", text)
        self.face.user(text)
        self.answer(text)

    def listen(self, start_timeout=None):
        audio = self.mic.record_command(
            config.SILENCE_SECONDS, config.MAX_COMMAND_SECONDS,
            start_timeout or config.START_TIMEOUT_SECONDS,
        )
        if audio is None:
            return ""
        # Whisper иногда "слышит" в шуме фразы из субтитров — _clean их выкидывает
        return self._clean(self.stt.transcribe(audio))

    @staticmethod
    def _norm(text):
        return " ".join(re.findall(r"\w+", text.lower().replace("ё", "е")))

    def is_sleep(self, text):
        t = " " + self._norm(text) + " "
        return any(" " + self._norm(p) + " " in t for p in config.SLEEP_PHRASES)

    def session(self, text=""):
        """Режим разговора: команды подряд без кодового слова, до фразы для сна или тишины."""
        log.info("Слушаю")
        beep()
        while not self.stopped.is_set() and not self.paused.is_set():
            if not text:
                text = self.listen(config.SESSION_TIMEOUT_SECONDS)
                if not text:
                    log.info("Засыпаю: тишина")
                    beep(440, 150)
                    return
            log.info("Ты: %s", text)

            if self.is_sleep(text):
                log.info("Засыпаю по команде")
                if config.SLEEP_REPLY:
                    self.say(config.SLEEP_REPLY)
                beep(440, 150)
                return

            words = set(re.findall(r"\w+", text.lower()))
            if not (words and words <= CANCEL):
                self.answer(text)
            text = ""
            beep(1000, 60)   # короткий писк — готов слушать дальше

    def confirm(self, question: str) -> bool:
        self.say(question + " Скажи да или нет.")
        beep()
        words = set(re.findall(r"\w+", self.listen().lower()))
        ok = bool(words & YES) and not (words & NO)
        log.info("Подтверждение «%s»: %s", question, ok)
        return ok

    def stop(self):
        try:
            self.face.stop()
        except Exception:
            pass
        self.stopped.set()


def run_tray(assistant: Assistant):
    import pystray
    from PIL import Image, ImageDraw

    def icon_image(paused):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        color = (120, 120, 120, 255) if paused else (0, 170, 255, 255)
        d.ellipse((6, 6, 58, 58), fill=color)
        d.ellipse((22, 22, 42, 42), fill=(255, 255, 255, 255))
        return img

    def toggle(icon, item):
        if assistant.paused.is_set():
            assistant.paused.clear()
        else:
            assistant.paused.set()
        icon.icon = icon_image(assistant.paused.is_set())

    def open_log(icon, item):
        os.startfile(LOG_FILE)

    def open_web(icon, item):
        import web
        if web.LOCAL_CONNECT_URL:
            os.startfile(web.LOCAL_CONNECT_URL)    # страница со ссылкой и QR-кодом для телефона

    def quit_app(icon, item):
        assistant.stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(lambda item: "Продолжить" if assistant.paused.is_set() else "Пауза", toggle),
        pystray.MenuItem("Веб-интерфейс (для телефона)", open_web),
        pystray.MenuItem("Открыть лог", open_log),
        pystray.MenuItem("Выход", quit_app),
    )
    pystray.Icon("Jarvis", icon_image(False), "Jarvis", menu).run()


def sync_autostart():
    """AUTOSTART = False в config.py — убрать Джарвиса из автозагрузки Windows (ярлык ставит setup)."""
    if os.name != "nt" or getattr(config, "AUTOSTART", True):
        return
    lnk = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup\Jarvis.lnk")
    try:
        if os.path.exists(lnk):
            os.remove(lnk)
            log.info("Убрала себя из автозагрузки (AUTOSTART = False)")
    except OSError as e:
        log.warning("Не удалось убрать из автозагрузки: %s", e)


def main():
    if not single_instance():
        log.info("Джарвис уже запущен")
        return
    sync_autostart()
    assistant = Assistant()
    assistant.start()
    try:
        run_tray(assistant)
    except Exception:
        log.exception("Трей не запустился, работаю без него (Ctrl+C для выхода)")
        try:
            assistant.join()
        except KeyboardInterrupt:
            assistant.stop()


if __name__ == "__main__":
    main()
