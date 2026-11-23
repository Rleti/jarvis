"""Окно с Джарвис-тян в консоли. Запускается самим Джарвисом (config.FACE_WINDOW).

Слушает UDP 127.0.0.1:<порт> сообщения {"state": ..., "user": ..., "reply": ...}
и рисует анимацию: моргание, рот при разговоре, «слушаю», «думаю» + субтитры.
Закрывается сам, если Джарвис перестал присылать сигналы.
"""
import json
import os
import random
import shutil
import socket
import sys
import textwrap
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config      # noqa: E402
import numpy as np  # noqa: E402
import face_art    # noqa: E402

PORT = getattr(config, "FACE_PORT", 3006)
STYLE = getattr(config, "FACE_STYLE", "braille")
NAME = getattr(config, "FACE_NAME", "Джарвис-тян")

PINK, CYAN, GREY, WHITE, RESET = "\x1b[38;5;218m", "\x1b[38;5;117m", "\x1b[38;5;245m", "\x1b[97m", "\x1b[0m"
STATUS = {
    "idle": (GREY, "♡ жду команду — держи правый Ctrl"),
    "listen": (CYAN, "● слушаю..."),
    "think": (PINK, "… думаю"),
    "talk": (PINK, "♪ говорю"),
    "sleep": (GREY, "z z z"),
}


BOX_LINES = 4


SCENE_BOX = "\x1b[48;2;14;8;14m"      # тёмный фон окна диалога в режиме сцены
SCENE_RED = "\x1b[38;2;214;64;78m"
SCENE_TEAL = "\x1b[38;2;80;210;200m"
SCENE_TEXT = "\x1b[38;2;236;214;214m"


def dialog_box(who, text, width, typing=False, scene=False):
    """Рамка с табличкой имени и текстом (последние строки, если не влезает)."""
    inner = width - 4
    name_col = (SCENE_TEAL if scene else CYAN) if who == "Ты" else (SCENE_RED if scene else PINK)
    border = (SCENE_BOX + name_col) if scene else name_col
    text_col = (SCENE_BOX + SCENE_TEXT) if scene else WHITE
    wrapped = textwrap.wrap(("- " + text) if text else "", inner) or [""]
    lines = wrapped[-BOX_LINES:]
    if typing and lines:
        lines[-1] = lines[-1] + "▌"
    lines += [""] * (BOX_LINES - len(lines))
    tag = f" {who} "
    top = border + "╔═" + "\x1b[1m" + tag + "\x1b[22m" + border + "═" * (width - 3 - len(tag)) + "╗" + RESET
    body = [border + "║ " + text_col + l.ljust(inner)[:inner] + border + " ║" + RESET for l in lines]
    bottom = border + "╚" + "═" * (width - 2) + "╝" + RESET
    return [top] + body + [bottom]


LOG_RE = __import__("re").compile(r"^\d{4}-\d\d-\d\d (\d\d:\d\d):\d\d,\d+ (\w+) ([\w.]+): (.*)")
LOG_SKIP = ("httpx", "pySBD", "Segmenters", "TTS.", "faster_whisper", "huggingface")


class LogTail:
    """Следит за jarvis.log и отдаёт последние строки, ужатые под экран монитора."""
    def __init__(self, path, width=35, keep=10):
        self.path, self.width, self.keep = path, width, keep
        self.pos, self.lines = 0, []
        try:
            size = os.path.getsize(path)
            self.pos = max(0, size - 4000)            # при старте — хвост лога
        except OSError:
            pass

    def poll(self):
        try:
            size = os.path.getsize(self.path)
            if size < self.pos:
                self.pos = 0                          # лог пересоздан
            with open(self.path, encoding="utf-8", errors="ignore") as f:
                f.seek(self.pos)
                new = f.read()
                self.pos = f.tell()
        except OSError:
            return self.lines
        for raw in new.splitlines():
            m = LOG_RE.match(raw)
            if not m or any(k in m.group(3) or k in m.group(4) for k in LOG_SKIP):
                continue
            hhmm, level, _, msg = m.groups()
            mark = "!" if level in ("WARNING", "ERROR") else ">"
            for i, part in enumerate(textwrap.wrap(f"{mark}{hhmm} {msg}", self.width) or [""]):
                self.lines.append(part if i == 0 else " " + part)
        self.lines = self.lines[-self.keep * 3:]
        return self.lines[-self.keep:]


def runs(cols, gap=6):
    """Изменённые столбцы -> отрезки [c0, c1); близкие куски склеиваем."""
    out = []
    for c in cols:
        c = int(c)
        if out and c - out[-1][1] <= gap:
            out[-1][1] = c + 1
        else:
            out.append([c, c + 1])
    return out


def face_scene_span(*a):
    import face_scene
    return face_scene.span(*a)


def main():
    os.system("")                                    # включает ANSI-цвета в старой консоли Windows
    if os.name == "nt":
        os.system(f"title {NAME}")
        if not getattr(config, "FACE_SCENE", False):
            os.system("mode con cols=80 lines=54 >nul 2>&1")
        # окно разворачивает Джарвис при запуске (face_link). ShowWindow здесь НЕ вызываем: в Windows Terminal
        # GetConsoleWindow — невидимое служебное окно, развернув его, мы накрывали монитор «стеклом»
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), getattr(config, "FACE_FOLDER", "face"))
    try:
        frames = face_art.load_frames(STYLE, folder, getattr(config, "FACE_INVERT", False),
                                      width_chars=getattr(config, "FACE_WIDTH", 75),
                                      mode=getattr(config, "FACE_MODE", "dither"))
    except Exception as e:                           # битая картинка — показываем встроенную
        print("Не удалось загрузить картинку:", e)
        frames = face_art.all_frames(STYLE)
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis.log")
    logs = LogTail(log_path)
    scene, scene_size, char_imgs = None, None, None
    prev, last_status = None, ""
    use_scene = getattr(config, "FACE_SCENE", False)

    def term():
        t = shutil.get_terminal_size((118, 54))
        return max(40, t.columns - 1), max(16, t.lines - 1)      # последний столбец не трогаем: без переноса строк

    def build_scene(size):
        nonlocal scene, scene_size, char_imgs, logs, prev
        try:
            import face_scene
            if char_imgs is None:
                char_imgs = face_scene.character_images(folder, list(frames))
            sys.stdout.write("\x1b[2J\x1b[H" + GREY + "  перерисовываю сцену…" + RESET)
            sys.stdout.flush()
            scene = face_scene.Scene(char_imgs, cols=size[0], rows=size[1],
                                     source_color=getattr(config, "FACE_SOURCE_COLOR", 0.0))
            scene.set_period(face_scene.period_now())
            logs = LogTail(log_path, width=max(10, scene.screen_cols - 1), keep=max(3, scene.screen_rows))
        except Exception as e:                       # нет numpy или что-то с картинками — обычный режим
            print("Сцена не загрузилась:", e)
            scene = None
        prev = None
        scene_size = size
        sys.stdout.write("\x1b[2J")

    if use_scene:
        build_scene(term())
    pending_size, pending_since = None, 0.0
    hwnd, is_iconic = 0, None
    if os.name == "nt":
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            is_iconic = ctypes.windll.user32.IsIconic
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                hwnd = 0                                 # Windows Terminal: служебное окно, не трогаем
        except Exception:
            hwnd = 0
    tick = 0
    log_lines, next_log = [], 0.0
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for _ in range(40):
        try:
            sock.bind(("127.0.0.1", PORT))
            break
        except OSError:                              # порт занят старым окном — просим его закрыться
            try:
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'{"quit": 1}', ("127.0.0.1", PORT))
            except OSError:
                pass
            time.sleep(0.25)
    sock.setblocking(False)

    state, last_beat = "idle", time.time()
    emotion, emotion_until = "neutral", 0.0          # эмоция держится несколько секунд после ответа
    look, look_until, next_look = None, 0.0, time.time() + 5
    gesture_until = 0.0
    # диалоговое окно как в визуальной новелле
    box_who, box_text, box_shown, box_speed = "", "", 0.0, 16.0
    last_reply, last_frame = 0.0, time.time()
    next_blink, blink_until = time.time() + 3, 0.0
    talk_flip = 0
    mouth, mouth_t0 = "", 0.0                         # липсинк: громкость голоса по 60 мс
    next_period, yawn_until, next_yawn = 0.0, 0.0, time.time() + 90
    sys.stdout.write("\x1b[2J\x1b[?25l\x1b[?7l")    # очистить экран, спрятать курсор, без автопереноса

    while True:
        # --- новые сообщения от Джарвиса ---
        while True:
            try:
                data, _ = sock.recvfrom(65536)
            except (BlockingIOError, OSError):
                break
            try:
                msg = json.loads(data.decode("utf-8"))
            except ValueError:
                continue
            last_beat = time.time()
            if msg.get("quit"):
                sys.stdout.write("\x1b[?25h\x1b[?7h" + RESET)
                return
            if msg.get("state"):
                state = msg["state"]
                if state == "talk":
                    emotion_until = time.time() + 600       # пока говорит — эмоция держится
                elif state == "idle" and emotion != "neutral":
                    emotion_until = time.time() + 6         # после ответа ещё 6 секунд
            if msg.get("emotion"):
                emotion = msg["emotion"] if msg["emotion"] in face_art.EMOTIONS else "neutral"
                emotion_until = time.time() + 600
                if emotion == "wave":
                    gesture_until = time.time() + 3
            if msg.get("user"):
                box_who, box_text = "Ты", msg["user"]
                box_shown = len(box_text)
            if msg.get("reply"):
                text = msg["reply"]
                dur = msg.get("duration") or 0
                if box_who == NAME and time.time() - last_reply < 8:
                    box_text = box_text + " " + text          # следующее предложение того же ответа
                else:
                    box_who, box_text, box_shown = NAME, text, 0.0
                box_speed = len(text) / dur if dur > 0.3 else 16.0   # печатаем в темп голоса
                last_reply = time.time()
                mouth, mouth_t0 = msg.get("mouth") or "", time.time()

        if time.time() - last_beat > 15:             # Джарвис закрылся — закрываемся и мы
            sys.stdout.write("\x1b[?25h\x1b[?7h" + RESET)
            return

        # --- выбор кадра ---
        now = time.time()
        dt, last_frame = now - last_frame, now
        if box_shown < len(box_text):
            box_shown = min(len(box_text), box_shown + box_speed * dt)
        if now > emotion_until:
            emotion = "neutral"
        emo = emotion
        if emo == "wave" and now > gesture_until:        # помахала — дальше просто радуется
            emo = "happy"
        # время суток: свет в комнате; глубокой ночью она сонная — чаще моргает и зевает
        hour = time.localtime(now).tm_hour
        sleepy = 0 <= hour < 5
        if scene and now > next_period:
            next_period = now + 30
            import face_scene
            if scene.set_period(face_scene.period_now()):
                prev = None
        if now > next_blink:
            blink_until = now + (0.3 if sleepy else 0.15)
            next_blink = now + (random.uniform(1.5, 3.5) if sleepy else random.uniform(2.5, 6))
        if sleepy and state == "idle" and emo == "neutral" and now > next_yawn:
            yawn_until, next_yawn = now + 1.8, now + random.uniform(60, 150)
        if state == "idle" and emo == "neutral" and now > next_look:   # в простое поглядывает по сторонам
            look = random.choice(["look_left", "look_right", "look_up", "look_left", "look_right"])
            look_until, next_look = now + random.uniform(0.8, 1.6), now + random.uniform(4, 10)
        if state == "talk":
            i = int((now - mouth_t0) / 0.06)
            if mouth and i < len(mouth):                 # рот открывается в такт громкости голоса
                frame = (emo, f"{emo}_talk1", f"{emo}_talk2")[int(mouth[i])]
            elif mouth:
                frame = emo                              # фраза доиграла — рот закрыт
            else:
                talk_flip = (talk_flip + 1) % 4
                frame = (f"{emo}_talk1", f"{emo}_talk2", f"{emo}_talk1", emo)[talk_flip]
        elif now < yawn_until:                           # зевает: рот широко, в конце жмурится
            frame = "surprised_talk2" if yawn_until - now > 0.5 else "blink"
        elif state == "think":
            frame = "think"
        elif state == "listen":
            frame = "listen"
        elif state == "sleep":
            frame = "blink"
        elif emo != "neutral":
            frame = "blink" if now < blink_until and emo not in ("happy", "wink", "wave") else emo
        elif now < look_until and look:
            frame = look
        else:
            frame = "blink" if now < blink_until else "idle"
        if frame.startswith("wave") and int(now * 3) % 2:
            alternate = frame.replace("wave", "wave_alt", 1)
            if alternate in frames:
                frame = alternate
        frame = frame if frame in frames else "idle"

        # --- окно поменяло размер: ждём, пока перестанут тянуть, и пересобираем сцену ---
        if use_scene:
            size = term()
            if size != scene_size:
                if size != pending_size:
                    pending_size, pending_since = size, now
                    sys.stdout.write("\x1b[2J")           # стираем «хвосты» старой картинки сразу
                elif now - pending_since > 0.4:
                    build_scene(size)
                    pending_size = None
                time.sleep(0.05)
                continue

        # --- свёрнуто — не рисуем вовсе ---
        if hwnd and is_iconic(hwnd):
            prev = None
            time.sleep(0.25)
            continue

        # --- отрисовка ---
        width = max(60, min(shutil.get_terminal_size((80, 56)).columns - 2, 100))
        tick = int(now / 0.12)                           # анимация комнаты не зависит от частоты кадров
        if scene:
            # рисуем только изменившиеся куски: целиком на весь экран это мегабайты в секунду
            if now > next_log:
                log_lines, next_log = logs.poll(), now + 0.5
            chars, fg, bg = scene.arrays(frame, tick, log_lines if getattr(config, "FACE_LOGS", True) else None)
            box_rows = {}
            if box_text:
                box = dialog_box(box_who, box_text[:int(box_shown)], scene.cols,
                                 typing=box_shown < len(box_text), scene=True)
                start = max(0, scene.rows - len(box))
                box_rows = {start + i: line for i, line in enumerate(box)}
            out = []
            pbox = prev[3] if prev else {}
            if prev is None:
                out.append("\x1b[2J")
                diff = np.ones(chars.shape, bool)
            else:
                pc, pf, pb, _ = prev
                diff = (chars != pc) | (fg != pf).any(-1) | (bg != pb).any(-1)
                for r in pbox:
                    if r not in box_rows:
                        diff[r] = True                   # окно диалога исчезло — вернуть картинку
            for r in range(scene.rows):
                if r in box_rows:
                    if prev is None or pbox.get(r) != box_rows[r]:
                        out.append(f"\x1b[{r + 1};1H" + box_rows[r] + RESET + "\x1b[K")
                    continue
                for c0, c1 in runs(np.flatnonzero(diff[r])):
                    out.append(f"\x1b[{r + 1};{c0 + 1}H" + face_scene_span(chars, fg, bg, r, c0, c1) + RESET)
            color, text = STATUS.get(state, STATUS["idle"])
            status = color + f"  {text}" + RESET + "\x1b[K"
            if prev is None or status != last_status:
                out.append(f"\x1b[{scene.rows + 1};1H" + status)
                last_status = status
            prev = (chars, fg, bg, box_rows)
            if out:
                sys.stdout.write("".join(out))
                sys.stdout.flush()
            time.sleep(0.05 if state == "talk" else 0.12)    # пока говорит — чаще, чтобы рот успевал
            continue
        out = ["\x1b[H"]
        if scene:
            if now > next_log:
                log_lines, next_log = logs.poll(), now + 0.5
            art = scene.render(frame, tick, log_lines if getattr(config, "FACE_LOGS", True) else None)
            art_w = scene.cols
        else:
            art = [PINK + line + RESET for line in frames[frame]]
            art_w = max(len(l) for l in frames[frame])
        if box_text:
            box = dialog_box(box_who, box_text[:int(box_shown)],
                             art_w if scene else max(40, min(art_w, width)),
                             typing=box_shown < len(box_text), scene=bool(scene))
            start = max(0, len(art) - len(box) + 2)          # окно поверх нижней части картинки
            art = art[:start] + box + art[start + len(box):]
        for line in art:
            out.append(line + RESET + "\x1b[K\n")
        color, text = STATUS.get(state, STATUS["idle"])
        out.append(color + f"  {text}" + RESET + "\x1b[K\n")
        out.append("\x1b[J")
        sys.stdout.write("".join(out))
        sys.stdout.flush()
        time.sleep(0.12)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback
        err = traceback.format_exc()
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "face_window.log"), "a",
                      encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + err + "\n")
        except OSError:
            pass
        sys.stdout.write("\x1b[?25h\x1b[?7h" + RESET + "\x1b[2J\x1b[H")
        print("Окно с анимацией упало (подробности в face_window.log):\n")
        print(err)
        time.sleep(60)
