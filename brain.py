"""Мозг: модель в Ollama + цикл вызова функций."""
import datetime
import json
import logging
import os
import re
import time

import ollama

import config

log = logging.getLogger("jarvis.brain")

import personas

EMOTION_TAGS = ("neutral", "happy", "sad", "angry", "surprised", "shy", "wink", "think", "wave")

RULES = (
    "Ты работаешь голосовым ассистентом на компьютере пользователя под Windows. "
    "Отвечай по-русски, коротко — одно-три предложения, без markdown, списков и эмодзи: "
    "твой ответ будет озвучен. Для любых действий на компьютере вызывай функции, "
    "не придумывай, что сделал что-то без вызова функции. "
    "Для вопросов о фактах, новостях, событиях и всего, в чём не уверен — сначала search_internet. "
    "Погода — weather. Что на экране, ошибки, окна — look_at_screen. "
    "Таймеры и напоминания — set_timer (через N минут) или set_alarm (на конкретное время). "
    "Minecraft: «зайди в майнкрафт / поиграй со мной» — minecraft_join; дальше команды боту — minecraft_command "
    "(иди за мной — follow, охраняй — guard, добудь дерево — collect с target wood, скрафти верстак — craft с target "
    "crafting_table, построй дом — build с target house, сделай мост — build bridge, загон — build pen, "
    "дай кирку — give с target pickaxe). "
    "Игры запускай через launch_game, передавая официальное английское название (дота — Dota 2). "
    "Названия программ и игр, сказанные по-русски, переводи в оригинальные английские. "
    "Если функция вернула ошибку — честно скажи об этом. Отвечай по смыслу результата функции, а не наугад. "
    "Если нужной функции нет — честно скажи, что этого пока не умеешь. "
    "Долгие дела бота в Minecraft (стройка, добыча, плавка, урожай) идут в фоне: не говори, что готово, "
    "пока бот сам не сообщит. Просьбу из нескольких шагов (наруби дерево, скрафти инструменты, построй дом) "
    "отдавай боту сразу всеми командами подряд — он выполнит их по очереди. Брошенный игроком предмет бот подбирает командой pickup. "
    "Никогда не выдумывай рецепты, предметы и правила Minecraft: рецепт узнавай через minecraft_command "
    "с action recipe и пересказывай только его. Если пользователь тебя поправил — признай и попробуй снова. "
    "Если команда непонятна — коротко переспроси. "
    "Дату, время и день недели бери из блока «Сейчас» — для этого функции не нужны. "
    "Помни о пользователе: если он просит запомнить или сообщает о себе что-то важное и долговременное "
    "(имя, вкусы, расписание, близкие, планы) — вызови remember_fact; «забудь» — forget_fact. "
    "Используй известные факты о нём, когда это к месту, но не перечисляй их без повода. "
    "Про скопированный текст («переведи / объясни / исправь то, что я скопировал») — read_clipboard; "
    "длинный готовый текст для вставки — copy_to_clipboard. "
    "Учитывай весь предыдущий разговор: «а там», «а завтра», «ещё раз» относятся к прошлым репликам. "
    "Не пересказывай список своих умений, пока об этом прямо не спросят. Отвечай по существу, без воды. "
    "ВАЖНО: если для ответа нужна функция (погода, поиск, время, программы, игры, Minecraft и т.д.) — "
    "СНАЧАЛА вызови её, без единого слова текста перед вызовом. Никогда не говори, что тебе «нужна функция» — "
    "просто вызови её. На вопросы о погоде всегда вызывай weather, о фактах и новостях — search_internet. "
    "Только в окончательном ответе пользователю, после всех вызовов, поставь в самом начале метку эмоции: "
    "[neutral] [happy] [sad] [angry] [surprised] [shy] [wink] [think] [wave] (wave — приветствие или прощание). "
    "Метка не озвучивается. Пример окончательного ответа: [happy] Готово, всё получилось! "
    "Характер влияет только на манеру речи — функции вызывай всегда так же точно. "
    "Текст читает синтезатор речи, поэтому пиши грамотно и обычными словами: без многоточий, без растянутых "
    "букв (ну-у-у), без звукоподражаний (хм, кхе, пф), без ремарок в звёздочках или скобках, без сленга "
    "и выдуманных словечек; короткие ясные предложения. Характер передавай смыслом и интонацией фраз."
)
PERSONA = personas.get(config.PERSONA, config.PROFANITY, config.CUSTOM_PERSONA)
SYSTEM_PROMPT = PERSONA["prompt"] + "\n\n" + RULES

MAX_HISTORY = 30
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
          "октября", "ноября", "декабря")
# сложные вопросы — модель сначала «думает» (дольше, но умнее)
THINK_RX = r"\b(подумай|поразмысли|реши|решить|посчитай|вычисли|сравни|проанализируй|объясни подробно|" \
           r"почему|докажи|придумай план|составь план|разбери)"


# (регулярка по тексту пользователя, функция, аргументы)
_MC = r"(майн|minecraft|майнкрафт|мир|сервер|игру ко мне)"
FORCED = [
    (r"(зайд|зайти|заходи|зайдёшь|зайдешь|подключи|подключ|присоедин|войди|войти|залет|залеза|запрыг)\w*\W+(\w+\W+){0,6}?" + _MC,
     "minecraft_join", {}),
    (r"(майн|minecraft)\w*\W+(\w+\W+){0,6}?(зайд|зайти|заходи|подключ|присоедин|войди|войти)", "minecraft_join", {}),
]


def keep_alive(value):
    """Ollama принимает число секунд (-1 — навсегда, 0 — сразу) или строку с единицами ("10m").
    Строка из одного числа ("-1") вызывает ошибку — превращаем её в число."""
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        return int(value)
    return value


def _free_torch_cache():
    """Отдаёт обратно видеопамять, которую PyTorch (XTTS) держит «про запас»."""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
MAX_STEPS = 6


def _role(m):
    return m["role"] if isinstance(m, dict) else m.role


class Brain:
    def __init__(self, tools):
        self.client = ollama.Client(host=config.OLLAMA_HOST)
        self.tools = tools
        self.by_name = {f.__name__: f for f in tools}
        self.history = []
        self.last_time = 0.0
        self.game_mode = False
        self._load_history()

    # --- разговор переживает перезапуск ---
    def _load_history(self):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if time.time() - data.get("time", 0) < config.HISTORY_RESET_SECONDS:
                self.history = data.get("messages", [])
                self.last_time = data["time"]
                log.info("Продолжаю прошлый разговор (%d реплик)", len(self.history))
        except (OSError, ValueError, KeyError):
            pass

    def _save_history(self):
        msgs = []
        for m in self.history:                     # сохраняем только реплики, без служебных вызовов
            role = _role(m)
            content = m.get("content", "") if isinstance(m, dict) else (getattr(m, "content", "") or "")
            if role in ("user", "assistant") and content:
                msgs.append({"role": role, "content": content})
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump({"time": self.last_time, "messages": msgs[-MAX_HISTORY:]}, f, ensure_ascii=False)
        except OSError:
            pass

    @staticmethod
    def context():
        """Короткая справка о текущем моменте — подставляется перед последней репликой."""
        n = datetime.datetime.now()
        lines = [f"Сейчас: {WEEKDAYS[n.weekday()]}, {n.day} {MONTHS[n.month - 1]} {n.year}, {n:%H:%M}. "
                 f"Город пользователя: {getattr(config, 'CITY', '')}."]
        if 0 <= n.hour < 5:
            lines.append("Глубокая ночь: ты сонная. Можешь иногда сказать, что зеваешь, и мягко поворчать, "
                         "что пользователю пора спать, — но не в каждом ответе и не вместо дела.")
        elif 5 <= n.hour < 10:
            lines.append("Утро: если это первый разговор за день — пожелай доброго утра.")
        try:
            import tools
            win = tools.active_window()
            if win and "Джарвис" not in win and "jarvis" not in win.lower():
                lines.append(f"Активное окно на компьютере: {win[:80]}.")
        except Exception:
            pass
        try:
            import memory
            mem = memory.as_text()
            if mem:
                lines.append(mem)
        except Exception:
            pass
        return "\n".join(lines)

    def unload(self):
        """Выгружает из видеопамяти все загруженные модели Ollama."""
        try:
            for m in self.client.ps().models:
                self.client.generate(model=m.model, prompt="", keep_alive=0)
                log.info("Выгружена модель %s", m.model)
        except Exception:
            log.exception("Не удалось выгрузить модели")

    def _kwargs(self, messages):
        """Одинаковые параметры для прогрева и ответов: если num_ctx отличается, Ollama перезагружает модель."""
        messages = list(messages)
        # справку о «сейчас» и память ставим перед последней репликой пользователя: начало запроса
        # (инструкции + функции) не меняется, и Ollama не пересчитывает его каждый раз
        last_user = max((i for i, m in enumerate(messages) if _role(m) == "user"), default=None)
        if last_user is not None:
            messages.insert(last_user, {"role": "system", "content": self.context()})
        kwargs = dict(
            model=config.OLLAMA_MODEL,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            tools=self.tools,
            keep_alive=0 if self.game_mode else keep_alive(config.OLLAMA_KEEP_ALIVE),
            options={"num_ctx": config.OLLAMA_NUM_CTX, "repeat_penalty": 1.18,
                     "repeat_last_n": 256, "temperature": 0.8},
        )
        if config.OLLAMA_THINK is not None:
            kwargs["think"] = config.OLLAMA_THINK
        return kwargs

    def preload(self):
        """Прогрев: загружает модель с теми же настройками и «прочитывает» инструкции и список функций.
        Ollama запоминает этот общий начальный кусок, и первый настоящий ответ не ждёт ни загрузки, ни разбора."""
        t = time.time()
        try:
            kw = self._kwargs([{"role": "user", "content": "привет"}])
            kw["options"] = dict(kw["options"], num_predict=1)
            self.client.chat(stream=False, **kw)
            log.info("Модель %s прогрета за %.1f с", config.OLLAMA_MODEL, time.time() - t)
        except Exception as e:
            log.warning("Не удалось заранее загрузить модель: %s", e)

    warmup = preload

    def _stream(self, kwargs, on_sentence):
        """Потоковый ответ модели: готовые предложения сразу отдаём на озвучку.
        Возвращает (полный текст, вызовы функций, было_ли_что-то_озвучено)."""
        content, calls, buf, spoke = "", [], "", False
        for chunk in self.client.chat(stream=True, **kwargs):
            m = chunk.message
            if m.tool_calls:
                calls.extend(m.tool_calls)
            if m.content:
                content += m.content
                buf += m.content
                if on_sentence and not calls:
                    # отдаём всё до последнего конца предложения
                    cut = max(buf.rfind(c) for c in ".!?…")
                    if cut >= 15 and (cut + 1 == len(buf) or buf[cut + 1].isspace()):
                        part, buf = buf[:cut + 1], buf[cut + 1:]
                        on_sentence(part.strip())
                        spoke = True
        if on_sentence and not calls and buf.strip():
            on_sentence(buf.strip())
            spoke = True
        return content, calls, spoke

    def _stream_safe(self, kwargs, on_sentence):
        """То же, но если не хватило видеопамяти — выгружаем всё из Ollama и пробуем ещё раз."""
        try:
            return self._stream(kwargs, on_sentence)
        except ollama.ResponseError as e:
            if "out of memory" not in str(e).lower():
                raise
            log.warning("Не хватило видеопамяти — выгружаю модели и повторяю")
            self.unload()
            _free_torch_cache()
            time.sleep(3)
            return self._stream(kwargs, on_sentence)

    def _trim(self):
        if len(self.history) > MAX_HISTORY:
            self.history = self.history[-MAX_HISTORY:]
        while self.history and _role(self.history[0]) != "user":
            self.history.pop(0)

    def _forced_tool(self, text):
        """Команды, которые модель иногда «забалтывает» вместо вызова функции, — вызываем сами."""
        t = text.lower()
        # «я открыл / проверь ещё раз» сразу после разговора о входе в мир
        prev = next((str(m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "") or "")
                     for m in reversed(self.history[:-1]) if _role(m) == "assistant"), "").lower()
        if re.search(r"(открыл|провер|попробу|ещё раз|еще раз|готово|давай)", t) and re.search(r"(мир|для сети|майн)", prev):
            t += " зайди в мир"
        for rx, name, args in FORCED:
            if not re.search(rx, t):
                continue
            if name in self.by_name:
                log.info("Вызов (по ключевым словам): %s(%s)", name, args)
                try:
                    result = self.by_name[name](**args)
                except Exception as e:
                    log.exception("Ошибка в %s", name)
                    result = f"Ошибка: {e}"
                log.info("Результат: %s", str(result)[:300])
                self.history.append({"role": "assistant", "content": "",
                                     "tool_calls": [{"function": {"name": name, "arguments": args}}]})
                self.history.append({"role": "tool", "content": str(result), "tool_name": name})
                return

    def ask(self, text: str, on_sentence=None) -> str:
        """Ответ на команду. on_sentence(текст) вызывается для каждого готового предложения —
        так озвучка начинается, пока модель ещё дописывает ответ."""
        if time.time() - self.last_time > config.HISTORY_RESET_SECONDS:
            self.history = []
        self.last_time = time.time()
        self.history.append({"role": "user", "content": text})
        if "weather" in self.by_name and re.search(r"\b(?:погод\w*|прогноз\w*|дождь|зонт)\b", text, re.I):
            location = re.search(
                r"\b(?:в|во)\s+([\w-]+(?:\s+(?!(?:сейчас|сегодня|завтра|на|пожалуйста|для)\b)[\w-]+)*)",
                text, re.I,
            )
            city = location[1] if location else ""
            try:
                answer = self.by_name["weather"](city=city)
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                log.exception("Ошибка запроса погоды")
                answer = "Сервис погоды не ответил. Попробуй ещё раз чуть позже."
            self.history.append({"role": "assistant", "content": answer})
            self._trim()
            self._save_history()
            if on_sentence:
                on_sentence(answer)
            return answer
        self._forced_tool(text)
        think = bool(re.search(THINK_RX, text.lower())) and config.OLLAMA_THINK is not None
        if think:
            log.info("Сложный вопрос — думаю перед ответом")
            if on_sentence:
                on_sentence("Секунду, подумаю.")

        for step in range(MAX_STEPS):
            kwargs = self._kwargs(self.history)
            if think and step == 0:
                kwargs["think"] = True
            content, calls, spoke = self._stream_safe(kwargs, on_sentence)
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
            self.history.append(ollama.Message(role="assistant", content=content, tool_calls=calls or None))

            if not calls:
                self._trim()
                self._save_history()
                answer = content or "Готово."
                if on_sentence and not spoke:
                    on_sentence(answer)
                return answer

            for call in calls:
                name, args = call.function.name, dict(call.function.arguments or {})
                log.info("Вызов: %s(%s)", name, args)
                fn = self.by_name.get(name)
                try:
                    result = fn(**args) if fn else f"Функции {name} не существует"
                except Exception as e:
                    log.exception("Ошибка в %s", name)
                    result = f"Ошибка: {e}"
                log.info("Результат: %s", str(result)[:300])
                self.history.append({"role": "tool", "content": str(result)[:4000], "tool_name": name})

        self._trim()
        if on_sentence:
            on_sentence("Не получилось выполнить команду.")
        return "Не получилось выполнить команду."
