"""Напарник в Minecraft: запускает бота (minecraft/bot.js) и передаёт ему голосовые команды."""
import atexit
import json
import logging
import os
import shutil
import socket
import struct
import subprocess
import threading
import time
import urllib.request

import config

log = logging.getLogger("jarvis.minecraft")
BOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "minecraft")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

announce = lambda text: None    # озвучка сообщений бота; подставляет jarvis.py
_proc = None


def _api(path, data=None, timeout=60):
    req = urllib.request.Request(
        f"http://127.0.0.1:{config.MC_API_PORT}{path}",
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def find_lan_port(timeout=5.0):
    """Minecraft, открытый для сети, раз в 1,5 с рассылает «[MOTD]..[/MOTD][AD]порт[/AD]» на 224.0.2.60:4445."""
    group = "224.0.2.60"
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", 4445))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                     struct.pack("4sl", socket.inet_aton(group), socket.INADDR_ANY))
        s.settimeout(timeout)
        data, _ = s.recvfrom(1024)
        text = data.decode("utf-8", errors="ignore")
        if "[AD]" in text:
            return int(text.split("[AD]")[1].split("[/AD]")[0])
    except (OSError, ValueError):
        pass
    finally:
        s.close()
    return None


def _running():
    return _proc is not None and _proc.poll() is None


def _poll_events():
    while _running():
        try:
            for text in _api("/events", timeout=5):
                announce(text)
        except Exception:
            pass
        time.sleep(2)


def _stop():
    if _running():
        _proc.terminate()


atexit.register(_stop)


def minecraft_join() -> str:
    """Заходит в мир Minecraft вторым игроком-напарником. Мир должен быть открыт для сети (Esc → «Открыть для сети»)."""
    global _proc
    if _running():
        return "Я уже в игре"
    if not os.path.isfile(os.path.join(BOT_DIR, "node_modules", "mineflayer", "package.json")):
        return "Бот для Minecraft не установлен — запусти setup.bat"
    node = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
    if not os.path.isfile(node) and not shutil.which("node"):
        return "Не найден Node.js — запусти setup.bat"

    port = config.MC_PORT or find_lan_port()
    if not port:
        return "Не нашёл открытый мир. Нажми в игре Esc, «Открыть для сети», «Начать» и позови снова"

    logf = open(os.path.join(BOT_DIR, "bot.log"), "a", encoding="utf-8")
    logf.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} port {port} =====\n")
    logf.flush()
    _proc = subprocess.Popen(
        [node, "bot.js", f"--host={config.MC_HOST}", f"--port={port}",
         f"--name={config.MC_BOT_NAME}", f"--api={config.MC_API_PORT}"],
        cwd=BOT_DIR, stdout=logf, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
    )
    for _ in range(80):              # до 60 секунд: первый вход в большой мир бывает долгим
        time.sleep(0.75)
        if not _running():
            return "Не смог зайти в мир — подробности в minecraft\\bot.log"
        try:
            if _api("/status", timeout=2).get("ready"):
                threading.Thread(target=_poll_events, daemon=True).start()
                log.info("Бот зашёл в мир, порт %s", port)
                return f"Зашёл в мир как {config.MC_BOT_NAME}"
        except Exception:
            pass
    _stop()
    return "Не дождался входа в мир — подробности в minecraft\\bot.log"


def minecraft_command(action: str, target: str = "", count: int = 0, material: str = "", height: int = 0) -> str:
    """Командует ботом-напарником в Minecraft (после minecraft_join). Все id предметов и блоков — английские, как в игре.

    Args:
        action: одно из:
            follow — идти за игроком; come — подойти; stop — остановить любое дело; guard — охранять игрока от мобов;
            attack — напасть (target: моб, например zombie; пусто — ближайший враг);
            goto — идти по координатам (target: "x y z" или "x z");
            collect — добыть блоки (target: id блока: wood, oak_log, stone, coal_ore, iron_ore, dirt, sand; count);
            pickup — подобрать предметы, валяющиеся рядом (например, то, что бросил игрок);
            craft — скрафтить (target: id: crafting_table, wooden_pickaxe, stone_axe, stick, furnace, torch, chest; count);
            recipe — узнать настоящий рецепт предмета (target: id);
            smelt — переплавить в печи (target: raw_iron, raw_gold, sand, beef, cobblestone…; count);
            place — поставить блок рядом с собой (target: id: crafting_table, furnace, chest, torch…);
            build — построить перед игроком (target: house, shelter, wall, tower, pillar, platform, bridge, pen;
                count — размер; material — из чего; height — высота);
            farm — собрать спелый урожай рядом и пересадить;
            equip — взять в руку или надеть (target: часть id: pickaxe, sword, helmet…);
            eat — поесть; sleep — лечь в кровать рядом;
            give — отдать игроку предмет (target: часть id; count); drop — выбросить предмет;
            deposit — положить в ближайший сундук (target: что, пусто — всё кроме инструментов и брони);
            withdraw — взять из сундука (target: что; count);
            inventory — что в инвентаре; status — здоровье, еда, координаты, чем занят;
            say — написать в чат (target: текст); leave — выйти из игры.
            Если бот занят долгим делом (стройка, добыча, плавка, урожай), новые команды встают в очередь
            и выполняются по порядку — можно сразу давать несколько команд подряд. stop отменяет всё.
        target: цель команды (см. выше), можно пусто
        count: количество (для build — размер); 0 — по умолчанию
        material: материал для build: planks (по умолчанию), cobblestone, dirt или id блока
        height: высота для build, 0 — по умолчанию
    """
    if not _running():
        return "Я не в игре — сначала нужно зайти (minecraft_join)"
    try:
        return _api("/cmd", {"action": action, "target": target, "count": int(count or 0),
                             "material": material, "height": int(height or 0)}, timeout=75)["text"]
    except Exception as e:
        return f"Бот не ответил: {e}"


TOOLS = [minecraft_join, minecraft_command]
