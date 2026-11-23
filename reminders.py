"""Таймеры, будильники и напоминания. Хранятся в reminders.json — переживают перезапуск."""
import json
import logging
import os
import threading
import time
import uuid

log = logging.getLogger("jarvis.reminders")
FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reminders.json")
MISSED_LIMIT = 12 * 3600   # пропущенные (комп был выключен) напоминаем, если опоздали не больше чем на 12 ч


class Reminders:
    def __init__(self, announce):
        self.announce = announce          # функция(text, missed) — озвучивает напоминание
        self.lock = threading.Lock()
        self.items = self._load()
        threading.Thread(target=self._loop, daemon=True).start()

    def _load(self):
        try:
            with open(FILE, encoding="utf-8") as f:
                items = json.load(f)
            return [i for i in items if i["at"] > time.time() - MISSED_LIMIT]
        except (OSError, ValueError):
            return []

    def _save(self):
        try:
            with open(FILE, "w", encoding="utf-8") as f:
                json.dump(self.items, f, ensure_ascii=False, indent=1)
        except OSError:
            log.exception("Не удалось сохранить напоминания")

    def add(self, at: float, text: str):
        with self.lock:
            self.items.append({"id": uuid.uuid4().hex[:8], "at": at, "text": text})
            self._save()

    def list(self):
        with self.lock:
            return sorted(self.items, key=lambda i: i["at"])

    def cancel(self, query: str = "") -> int:
        q = query.lower().strip()
        with self.lock:
            keep = [i for i in self.items if q and q not in i["text"].lower()]
            removed = len(self.items) - len(keep)
            self.items = keep
            self._save()
        return removed

    def _loop(self):
        while True:
            time.sleep(1)
            now = time.time()
            with self.lock:
                due = [i for i in self.items if i["at"] <= now]
                if due:
                    self.items = [i for i in self.items if i["at"] > now]
                    self._save()
            for item in due:
                missed = now - item["at"] > 60
                log.info("Напоминание: %s", item["text"])
                try:
                    self.announce(item["text"], missed)
                except Exception:
                    log.exception("Не удалось озвучить напоминание")
