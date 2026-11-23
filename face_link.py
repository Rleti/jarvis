"""Связь Джарвиса с окном Джарвис-тян: открыть окно, сообщать состояние и субтитры."""
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time

import config

log = logging.getLogger("jarvis.face")
_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_enabled = False


def _send(**msg):
    if not _enabled:
        return
    try:
        _sock.sendto(json.dumps(msg, ensure_ascii=False).encode("utf-8"),
                     ("127.0.0.1", getattr(config, "FACE_PORT", 3006)))
    except OSError:
        pass


def state(name):
    _send(state=name)


def emotion(name):
    _send(emotion=name)


def user(text):
    _send(user=text)


def reply(text, duration=None, mouth=None):
    """mouth — громкость голоса по 60 мс ('0'/'1'/'2'): окно двигает ртом в такт звуку."""
    _send(reply=text, duration=duration, mouth=mouth or "")


def _heartbeat():
    while True:
        _send(beat=1)
        time.sleep(3)


def start():
    """Открывает отдельное окно консоли с анимацией (если включено в config)."""
    global _enabled
    if not getattr(config, "FACE_WINDOW", False):
        return
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):          # нужна консоль, а не «тихий» python
        exe = exe[:-len("pythonw.exe")] + "python.exe"
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "face_window.py")
    si = None
    if os.name == "nt" and getattr(config, "FACE_MAXIMIZED", True):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 3                               # SW_MAXIMIZE — окно сразу на весь экран
    try:
        subprocess.Popen([exe, script], creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                         cwd=os.path.dirname(script), startupinfo=si)
    except OSError as e:
        log.warning("Не удалось открыть окно с анимацией: %s", e)
        return
    _enabled = True
    threading.Thread(target=_heartbeat, daemon=True).start()
    log.info("Окно с анимацией открыто")


def stop():
    _send(quit=1)
