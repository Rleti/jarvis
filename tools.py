"""Функции, которые Джарвис может вызывать.

Модель видит название, типы аргументов и докстринг каждой функции — пиши их понятно.
Чтобы добавить новую команду: напиши функцию и добавь её в список TOOLS внизу.
"""
import ctypes
import datetime
import logging
import os
import re
import subprocess
import time
import urllib.parse
import webbrowser
from pathlib import Path

import psutil

import config

log = logging.getLogger("jarvis.tools")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HOME = Path.home()

# Подтверждение опасных действий голосом. Обработчик подставляет jarvis.py.
_confirm = lambda question: False


def set_confirm_handler(fn):
    global _confirm
    _confirm = fn


START_MENU_DIRS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
]
PROTECTED = {
    "explorer.exe", "csrss.exe", "winlogon.exe", "svchost.exe", "lsass.exe",
    "services.exe", "dwm.exe", "system", "python.exe", "pythonw.exe", "ollama.exe",
}
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def _find_shortcut(name: str):
    q = name.lower().strip()
    best = None
    for d in START_MENU_DIRS:
        if not d.exists():
            continue
        for p in list(d.rglob("*.lnk")) + list(d.rglob("*.url")):
            stem = p.stem.lower()
            if "uninstall" in stem or "удал" in stem:
                continue
            if stem == q:
                return p
            if q in stem and (best is None or len(stem) < len(best.stem)):
                best = p
    return best


# ======================= Команды =======================

def get_time() -> str:
    """Возвращает текущую дату, день недели и время."""
    n = datetime.datetime.now()
    return f"{n.day} {MONTHS[n.month - 1]} {n.year}, {WEEKDAYS[n.weekday()]}, {n:%H:%M}"


def open_app(name: str) -> str:
    """Открывает программу на компьютере. Для игр лучше launch_game.

    Args:
        name: название программы, лучше как в меню Пуск (например: Telegram, Steam, Word, PyCharm, браузер, блокнот)
    """
    key = name.lower().strip()
    target = None
    for alias, path in config.APPS.items():
        if alias in key or key in alias:
            target = os.path.expandvars(path)
            break
    if target is None:
        lnk = _find_shortcut(name)
        if lnk:
            target = str(lnk)
    if target is None and _match_game(name):
        return launch_game(name)
    try:
        os.startfile(target or name)
        return f"Открываю {name}"
    except OSError:
        return f"Не нашёл программу «{name}»"


def _norm(s: str) -> str:
    return re.sub(r"[^a-zа-я0-9]", "", s.lower().replace(".exe", ""))


# Программы, которые при обычном закрытии прячутся в трей — их надо завершать принудительно
TRAY_APPS = {"steam", "steamwebhelper", "discord", "telegram", "epicgameslauncher",
             "battlenet", "spotify", "ubisoftconnect", "origin", "eadesktop"}


def close_app(name: str) -> str:
    """Полностью закрывает программу или игру (включая те, что сворачиваются в трей, например Steam, Discord, Telegram).

    Args:
        name: название программы или игры (например: steam, chrome, telegram, discord, dota 2, winword)
    """
    q = _norm(name)
    if len(q) < 3:
        return "Слишком короткое название, уточни программу"

    # Steam правильно закрывать его же командой — иначе он просто прячется в трей
    if q.startswith("steam") or q == "стим":
        exe = os.path.join(_steam_root() or "", "steam.exe")
        if os.path.isfile(exe):
            subprocess.Popen([exe, "-shutdown"], creationflags=NO_WINDOW)
            return "Закрываю Steam"

    # имя игры из Steam -> имя её процесса (Dota 2 -> dota2.exe)
    targets = {q}
    game = _match_game(name)
    if game:
        targets.add(_norm(game[1]))

    found = {}
    for p in psutil.process_iter(["name"]):
        n = p.info["name"] or ""
        if n.lower() in PROTECTED:
            continue
        if any(t in _norm(n) for t in targets):
            found.setdefault(n, []).append(p)
    if not found:
        return f"Не нашёл запущенную программу «{name}»"

    for n in found:
        subprocess.run(["taskkill", "/IM", n], capture_output=True, creationflags=NO_WINDOW)
    time.sleep(2)
    # кто не закрылся (ушёл в трей) — завершаем принудительно, но только известные "трейные" программы и игры
    for n, procs in found.items():
        if any(p.is_running() for p in procs) and (_norm(n) in TRAY_APPS or game):
            subprocess.run(["taskkill", "/IM", n, "/F", "/T"], capture_output=True, creationflags=NO_WINDOW)
    return "Закрыл: " + ", ".join(sorted(found))


# ======================= Steam-игры =======================

def _steam_root():
    if os.path.isfile(os.path.join(config.STEAM_PATH, "steam.exe")):
        return config.STEAM_PATH
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return winreg.QueryValueEx(k, "SteamPath")[0].replace("/", "\\")
    except Exception:
        return None


def _steam_games():
    """Список установленных игр: [(appid, название, имя папки, полный путь)]."""
    root = _steam_root()
    if not root:
        return []
    libs = {root}
    vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
    if os.path.isfile(vdf):
        text = open(vdf, encoding="utf-8", errors="ignore").read()
        libs |= {p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"(.+?)"', text)}
    games = []
    for lib in libs:
        common = os.path.join(lib, "steamapps", "common")
        for acf in Path(lib, "steamapps").glob("appmanifest_*.acf"):
            text = acf.read_text(encoding="utf-8", errors="ignore")
            appid = re.search(r'"appid"\s+"(\d+)"', text)
            title = re.search(r'"name"\s+"(.+?)"', text)
            folder = re.search(r'"installdir"\s+"(.+?)"', text)
            if appid and title:
                d = folder.group(1) if folder else ""
                games.append((appid.group(1), title.group(1), d, os.path.join(common, d) if d else ""))
    return games


_TR = dict(zip("абвгдезийклмнопрстуфхцыэ", "abvgdeziiklmnoprstufhcye"))
_TR.update({"ж": "zh", "ч": "ch", "ш": "sh", "щ": "sch", "ю": "yu", "я": "ya", "ь": "", "ъ": ""})


def _match_game(name: str):
    """Ищет игру по названию: 'дота 2', 'Dota2', 'киберпанк' и т.п."""
    games = _steam_games()
    q = _norm(name)
    if not games or not q:
        return None
    g = _match_game_q(q, games)
    if g is None and re.search("[а-я]", q):
        g = _match_game_q("".join(_TR.get(ch, ch) for ch in q), games)   # дота -> dota
    return g


def _match_game_q(q, games):
    import difflib
    for g in games:
        if q == _norm(g[1]) or q == _norm(g[2]):
            return g
    for g in games:
        if q in _norm(g[1]) or q in _norm(g[2]):
            return g
    names = {_norm(g[1]): g for g in games}
    close = difflib.get_close_matches(q, names.keys(), n=1, cutoff=0.6)
    return names[close[0]] if close else None


def launch_game(name: str) -> str:
    """Запускает игру из Steam.

    Args:
        name: название игры, лучше официальное английское (например: Dota 2, Counter-Strike 2, Cyberpunk 2077)
    """
    g = _match_game(name)
    if not g:
        return f"Игра «{name}» не найдена в Steam"
    os.startfile(f"steam://rungameid/{g[0]}")
    return f"Запускаю {g[1]}"


def list_games() -> str:
    """Возвращает список установленных игр Steam."""
    games = _steam_games()
    return ", ".join(sorted(g[1] for g in games)) if games else "Игр Steam не найдено"


def open_website(url: str) -> str:
    """Открывает сайт в браузере.

    Args:
        url: адрес сайта, например youtube.com
    """
    if not url.startswith("http"):
        url = "https://" + url
    webbrowser.open(url)
    return f"Открыл {url}"


def web_search(query: str) -> str:
    """Открывает поиск в браузере. Только если пользователь явно просит открыть поиск; чтобы узнать ответ — search_internet.

    Args:
        query: поисковый запрос
    """
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(query))
    return f"Ищу: {query}"


def _volume_endpoint():
    import comtypes
    try:
        comtypes.CoInitialize()
    except OSError:
        pass
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    dev = AudioUtilities.GetSpeakers()
    if hasattr(dev, "EndpointVolume"):          # новые версии pycaw
        return dev.EndpointVolume
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL
    iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(iface, POINTER(IAudioEndpointVolume))


def set_volume(percent: int) -> str:
    """Устанавливает общую громкость звука.

    Args:
        percent: громкость от 0 до 100
    """
    p = max(0, min(100, int(percent)))
    _volume_endpoint().SetMasterVolumeLevelScalar(p / 100, None)
    return f"Громкость {p}%"


def get_volume() -> str:
    """Возвращает текущую громкость звука в процентах."""
    return f"Громкость {round(_volume_endpoint().GetMasterVolumeLevelScalar() * 100)}%"


def media_control(action: str) -> str:
    """Управляет воспроизведением музыки и видео.

    Args:
        action: одно из: play_pause, next, previous, mute
    """
    import pyautogui
    keys = {"play_pause": "playpause", "next": "nexttrack", "previous": "prevtrack", "mute": "volumemute"}
    if action not in keys:
        return f"Неизвестное действие {action}"
    pyautogui.press(keys[action])
    return "Готово"


def type_text(text: str) -> str:
    """Печатает текст в активное окно (туда, где стоит курсор).

    Args:
        text: текст для ввода
    """
    import pyautogui
    import pyperclip
    old = pyperclip.paste()
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.3)
    pyperclip.copy(old)
    return "Напечатал"


def press_keys(keys: str) -> str:
    """Нажимает клавишу или сочетание клавиш.

    Args:
        keys: сочетание через плюс, например: ctrl+c, alt+tab, win+d, enter, f5
    """
    import pyautogui
    parts = [k.strip().lower() for k in keys.split("+") if k.strip()]
    pyautogui.hotkey(*parts)
    return f"Нажал {keys}"


def take_screenshot() -> str:
    """Делает скриншот экрана и сохраняет его в папку Изображения/Jarvis."""
    import pyautogui
    folder = HOME / "Pictures" / "Jarvis"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"screenshot_{datetime.datetime.now():%Y%m%d_%H%M%S}.png"
    pyautogui.screenshot().save(path)
    return f"Скриншот сохранён: {path}"


def find_files(name: str) -> str:
    """Ищет файлы по части имени на рабочем столе, в документах, загрузках, изображениях, видео и музыке.

    Args:
        name: часть имени файла
    """
    q = name.lower()
    roots = [HOME / d for d in ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music")]
    roots += [HOME / "OneDrive" / d for d in ("Desktop", "Documents")]
    found, deadline = [], time.time() + 6
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "node_modules"]
            for f in filenames:
                if q in f.lower():
                    found.append(os.path.join(dirpath, f))
                    if len(found) >= 8:
                        return "\n".join(found)
            if time.time() > deadline:
                break
    return "\n".join(found) if found else "Ничего не нашёл"


def open_path(path: str) -> str:
    """Открывает файл или папку программой по умолчанию.

    Args:
        path: полный путь к файлу или папке
    """
    try:
        os.startfile(path)
        return "Открываю"
    except OSError as e:
        return f"Не удалось открыть: {e}"


def system_status() -> str:
    """Возвращает загрузку процессора, памяти, видеокарты и свободное место на дисках."""
    lines = [
        f"Процессор {psutil.cpu_percent(interval=0.5):.0f}%",
        f"Память {psutil.virtual_memory().percent:.0f}%",
    ]
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=NO_WINDOW,
        ).stdout.strip()
        u, used, total, t = [x.strip() for x in out.split(",")]
        lines.append(f"Видеокарта {u}%, видеопамять {used} из {total} МБ, {t} градусов")
    except Exception:
        pass
    for part in psutil.disk_partitions():
        try:
            free = psutil.disk_usage(part.mountpoint).free / 2**30
            lines.append(f"Диск {part.device[:2]}: свободно {free:.0f} ГБ")
        except Exception:
            pass
    return "; ".join(lines)


def lock_computer() -> str:
    """Блокирует компьютер (экран входа)."""
    ctypes.windll.user32.LockWorkStation()
    return "Заблокировал"


def power_action(action: str) -> str:
    """Выключает, перезагружает компьютер или отправляет в сон. Спрашивает подтверждение.

    Args:
        action: одно из: shutdown, restart, sleep
    """
    names = {"shutdown": "Выключить компьютер", "restart": "Перезагрузить компьютер", "sleep": "Отправить компьютер в сон"}
    if action not in names:
        return f"Неизвестное действие {action}"
    if not _confirm(names[action] + "?"):
        return "Отменено пользователем"
    if action == "shutdown":
        subprocess.run(["shutdown", "/s", "/t", "5"], creationflags=NO_WINDOW)
    elif action == "restart":
        subprocess.run(["shutdown", "/r", "/t", "5"], creationflags=NO_WINDOW)
    else:
        subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], creationflags=NO_WINDOW)
    return "Выполняю"


def run_powershell(command: str) -> str:
    """Выполняет команду PowerShell и возвращает её вывод. Используй, только если другие функции не подходят. Спрашивает подтверждение.

    Args:
        command: команда PowerShell
    """
    log.warning("Запрос PowerShell: %s", command)
    if not _confirm(f"Выполнить команду: {command[:120]}?"):
        return "Отменено пользователем"
    full = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + command
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", full],
        capture_output=True, timeout=60, creationflags=NO_WINDOW,
    )
    out = (r.stdout + r.stderr).decode("utf-8", errors="replace").strip()
    return out[:1500] or "Выполнено, вывода нет"


# ======================= Что на экране =======================
GAME_MODE = False   # выставляет jarvis.py; в игре модель зрения выгружается сразу


def _keep_alive(v):
    return int(v) if isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()) else v


def look_at_screen(question: str = "Что на экране?") -> str:
    """Делает скриншот и смотрит на экран: описывает, что открыто, читает текст, ошибки, подсказывает, куда нажать.

    Args:
        question: что именно нужно узнать про экран (например: «какая тут ошибка», «что за окно открыто»)
    """
    import io

    import ollama
    import pyautogui
    if not config.VISION_MODEL:
        return "Зрение выключено на этом компьютере: не хватает видеопамяти (VISION_MODEL пустой в config.py)"
    img = pyautogui.screenshot()
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    r = ollama.Client(host=config.OLLAMA_HOST).chat(
        model=config.VISION_MODEL,
        messages=[{"role": "user", "images": [buf.getvalue()],
                   "content": question + " Это скриншот экрана пользователя. Отвечай по-русски, кратко и по делу."}],
        keep_alive=0 if GAME_MODE else _keep_alive(config.VISION_KEEP_ALIVE),
    )
    return r.message.content or "Не удалось разглядеть экран"


# ======================= Погода =======================
WMO = {
    0: "ясно", 1: "в основном ясно", 2: "переменная облачность", 3: "пасмурно",
    45: "туман", 48: "туман с изморозью", 51: "слабая морось", 53: "морось", 55: "сильная морось",
    56: "ледяная морось", 57: "ледяная морось", 61: "небольшой дождь", 63: "дождь", 65: "сильный дождь",
    66: "ледяной дождь", 67: "ледяной дождь", 71: "небольшой снег", 73: "снег", 75: "сильный снег",
    77: "снежная крупа", 80: "ливень", 81: "ливень", 82: "сильный ливень", 85: "снегопад",
    86: "сильный снегопад", 95: "гроза", 96: "гроза с градом", 99: "гроза с градом",
}


def _get_json(url: str):
    import json
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def weather(city: str = "") -> str:
    """Погода сейчас и прогноз на сегодня и завтра.

    Args:
        city: город; пусто — город пользователя по умолчанию
    """
    city = city.strip() or config.CITY
    city = {"москве": "Москва", "питере": "Санкт-Петербург",
            "санкт-петербурге": "Санкт-Петербург", "казани": "Казань"}.get(city.casefold(), city)
    geo = _get_json("https://geocoding-api.open-meteo.com/v1/search?count=1&language=ru&name="
                    + urllib.parse.quote(city))
    if not geo.get("results"):
        return f"Не нашёл город «{city}»"
    g = geo["results"][0]
    w = _get_json(
        f"https://api.open-meteo.com/v1/forecast?latitude={g['latitude']}&longitude={g['longitude']}"
        "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        "&timezone=auto&forecast_days=2&wind_speed_unit=ms"
    )
    c, d = w["current"], w["daily"]
    parts = [f"{g['name']}: сейчас {round(c['temperature_2m'])}°, ощущается как {round(c['apparent_temperature'])}°, "
             f"{WMO.get(c['weather_code'], 'без осадков')}, ветер {round(c['wind_speed_10m'])} м/с"]
    for i, day in enumerate(("сегодня", "завтра")):
        parts.append(f"{day} от {round(d['temperature_2m_min'][i])}° до {round(d['temperature_2m_max'][i])}°, "
                     f"{WMO.get(d['weather_code'][i], '')}, вероятность осадков {d['precipitation_probability_max'][i]}%")
    return "; ".join(parts)


# ======================= Поиск ответа в интернете =======================

def _wikipedia(query: str) -> str:
    q = urllib.parse.quote(query)
    found = _get_json(f"https://ru.wikipedia.org/w/api.php?action=opensearch&limit=1&format=json&search={q}")
    if not found[1]:
        return ""
    title = urllib.parse.quote(found[1][0].replace(" ", "_"))
    return _get_json(f"https://ru.wikipedia.org/api/rest_v1/page/summary/{title}").get("extract", "")


def search_internet(query: str) -> str:
    """Ищет ответ в интернете и возвращает найденные фрагменты, чтобы ты пересказал их. Используй для вопросов о фактах, новостях, событиях, людях, ценах, результатах — всего, что могло измениться или чего ты точно не знаешь.

    Args:
        query: поисковый запрос
    """
    try:
        from ddgs import DDGS
        res = DDGS(timeout=10).text(query, region="ru-ru", max_results=6)
        if res:
            return "\n".join(f"{r.get('title', '')}: {r.get('body', '')}" for r in res)[:3000]
    except Exception as e:
        log.warning("Поиск не удался (%s), пробую Википедию", e)
    try:
        return _wikipedia(query) or "Ничего не нашёл"
    except Exception as e:
        return f"Поиск недоступен: {e}"


# ======================= Таймеры и напоминания =======================
reminders = None   # объект Reminders, подставляет jarvis.py


def _fmt_left(seconds: float) -> str:
    m = int(seconds // 60)
    if m < 1:
        return f"через {int(seconds)} секунд"
    if m < 60:
        return f"через {m} минут"
    return f"через {m // 60} ч {m % 60} мин"


def set_timer(minutes: float, text: str = "") -> str:
    """Ставит таймер или напоминание через указанное время.

    Args:
        minutes: через сколько минут (можно дробное: 0.5 — это 30 секунд, 90 — полтора часа)
        text: о чём напомнить (можно пусто — тогда просто «время вышло»)
    """
    if reminders is None:
        return "Напоминания не запущены"
    sec = float(minutes) * 60
    if sec <= 0:
        return "Время должно быть больше нуля"
    reminders.add(time.time() + sec, text)
    return f"Таймер поставлен, сработает {_fmt_left(sec)}"


def set_alarm(time_hhmm: str, text: str = "") -> str:
    """Ставит будильник или напоминание на конкретное время: сегодня, а если это время уже прошло — завтра.

    Args:
        time_hhmm: время в формате ЧЧ:ММ, например 07:30 или 19:00
        text: о чём напомнить (можно пусто — тогда «будильник»)
    """
    if reminders is None:
        return "Напоминания не запущены"
    m = re.search(r"(\d{1,2})(?:[:.\s-]?(\d{2}))?", str(time_hhmm))
    if not m:
        return "Не понял время, нужен формат ЧЧ:ММ"
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if h > 23 or mi > 59:
        return "Неправильное время"
    now = datetime.datetime.now()
    at = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if at <= now:
        at += datetime.timedelta(days=1)
    reminders.add(at.timestamp(), text or "будильник")
    day = "сегодня" if at.date() == now.date() else "завтра"
    return f"Поставил на {day} в {at:%H:%M}"


def list_reminders() -> str:
    """Возвращает список активных таймеров, будильников и напоминаний."""
    if not reminders or not reminders.list():
        return "Активных напоминаний нет"
    now = time.time()
    return "; ".join(
        f"{datetime.datetime.fromtimestamp(i['at']):%H:%M} ({_fmt_left(i['at'] - now)}) — {i['text'] or 'таймер'}"
        for i in reminders.list()
    )


def cancel_reminder(text: str = "") -> str:
    """Отменяет напоминания.

    Args:
        text: часть текста напоминания, которое отменить; пусто — отменить все
    """
    if reminders is None:
        return "Напоминания не запущены"
    n = reminders.cancel(text)
    return f"Отменено напоминаний: {n}" if n else "Такого напоминания нет"


# ======================= Буфер обмена и окна =======================

def _clip_get():
    import ctypes
    from ctypes import wintypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.GetClipboardData.restype = wintypes.HANDLE
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    for _ in range(5):
        if u.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return None
    try:
        h = u.GetClipboardData(13)                     # CF_UNICODETEXT
        if not h:
            return ""
        ptr = k.GlobalLock(h)
        try:
            return ctypes.wstring_at(ptr) if ptr else ""
        finally:
            k.GlobalUnlock(h)
    finally:
        u.CloseClipboard()


def _clip_set(text):
    import ctypes
    from ctypes import wintypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    k.GlobalAlloc.restype = wintypes.HGLOBAL
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    data = (text + "\0").encode("utf-16-le")
    h = k.GlobalAlloc(0x0002, len(data))               # GMEM_MOVEABLE
    ctypes.memmove(k.GlobalLock(h), data, len(data))
    k.GlobalUnlock(h)
    for _ in range(5):
        if u.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return False
    try:
        u.EmptyClipboard()
        u.SetClipboardData(13, h)
        return True
    finally:
        u.CloseClipboard()


def read_clipboard() -> str:
    """Возвращает текст, который пользователь скопировал (буфер обмена). Вызывай для просьб вроде
    «переведи / объясни / перескажи / исправь то, что я скопировал» — и дальше работай с этим текстом."""
    try:
        text = _clip_get()
    except Exception as e:
        return f"Не удалось прочитать буфер обмена: {e}"
    if text is None:
        return "Буфер обмена занят другой программой"
    if not text.strip():
        return "В буфере обмена нет текста"
    return text[:6000] + ("\n[…текст обрезан]" if len(text) > 6000 else "")


def copy_to_clipboard(text: str) -> str:
    """Кладёт текст в буфер обмена, чтобы пользователь мог вставить его (Ctrl+V). Используй для готового
    перевода, исправленного текста, ответа, который удобнее вставить, чем слушать."""
    try:
        return "Скопировала в буфер обмена" if _clip_set(str(text)) else "Буфер обмена занят"
    except Exception as e:
        return f"Не удалось скопировать: {e}"


def active_window() -> str:
    """Заголовок окна, которое сейчас на переднем плане (для контекста, не функция для модели)."""
    try:
        import ctypes
        u = ctypes.windll.user32
        h = u.GetForegroundWindow()
        n = u.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, buf, n + 1)
        return buf.value.strip()
    except Exception:
        return ""


TOOLS = [
    get_time, open_app, close_app, launch_game, list_games, open_website, web_search,
    set_volume, get_volume, media_control, type_text, press_keys,
    take_screenshot, find_files, open_path, system_status,
    lock_computer, power_action, run_powershell,
    look_at_screen, weather, search_internet,
    set_timer, set_alarm, list_reminders, cancel_reminder,
    read_clipboard, copy_to_clipboard,
]

# Долгая память
import memory  # noqa: E402
TOOLS += memory.TOOLS

# Minecraft-напарник
import minecraft_tools  # noqa: E402
TOOLS += minecraft_tools.TOOLS
