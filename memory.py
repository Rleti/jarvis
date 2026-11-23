"""Долгая память Джарвиса: факты о пользователе, которые переживают перезапуск (файл memory.json)."""
import json
import logging
import os
import re
import threading
import time

log = logging.getLogger("jarvis.memory")
FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.json")
MAX_FACTS = 80
_lock = threading.Lock()


def _load():
    try:
        with open(FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(facts):
    tmp = FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(facts, f, ensure_ascii=False, indent=1)
    os.replace(tmp, FILE)


def _words(s):
    return set(re.findall(r"[a-zа-яё0-9]{3,}", s.lower()))


def facts():
    with _lock:
        return [f["text"] for f in _load()]


def as_text():
    items = facts()
    if not items:
        return ""
    return "Что ты помнишь о пользователе (используй, когда к месту):\n" + "\n".join(f"- {t}" for t in items)


def remember_fact(fact: str) -> str:
    """Запомнить надолго факт о пользователе: имя, предпочтения, расписание, близких, планы.
    Вызывай, когда пользователь просит запомнить или сообщает о себе что-то важное и долговременное.
    fact — короткая фраза от третьего лица, например «Любит зелёный чай» или «Пары по вторникам с 9:00»."""
    fact = " ".join(str(fact).split()).strip(" .")
    if not fact:
        return "Нечего запоминать"
    with _lock:
        items = _load()
        new = _words(fact)
        # похожий факт заменяем новым (например, сменилось расписание)
        for i, f in enumerate(items):
            old = _words(f["text"])
            if old and new and len(old & new) / max(1, min(len(old), len(new))) >= 0.7:
                items[i] = {"text": fact, "ts": time.time()}
                _save(items)
                log.info("Память: обновлено «%s»", fact)
                return f"Обновила в памяти: {fact}"
        items.append({"text": fact, "ts": time.time()})
        items = items[-MAX_FACTS:]
        _save(items)
    log.info("Память: запомнено «%s»", fact)
    return f"Запомнила: {fact}"


def forget_fact(about: str) -> str:
    """Забыть факты о пользователе по теме. about — о чём забыть («про чай», «расписание»); «всё» — очистить память."""
    about = str(about).strip().lower()
    with _lock:
        items = _load()
        if about in ("всё", "все", "all", "*"):
            _save([])
            return f"Забыла всё ({len(items)} фактов)"
        keys = _words(about)
        keep = [f for f in items if not (keys & _words(f["text"]))]
        removed = len(items) - len(keep)
        _save(keep)
    return f"Забыла фактов: {removed}" if removed else "Ничего такого в памяти не нашла"


TOOLS = [remember_fact, forget_fact]
