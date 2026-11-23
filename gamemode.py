"""Игровой режим: если запущена игра — освобождаем видеопамять, после игры возвращаем как было."""
import logging
import os
import threading
import time

import psutil

import config

log = logging.getLogger("jarvis.gamemode")


class GameMode(threading.Thread):
    def __init__(self, on_change):
        super().__init__(daemon=True)
        self.on_change = on_change      # функция(active: bool, game: str | None)
        self.active = False
        self.dirs, self.dirs_time = [], 0.0

    def _game_dirs(self):
        """Папки установленных Steam-игр (обновляются раз в 5 минут)."""
        if time.time() - self.dirs_time > 300:
            from tools import _steam_games
            self.dirs = [os.path.normcase(g[3]) + os.sep for g in _steam_games() if g[3]]
            self.dirs_time = time.time()
        return self.dirs

    def detect(self):
        dirs = self._game_dirs()
        extra = {n.lower() for n in config.GAME_PROCESSES}
        ignore = [n.lower() for n in config.GAME_IGNORE]
        for p in psutil.process_iter(["name", "exe"]):
            name = (p.info["name"] or "").lower()
            if not name or any(i in name for i in ignore):
                continue
            if name in extra:
                return p.info["name"]
            exe = os.path.normcase(p.info["exe"] or "")
            if exe and any(exe.startswith(d) for d in dirs):
                return p.info["name"]
        return None

    def run(self):
        while True:
            try:
                game = self.detect()
                if game and not self.active:
                    self.active = True
                    log.info("Игровой режим ВКЛ: %s", game)
                    self.on_change(True, game)
                elif not game and self.active:
                    self.active = False
                    log.info("Игровой режим ВЫКЛ")
                    self.on_change(False, None)
            except Exception:
                log.exception("Ошибка игрового режима")
            time.sleep(10)
