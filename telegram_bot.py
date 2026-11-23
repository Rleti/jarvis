"""Связь с Джарвисом через Telegram-бота: текст и голосовые туда и обратно, скриншот, напоминания.

Настройка (один раз):
  1. В Telegram открой @BotFather → /newbot → придумай имя → получишь токен вида 123456:ABC...
  2. Впиши его в config.py: TG_TOKEN = "123456:ABC..." и перезапусти Джарвиса.
  3. В логе (и в трее → «Веб-интерфейс») появится код привязки из 6 цифр — отправь его своему боту.
     После этого бот слушается только тебя; чужим он отвечает отказом.
"""
import io
import json
import logging
import os
import random
import threading
import time
import urllib.parse
import urllib.request
import uuid
import wave

import config

log = logging.getLogger("jarvis.tg")
HERE = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(HERE, "tg_users.json")
PAIR_CODE = ""

_a = None                 # Assistant
_opener = None
_api = ""
_users = {}               # chat_id(str) -> {"voice": bool, "pc": bool}
_lock = threading.Lock()  # по одному сообщению за раз

HELP = ("Пиши или отправляй голосовые — отвечу как дома 💬\n\n"
        "/voice — присылать ответы голосом (вкл/выкл)\n"
        "/pc — говорить ответы ещё и вслух на компьютере (вкл/выкл)\n"
        "/screen — скриншот экрана компьютера\n"
        "/pause — пауза / продолжить голосовое управление дома")


# ---------- Telegram API ----------
def _call(method, params=None, files=None, timeout=40):
    url = f"{_api}/{method}"
    if files:
        boundary = uuid.uuid4().hex
        body = io.BytesIO()
        for k, v in (params or {}).items():
            body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        for k, (fname, data, ctype) in files.items():
            body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{fname}"\r\n'
                       f'Content-Type: {ctype}\r\n\r\n'.encode())
            body.write(data)
            body.write(b"\r\n")
        body.write(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(url, data=body.getvalue(),
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    else:
        req = urllib.request.Request(url, data=json.dumps(params or {}).encode(),
                                     headers={"Content-Type": "application/json"})
    with _opener.open(req, timeout=timeout) as r:
        res = json.loads(r.read())
    if not res.get("ok"):
        raise RuntimeError(res.get("description", "ошибка Telegram"))
    return res["result"]


def _download(file_id):
    path = _call("getFile", {"file_id": file_id})["file_path"]
    base = _api.replace("/bot", "/file/bot", 1)
    with _opener.open(f"{base}/{path}", timeout=60) as r:
        return r.read()


def send_text(chat, text):
    for i in range(0, len(text) or 1, 4000):
        _call("sendMessage", {"chat_id": chat, "text": text[i:i + 4000] or "…"})


def _action(chat, kind):
    try:
        _call("sendChatAction", {"chat_id": chat, "action": kind}, timeout=10)
    except Exception:
        pass


# ---------- звук ----------
def _ogg_opus(audio, sr):
    """numpy float -> голосовое сообщение (OGG/Opus) через PyAV (ставится вместе с faster-whisper)."""
    import av
    import numpy as np
    buf = io.BytesIO()
    with av.open(buf, "w", format="ogg") as out:
        try:
            st = out.add_stream("libopus", rate=48000, layout="mono")
        except TypeError:                         # старые версии PyAV
            st = out.add_stream("libopus", rate=48000)
            st.codec_context.layout = "mono"
        if sr != 48000:
            idx = np.linspace(0, len(audio) - 1, int(len(audio) * 48000 / sr))
            audio = np.interp(idx, np.arange(len(audio)), audio)
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16).reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(pcm, format="s16", layout="mono")
        frame.sample_rate = 48000
        for p in st.encode(frame):
            out.mux(p)
        for p in st.encode(None):
            out.mux(p)
    return buf.getvalue()


def _wav(audio, sr):
    import numpy as np
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def send_voice(chat, text):
    import tts as tts_mod
    with _a.tts_lock:
        audio = _a.tts.synth(text)
    if audio is None:
        return
    try:
        _call("sendVoice", {"chat_id": chat}, {"voice": ("voice.ogg", _ogg_opus(audio, tts_mod.SR), "audio/ogg")},
              timeout=90)
    except Exception as e:
        log.warning("Голосовое не собралось (%s), шлю аудиофайлом", e)
        _call("sendAudio", {"chat_id": chat, "title": "Ответ"},
              {"audio": ("reply.wav", _wav(audio, tts_mod.SR), "audio/wav")}, timeout=90)


def _transcribe_voice(data):
    from faster_whisper import decode_audio
    audio = decode_audio(io.BytesIO(data), sampling_rate=16000)
    return _a.stt.transcribe(audio).strip()


# ---------- пользователи ----------
def _load_users():
    global _users
    try:
        with open(USERS_FILE, encoding="utf-8") as f:
            _users = json.load(f)
    except (OSError, ValueError):
        _users = {}
    for cid in getattr(config, "TG_ALLOWED", []) or []:
        _users.setdefault(str(cid), {})


def _save_users():
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(_users, f, ensure_ascii=False, indent=1)


def _settings(chat):
    u = _users.setdefault(str(chat), {})
    u.setdefault("voice", bool(getattr(config, "TG_VOICE_REPLY", True)))
    u.setdefault("pc", bool(getattr(config, "TG_SPEAK_ON_PC", False)))
    return u


def notify(text):
    """Напоминания и прочие сообщения — всем привязанным."""
    if not _api:
        return
    for chat in list(_users):
        try:
            send_text(chat, text)
        except Exception as e:
            log.warning("Telegram: не отправилось (%s)", e)


# ---------- обработка сообщений ----------
def _handle(msg):
    global PAIR_CODE
    chat = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    if str(chat) not in _users:
        if PAIR_CODE and text == PAIR_CODE:
            _users[str(chat)] = {}
            _save_users()
            PAIR_CODE = ""
            log.info("Telegram: привязан чат %s (%s)", chat, msg["chat"].get("first_name", ""))
            send_text(chat, "Привязала! Теперь я слушаюсь только тебя, сенпай ✨\n\n" + HELP)
        else:
            send_text(chat, "Я тебя не знаю. Отправь код привязки из лога Джарвиса на компьютере.")
        return
    s = _settings(chat)
    if text.startswith("/"):
        cmd = text.split()[0].split("@")[0].lower()
        if cmd in ("/start", "/help"):
            send_text(chat, HELP)
        elif cmd == "/voice":
            s["voice"] = not s["voice"]
            _save_users()
            send_text(chat, "Буду отвечать голосом 🎙" if s["voice"] else "Отвечаю только текстом")
        elif cmd == "/pc":
            s["pc"] = not s["pc"]
            _save_users()
            send_text(chat, "Ответы звучат и на компьютере 🔊" if s["pc"] else "На компьютере молчу")
        elif cmd == "/screen":
            import pyautogui
            buf = io.BytesIO()
            img = pyautogui.screenshot()
            img.thumbnail((1920, 1920))
            img.convert("RGB").save(buf, "JPEG", quality=80)
            _call("sendPhoto", {"chat_id": chat}, {"photo": ("screen.jpg", buf.getvalue(), "image/jpeg")}, timeout=60)
        elif cmd == "/pause":
            if _a.paused.is_set():
                _a.paused.clear()
            else:
                _a.paused.set()
            send_text(chat, "Голос дома на паузе ⏸" if _a.paused.is_set() else "Снова слушаю дома ▶")
        else:
            send_text(chat, HELP)
        return

    if msg.get("voice") or msg.get("audio"):
        _action(chat, "typing")
        try:
            text = _transcribe_voice(_download((msg.get("voice") or msg["audio"])["file_id"]))
        except Exception as e:
            log.exception("Telegram: не распознала голосовое")
            send_text(chat, f"Не смогла разобрать голосовое: {e}")
            return
        if not text:
            send_text(chat, "Ничего не расслышала 🙉")
            return
        send_text(chat, f"🎤 «{text}»")
    if not text:
        return

    _action(chat, "typing")
    parts = []
    _a.answer(text, mode="pc" if s["pc"] else "quiet", on_part=parts.append, src="telegram")
    reply = " ".join(parts).strip()
    import re
    reply = re.sub(r"\s*\[\w+\]\s*", " ", reply).strip() or "…"
    send_text(chat, reply)
    if s["voice"]:
        _action(chat, "record_voice")
        try:
            send_voice(chat, reply)
        except Exception:
            log.exception("Telegram: голосовой ответ")


def _loop():
    offset = 0
    errors = 0
    while not _a.stopped.is_set():
        try:
            updates = _call("getUpdates", {"offset": offset, "timeout": 30,
                                           "allowed_updates": ["message"]}, timeout=45)
            errors = 0
        except Exception as e:
            errors += 1
            if errors in (1, 10):
                log.warning("Telegram недоступен: %s (если заблокирован — пропиши TG_PROXY в config.py)", e)
            time.sleep(min(60, 3 * errors))
            continue
        for up in updates:
            offset = up["update_id"] + 1
            msg = up.get("message")
            if not msg:
                continue

            def work(m=msg):
                with _lock:
                    try:
                        _handle(m)
                    except Exception as e:
                        log.exception("Telegram: ошибка")
                        try:
                            send_text(m["chat"]["id"], f"Ой, ошибка: {e}")
                        except Exception:
                            pass
            threading.Thread(target=work, daemon=True).start()


def start(assistant):
    global _a, _opener, _api, PAIR_CODE
    token = getattr(config, "TG_TOKEN", "")
    if not token:
        return False
    _a = assistant
    handlers = []
    proxy = getattr(config, "TG_PROXY", "")
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"https": proxy, "http": proxy}))
    _opener = urllib.request.build_opener(*handlers)
    _api = f"https://api.telegram.org/bot{token}"
    _load_users()
    try:
        me = _call("getMe", timeout=15)
        log.info("Telegram: бот @%s на связи", me.get("username"))
    except Exception as e:
        log.warning("Telegram: не удалось подключиться (%s) — проверь TG_TOKEN / TG_PROXY", e)
    if not _users:
        PAIR_CODE = f"{random.randint(0, 999999):06d}"
        log.info("Telegram: отправь боту код привязки %s", PAIR_CODE)
    threading.Thread(target=_loop, daemon=True, name="telegram").start()
    return True
