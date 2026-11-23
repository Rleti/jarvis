"""Настройки Джарвиса. Меняй здесь, код трогать не нужно."""

# ---------- Мозг (Ollama) ----------
OLLAMA_HOST = "http://127.0.0.1:11434"
# "auto" — подобрать под видеокарту (см. hardware.py; проверить: .venv\Scripts\python hardware.py)
OLLAMA_MODEL = "auto"           # 16+ ГБ: qwen3:8b · 12 ГБ: qwen3:8b · 8 ГБ: qwen3:4b · без NVIDIA: qwen3:1.7b
                                # "qwen3:14b" (~12 ГБ) умнее, но вместе со своим голосом (XTTS) не помещается в 16 ГБ —
                                # с ней поставь TTS_ENGINE = "silero" или XTTS_DEVICE = "cpu"
OLLAMA_KEEP_ALIVE = -1          # держать модель в видеопамяти всегда — ответы без задержки на загрузку
                                # (игровой режим всё равно выгружает её на время игры). "10m" — выгружать после простоя
OLLAMA_NUM_CTX = "auto"         # длина контекста (8192 на 16 ГБ, 4096 на меньших картах)
OLLAMA_THINK = False            # для qwen3: False = без "размышлений", быстрее. Для gpt-oss поставь None
HISTORY_RESET_SECONDS = 1800    # через сколько секунд тишины начинать разговор заново (переживает перезапуск)

# ---------- Кодовое слово ----------
WAKE_ENGINE = "none"            # "none" — только push-to-talk; "openwakeword" — «Hey Jarvis»;
                                # "phrase" — «Привет, Джарвис» через Whisper
WAKE_REQUIRE_GREETING = True    # True — нужно «привет, Джарвис»; False — хватит просто «Джарвис»
WAKE_SILENCE_SECONDS = 0.6      # пауза, после которой фраза отправляется на проверку
WAKE_MAX_SECONDS = 8
WAKE_MIN_LEVEL = 400            # минимальная громкость речи; если реагирует на шум — подними до 600–800

# для WAKE_ENGINE = "openwakeword":
WAKE_MODEL = "hey_jarvis"       # встроенная модель; можно указать путь к своей .onnx
WAKE_THRESHOLD = 0.5            # 0..1: выше — меньше ложных срабатываний, но надо говорить чётче

# ---------- Режим разговора ----------
# После кодового слова Джарвис слушает команды одну за другой, пока не скажешь фразу для сна
# или не помолчишь SESSION_TIMEOUT_SECONDS секунд.
SESSION_TIMEOUT_SECONDS = 15
SLEEP_PHRASES = [
    "отбой", "спасибо джарвис", "пока джарвис", "спи", "иди спать",
    "засыпай", "отключись", "выключись", "хватит", "все спасибо",
]
SLEEP_REPLY = "Если что — зови."   # пустая строка — просто писк

# ---------- Распознавание речи (faster-whisper) ----------
WHISPER_MODEL = "auto"          # large-v3-turbo на 8+ ГБ, small на слабых
WHISPER_DEVICE = "auto"         # "cuda" или "cpu"
WHISPER_COMPUTE = "auto"        # float16 / int8_float16 / int8
WHISPER_CPU_MODEL = "small"     # запасной вариант, если видеокарта не завелась
LANGUAGE = "ru"

SILENCE_SECONDS = 1.0           # пауза, после которой команда считается законченной
MAX_COMMAND_SECONDS = 12
START_TIMEOUT_SECONDS = 5       # сколько ждать начала речи после кодового слова

# ---------- Характер ----------
PERSONA = "anime"               # anime — аниме-девочка Джарвис-тян; pathos — пафосный прокуренный мужик;
                                # butler — чопорный дворецкий; default — обычный; custom — свой (опиши ниже)
PROFANITY = "full"              # none — без мата; light — «блин», «чёрт побери»; full — с матом
CUSTOM_PERSONA = ""

# ---------- Окно с анимацией ----------
FACE_WINDOW = True              # открывать окно консоли с Джарвис-тян
FACE_SCENE = True               # цветная сцена: комната с анимациями за персонажем (нужен Windows Terminal)
FACE_STYLE = "braille"          # braille — точками, как на картинке; ascii — для старой консоли, если видны квадратики
FACE_NAME = "Джарвис-тян"
FACE_SOURCE_COLOR = 0.32        # доля исходного цвета в палитре комнаты
FACE_FOLDER = "face_neon"            # своя картинка: положи в эту папку idle.png (и по желанию blink, talk1, talk2,
                                # think, listen — тогда будет анимация). Нет картинок — встроенная Джарвис-тян
FACE_WIDTH = 78                 # ширина картинки в символах
FACE_MODE = "lineart"           # lineart — для рисунков с контуром (линии чёткие, заливка редкими точками);
                                # dither — для фото и картинок с плавными тенями
FACE_INVERT = False             # False — точки на тёмных местах (рисунок на светлом фоне); True — на светлых (фото)
FACE_PORT = 3006

# ---------- Озвучка ----------
TTS_ENGINE = "blips"            # короткие звуки при появлении реплики, как в визуальной новелле
BLIP_CHARS_PER_SECOND = 22
BLIP_VOLUME = 0.17              # громкость от 0 до 1
XTTS_VOICE = r"voices\my_voice.wav"   # твой голос (самая первая запись); голос друга — voices\friend_v3.wav или friend_v2.wav
XTTS_DEVICE = "auto"            # "cuda" — быстро, ~2–3 ГБ видеопамяти; "cpu" — медленно, но не занимает видеокарту
XTTS_EFFECT = "none"            # эффект для своего голоса: velvet (бархатный, томный), none (как есть), smoker …
XTTS_SPEED = 1.0                # темп речи: меньше — медленнее и томнее (0.8–1.1)
XTTS_COND_SECONDS = 60          # сколько секунд записи брать для «отпечатка» голоса (больше — похожее)
XTTS_TEMPERATURE = 0.7          # 0.5 — ровнее и стабильнее, 0.85 — живее, но голос может «гулять»
SILERO_SPEAKER = "auto"         # auto — голос под характер; или aidar, eugene, baya, kseniya, xenia
VOICE_EFFECT = "auto"           # auto — под характер; или none, velvet (бархат), smoker (прокуренный), chipmunk, demon,
                                # giant, robot, alien, drunk, cave
GREETING ="Джарвис на связи."  # пустая строка — молча

# ---------- Новые функции ----------
CITY = "Москва"                 # город для погоды по умолчанию
VISION_MODEL = "auto"           # зрение «что на экране»: qwen3-vl:8b / 4b / 2b по видеопамяти, "" — выключить
VISION_KEEP_ALIVE = 0           # "0" — сразу выгружать, чтобы вернуть видеопамять основной модели

PTT_KEY = "ctrl_r"              # push-to-talk: держи и говори. "" — выключить.
                                # Варианты: ctrl_r, alt_r, shift_r, f1..f12, caps_lock, insert, pause,
                                # num0..num9, любая буква/цифра, mouse_x1 / mouse_x2 — боковые кнопки мыши
PTT_MAX_SECONDS = 30
MIC_DEVICE = ""

GAME_MODE = True                # при запуске игры выгружать модели из видеопамяти
GAME_MODE_WHISPER_CPU = True    # в игре переносить распознавание речи на процессор
GAME_PROCESSES = []             # игры не из Steam, имена процессов: ["VALORANT-Win64-Shipping.exe"]
GAME_IGNORE = ["wallpaper", "steamvr", "vrserver", "vrmonitor"]  # не считать играми

# ---------- Minecraft-напарник ----------
MC_HOST = "localhost"
MC_PORT = 0                     # 0 — найти порт открытого для сети мира автоматически
MC_BOT_NAME = "Jarvis"          # ник бота в игре (не должен совпадать с твоим)
MC_API_PORT = 3005              # внутренний порт для связи Джарвиса с ботом

# ---------- Программы ----------
STEAM_PATH = ""

# Псевдонимы: что ты говоришь -> что запускать. Остальное ищется в меню Пуск автоматически.
APPS = {}


# ---------- веб-интерфейс (чат с телефона в домашней сети) ----------
WEB_ENABLED = True              # ссылка с ключом — в трее: «Веб-интерфейс (для телефона)», там же QR-код
WEB_PORT = 8765
WEB_LAN = False
WEB_TOKEN = ""

# ---------- Telegram-бот (переписка и голосовые с телефона откуда угодно) ----------
TG_TOKEN = ""
TG_ALLOWED = []
TG_VOICE_REPLY = True           # присылать ответы ещё и голосовым
TG_SPEAK_ON_PC = False          # говорить ответы из Telegram ещё и вслух на компьютере
TG_PROXY = ""

AUTOSTART = False               # True — запускать Джарвиса вместе с Windows

# ---------- автоподбор под железо (заменяет значения "auto" выше) ----------
WARMUP = False                  # загружать модели по первой команде; True — прогреть их при запуске
import hardware as _hw
_hw.apply(globals())
