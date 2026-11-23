"""Цветная сцена для окна Джарвиса: комната с анимациями + персонаж поверх неё.

Каждая клетка консоли = символ Брайля (2x4 точки) с двумя цветами: цвет точек и цвет фона.
Так в консоли получается цветной «пиксель-арт» примерно 200x184 пикселя.
Нужна консоль с поддержкой 24-битного цвета (Windows Terminal — да).
"""
import math
import os
import random
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

BASE_W, H = 232, 184           # базовая сцена в пикселях; под широкое окно она расширяется вправо
W = BASE_W
BASE_CHAR_X = 18
BASE_SCREEN = (146, 72, 218, 112)   # экран монитора 16:9; левая часть — за персонажем
CHAR_X, SCREEN, MID, RIGHT = BASE_CHAR_X, BASE_SCREEN, 0, 0
BG_FRAMES = 16                 # длина цикла анимации комнаты


def _layout(width):
    """Раскладка под ширину: окно и торшер слева, персонаж с монитором — к центру, полка — к правой стене."""
    global W, CHAR_X, SCREEN, MID, RIGHT
    W = width
    RIGHT = width - BASE_W
    MID = RIGHT // 2 // 2 * 2
    CHAR_X = BASE_CHAR_X + MID
    x0, y0, x1, y1 = BASE_SCREEN
    SCREEN = (x0 + MID, y0, x1 + MID, y1)

# палитра в духе тёмной визуальной новеллы: глубокий синий, красный, бирюзовый
WALL_TOP, WALL_BOT = (9, 9, 16), (20, 12, 20)
RED, RED_DARK = (127, 29, 44), (64, 21, 35)
TEAL, TEAL_DIM = (70, 200, 190), (24, 84, 86)
WARM = (196, 92, 64)
SKY_TOP, SKY_BOT = (12, 11, 27), (76, 24, 42)
WOOD_EDGE, WOOD_SHADOW = (77, 37, 51), (15, 9, 17)


# ---------------- клетки: картинка -> (символ, цвет точек, цвет фона) ----------------
def to_cells(rgb):
    """rgb: массив H x W x 3 (H кратно 4, W кратно 2) -> (codes, fg, bg) размером rows x cols."""
    h, w, _ = rgb.shape
    rows, cols = h // 4, w // 2
    a = rgb[:rows * 4, :cols * 2].astype(np.float32).reshape(rows, 4, cols, 2, 3).transpose(0, 2, 1, 3, 4)
    a = a.reshape(rows, cols, 8, 3)                                  # 8 пикселей клетки в порядке (dy, dx)
    lum = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    lo, hi = lum.min(axis=2), lum.max(axis=2)
    thr = (lo + hi) / 2
    bright = lum > thr[..., None]
    flat = (hi - lo) < 14                                            # почти однотонная клетка
    bright[flat] = False
    nb = bright.sum(axis=2, keepdims=True)
    nd = 8 - nb
    fg = np.where(nb > 0, (a * bright[..., None]).sum(axis=2) / np.maximum(nb, 1), 0)
    bg = np.where(nd > 0, (a * (~bright)[..., None]).sum(axis=2) / np.maximum(nd, 1), fg)
    # порядок пикселей (dy, dx) -> биты Брайля
    bitmap = np.array([0x01, 0x08, 0x02, 0x10, 0x04, 0x20, 0x40, 0x80])
    codes = (bright * bitmap).sum(axis=2)
    return codes.astype(np.int32), fg.astype(np.uint8), bg.astype(np.uint8)


# ---------------- комната ----------------
def _gradient(d, box, top, bot):
    x0, y0, x1, y1 = box
    for y in range(y0, y1):
        t = (y - y0) / max(1, y1 - y0 - 1)
        d.line((x0, y, x1 - 1, y), fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))


def _cat(d):
    """Кошка на подоконнике (тёмный силуэт с лунным контуром). Рисуется поверх дождя."""
    rim = (58, 62, 92)                                                # лунный контур
    d.ellipse((43, 88, 63, 101), fill=rim)
    d.ellipse((51, 81, 64, 93), fill=rim)
    d.polygon([(52, 86), (54, 76), (58, 83)], fill=rim)
    d.polygon([(58, 83), (62, 76), (64, 87)], fill=rim)
    cat = (8, 6, 12)
    d.ellipse((44, 89, 62, 101), fill=cat)                            # тело
    d.ellipse((52, 82, 63, 92), fill=cat)                             # голова
    d.polygon([(53, 85), (54, 78), (57, 83)], fill=cat)               # уши
    d.polygon([(59, 83), (62, 78), (63, 86)], fill=cat)


# время суток: (яркость комнаты, подкраска, небо сверху, небо снизу, свет на персонаже)
PERIODS = {
    "morning": (1.45, (16, 6, 10), (96, 116, 170), (222, 150, 132), 1.12),
    "day":     (1.75, (8, 12, 16), (104, 156, 210), (182, 204, 222), 1.22),
    "evening": (1.25, (22, 4, 0), (52, 34, 86), (214, 104, 66), 1.05),
    "night":   (1.0, (0, 0, 0), None, None, 1.0),
}


def period_now(hour=None):
    import datetime
    h = datetime.datetime.now().hour if hour is None else hour
    return "morning" if 6 <= h < 10 else "day" if 10 <= h < 17 else "evening" if 17 <= h < 22 else "night"


def _sky_mask():
    """Где в окне видно небо (без домов и рам) — днём там светлое небо вместо ночного."""
    m = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(m)
    d.rectangle((12, 24, 67, 96), fill=255)
    rnd = random.Random(7)
    for x0 in range(12, 69, 7):                                       # те же дома, что в _room_static
        hgt = rnd.randint(14, 34)
        d.rectangle((x0, 97 - hgt, x0 + 6, 96), fill=0)
    d.line((40, 24, 40, 96), fill=0)
    d.line((12, 60, 68, 60), fill=0)
    d.rectangle((43, 26, 67, 43), fill=0)                             # приподнятые жалюзи
    d.ellipse((42, 87, 64, 102), fill=0)                              # кошка с хвостом
    d.ellipse((50, 74, 65, 94), fill=0)
    d.rectangle((33, 84, 46, 101), fill=0)
    d.rectangle((10, 86, 26, 101), fill=0)                            # свеча
    return m


def _room_static():
    img = Image.new('RGB', (W, H))
    d = ImageDraw.Draw(img)
    _gradient(d, (0, 0, W, 152), WALL_TOP, WALL_BOT)
    # Тень в углах и на стыке стены с полом.
    shade = Image.new('L', (W, H))
    shadow = ImageDraw.Draw(shade)
    shadow.rectangle((0, 0, W, 13), fill=125)
    shadow.rectangle((W - 19, 0, W, 152), fill=145)
    shadow.rectangle((0, 145, W, 153), fill=140)
    img.paste((4, 4, 9), (0, 0, W, H), shade.filter(ImageFilter.GaussianBlur(9)))
    d.line([(0, 16), (102, 7), (W - 19, 7), (W, 16)], fill=(50, 28, 43))
    d.line((W - 19, 8, W - 19, 151), fill=(35, 21, 34))
    # пол
    d.rectangle((0, 152, W, H), fill=(16, 8, 12))
    for y in (160, 170, 181):
        d.line((0, y, W, y), fill=(10, 5, 8))
    for x in range(-34, W + 34, 24):
        near = round(W / 2 + (x - W / 2) * 1.36)
        d.line((x, 152, near, H), fill=(10, 5, 8))
    d.line((0, 152, W, 152), fill=(44, 14, 22))
    pool = Image.new('L', (W, H))
    ImageDraw.Draw(pool).ellipse((-28, 148, 79, 181), fill=85)
    img.paste((78, 36, 30), (0, 0, W, H), pool.filter(ImageFilter.GaussianBlur(9)))
    # окно слева
    d.rectangle((10, 23, 77, 107), fill=(8, 6, 12))
    d.rectangle((8, 20, 72, 100), fill=(34, 20, 30))
    d.rectangle((8, 20, 72, 100), outline=WOOD_EDGE)
    d.rectangle((10, 22, 70, 98), outline=WOOD_SHADOW)
    _gradient(d, (12, 24, 69, 97), SKY_TOP, SKY_BOT)
    d.ellipse((20, 30, 34, 44), fill=(170, 206, 200))                 # луна
    d.ellipse((24, 30, 36, 42), fill=SKY_TOP)                         # серп
    rnd = random.Random(7)
    for x0 in range(12, 69, 7):                                       # силуэт города
        hgt = rnd.randint(14, 34)
        d.rectangle((x0, 97 - hgt, x0 + 6, 96), fill=(5, 4, 10))
    d.line((40, 24, 40, 96), fill=(34, 20, 30))                       # переплёт
    d.line((12, 60, 68, 60), fill=(34, 20, 30))
    d.rectangle((6, 100, 74, 104), fill=(44, 24, 34))                 # подоконник
    # шторы
    for x0, x1 in ((0, 12), (68, 82)):
        d.rectangle((x0, 14, x1, 128), fill=(42, 17, 29), outline=WOOD_EDGE)
        for x in range(x0 + 2, x1, 4):
            d.line((x, 17, x, 127), fill=RED_DARK)
    d.rectangle((0, 12, 86, 15), fill=(52, 30, 30))                   # карниз
    # торшер слева
    d.line((14, 116, 14, 152), fill=(48, 30, 32), width=2)
    d.polygon([(4, 116), (24, 116), (20, 104), (8, 104)], fill=WARM)
    d.ellipse((8, 150, 20, 154), fill=(34, 20, 22))
    # полка справа сверху с книгами и растением
    R = RIGHT
    d.polygon([(177 + R, 42), (230 + R, 42), (226 + R, 49), (182 + R, 47)], fill=(9, 6, 12))
    d.rectangle((176 + R, 40, 230 + R, 43), fill=(46, 26, 26))
    d.line((176 + R, 40, 230 + R, 40), fill=WOOD_EDGE)
    for i, (bx, col) in enumerate(((180, RED_DARK), (186, TEAL_DIM), (191, (90, 60, 50)), (197, (54, 34, 64)),
                                   (202, RED), (207, (30, 60, 62)))):
        d.rectangle((bx + R, 26 + (i % 3) * 2, bx + 4 + R, 39), fill=col)
    d.polygon([(216 + R, 39), (226 + R, 39), (224 + R, 32), (218 + R, 32)], fill=(70, 30, 26))
    for dx, dy in ((-6, -10), (0, -14), (6, -10), (-3, -6), (4, -6)):
        d.ellipse((221 + R + dx - 4, 30 + dy - 3, 221 + R + dx + 4, 30 + dy + 3), fill=(22, 62, 56))
    px = BASE_SCREEN[2] + MID + 14
    if W - px > 40:                                                   # на широком экране — постер справа от монитора
        d.rectangle((px, 64, px + 24, 98), fill=(30, 14, 22))
        d.rectangle((px, 64, px + 24, 98), outline=WOOD_EDGE)
        d.rectangle((px + 2, 66, px + 22, 96), fill=(70, 14, 30))
        d.ellipse((px + 5, 72, px + 19, 86), fill=(150, 30, 46))
    # стол справа
    d.polygon([(143 + MID, 124), (W, 124), (W, 131), (138 + MID, 131)],
              fill=(37, 21, 28), outline=WOOD_EDGE)
    d.rectangle((139 + MID, 132, W, 135), fill=WOOD_SHADOW)
    d.rectangle((144 + MID, 133, 148 + MID, 152), fill=(28, 14, 18))
    d.rectangle((W - 6, 133, W - 2, 152), fill=(28, 14, 18))
    # монитор: тонкая рамка со скруглёнными углами, «подбородок», ножка и овальная подставка
    x0, y0, x1, y1 = SCREEN
    cx = (x0 + x1) // 2
    glow = Image.new('L', (W, H), 0)
    ImageDraw.Draw(glow).rounded_rectangle((x0 - 12, y0 - 12, x1 + 12, y1 + 26), 10, fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(10))
    img = Image.composite(Image.new('RGB', (W, H), (20, 70, 72)), img, glow)
    d = ImageDraw.Draw(img)
    d.polygon([(cx - 3, y1 + 6), (cx + 3, y1 + 6), (cx + 5, 125), (cx - 5, 125)], fill=(38, 36, 46))   # ножка
    d.ellipse((cx - 18, 122, cx + 18, 129), fill=(42, 40, 52))                                          # подставка
    d.ellipse((cx - 15, 122, cx + 15, 125), fill=(60, 58, 72))
    d.rounded_rectangle((x0 - 3, y0 - 3, x1 + 3, y1 + 7), 3, fill=(30, 29, 40))                          # корпус
    d.line((x0 - 1, y0 - 3, x1 + 1, y0 - 3), fill=(46, 60, 66))                                          # блик сверху
    d.point((cx, y1 + 4), fill=(80, 220, 200))                                                           # индикатор
    # ---- декор ----
    # ковёр на полу (частично под персонажем)
    d.ellipse((CHAR_X - 13, 158, CHAR_X + 179, 184), fill=(8, 5, 10))
    d.ellipse((CHAR_X - 14, 156, CHAR_X + 176, 182), fill=(46, 10, 20))
    d.ellipse((CHAR_X - 6, 159, CHAR_X + 168, 179), outline=(84, 18, 32))
    d.ellipse((CHAR_X + 14, 162, CHAR_X + 148, 176), outline=(30, 60, 62))
    # стопка книг под столом
    for k, (bw, col) in enumerate(((26, (60, 16, 26)), (22, (24, 70, 72)), (24, (70, 44, 36)), (18, (40, 24, 52)))):
        bx = W - 44 + (k % 2) * 2
        d.rectangle((bx, 148 - k * 4, bx + bw, 151 - k * 4), fill=col)
    # кашпо с плющом, висит с потолка у окна
    d.line((92, 0, 92, 18), fill=(40, 30, 30))
    d.polygon([(85, 18), (99, 18), (97, 27), (87, 27)], fill=(74, 30, 26))
    for vx, ln in ((86, 22), (90, 34), (95, 28), (98, 18)):
        for t in range(0, ln, 3):
            x = vx + int(2 * math.sin(t / 4 + vx))
            d.ellipse((x - 2, 27 + t - 1, x + 2, 27 + t + 2), fill=(20, 58 + (t % 2) * 10, 50))
    # настенные часы
    d.ellipse((125, 18, 144, 36), fill=(7, 5, 10))
    d.ellipse((124, 16, 142, 34), fill=(45, 31, 39))
    d.ellipse((126, 18, 140, 32), fill=(68, 65, 72))
    for x, y in ((133, 19), (139, 25), (133, 31), (127, 25)):
        d.point((x, y), fill=(108, 101, 109))
    # свеча на подоконнике
    d.rectangle((16, 94, 20, 100), fill=(150, 130, 112))
    d.rectangle((14, 99, 22, 100), fill=(60, 40, 40))
    # кружка на столе
    mx = 223 + MID
    d.rectangle((mx, 120, mx + 7, 127), fill=(120, 26, 40))
    d.arc((mx + 5, 121, mx + 10, 126), -90, 90, fill=(120, 26, 40))
    d.line((mx, 120, mx + 7, 120), fill=(40, 20, 16))
    # провод от монитора свисает со стола
    d.line([(182 + MID, 129), (178 + MID, 136), (176 + MID, 146), (180 + MID, 152)], fill=(14, 12, 18))
    # неоновое сердечко над монитором (свечение)
    nx, ny = 152 + MID, 24
    hg = Image.new('L', (W, H), 0)
    ImageDraw.Draw(hg).ellipse((nx - 8, ny - 8, nx + 26, ny + 28), fill=60)
    hg = hg.filter(ImageFilter.GaussianBlur(7))
    img = Image.composite(Image.new('RGB', (W, H), (120, 20, 46)), img, hg)
    d = ImageDraw.Draw(img)
    # красная дымка от окна и штор
    haze = Image.new('L', (W, H), 0)
    ImageDraw.Draw(haze).ellipse((-60, 0, 110, 170), fill=60)
    haze = haze.filter(ImageFilter.GaussianBlur(24))
    img = Image.composite(Image.new('RGB', (W, H), (90, 10, 24)), img, haze)
    return img


def _room_frame(static, i):
    img = static.copy()
    d = ImageDraw.Draw(img)
    rnd = random.Random(1000 + i)
    # огоньки в окнах домов мерцают
    for k in range(10):
        x = 13 + (k * 13) % 55
        y = 72 + (k * 7) % 22
        if rnd.random() < 0.7:
            d.point((x, y), fill=(210, 60, 50) if k % 3 else (220, 150, 90))
    # дождь в окне
    for k in range(26):
        x = 12 + (k * 23) % 57
        y = 24 + ((k * 17) + i * 6) % 73
        d.line((x, y, x - 2, y + 5), fill=(64, 84, 112))
    d.line((40, 24, 40, 96), fill=(34, 20, 30))                       # переплёт поверх дождя
    d.line((12, 60, 68, 60), fill=(34, 20, 30))
    d.rectangle((43, 26, 67, 43), fill=(23, 14, 23), outline=WOOD_EDGE)
    for y in range(29, 43, 3):
        d.line((44, y, 66, y), fill=(63, 30, 43))
    # свечение торшера пульсирует
    glow = Image.new('RGB', (W, H))
    gd = ImageDraw.Draw(glow)
    r = 26 + 2 * math.sin(i / BG_FRAMES * 2 * math.pi)
    gd.ellipse((14 - r, 112 - r, 14 + r, 112 + r), fill=(70, 46, 20))
    img = Image.composite(Image.blend(img, Image.eval(img, lambda v: min(255, v + 26)), 0.5), img,
                          glow.convert('L').point(lambda v: 255 if v > 0 else 0).filter(ImageFilter.GaussianBlur(6)))
    d = ImageDraw.Draw(img)
    # ---- анимация декора ----
    # кошка поверх дождя: хвост качается, глаза иногда моргают
    _cat(d)
    sw = math.sin(i / BG_FRAMES * 2 * math.pi)
    d.line([(45, 99), (40, 97), (37 + 3 * sw, 92), (39 + 5 * sw, 86)], fill=(58, 62, 92), width=3)
    d.line([(45, 99), (40, 97), (37 + 3 * sw, 92), (39 + 5 * sw, 86)], fill=(8, 6, 12), width=1)
    if i % 8 not in (5,):
        d.rectangle((55, 87, 56, 87), fill=(120, 240, 200))
        d.rectangle((59, 87, 60, 87), fill=(120, 240, 200))
    # пламя свечи дрожит + тёплый ореол
    fl = rnd.choice((0, 0, 1, -1))
    halo = Image.new('L', (W, H), 0)
    ImageDraw.Draw(halo).ellipse((4 + fl, 80, 32 + fl, 106), fill=50 + rnd.randint(0, 25))
    halo = halo.filter(ImageFilter.GaussianBlur(5))
    img = Image.composite(Image.new('RGB', (W, H), (160, 80, 40)), img, halo)
    d = ImageDraw.Draw(img)
    d.polygon([(17 + fl, 89), (16, 93), (18, 94), (20, 93)], fill=(250, 190, 90))
    d.point((18, 92), fill=(255, 240, 200))
    # пар над кружкой
    mx = 226 + MID
    for k in range(2):
        for t in range(8):
            y = 118 - t * 2 - ((i + k * 5) % 4)
            x = mx + k * 3 + int(1.5 * math.sin((t + i + k * 3) / 2))
            if t < 7:
                d.point((x, y), fill=(52 + 8 * (7 - t), 56 + 8 * (7 - t), 62 + 8 * (7 - t)))
    # пылинки в свете монитора
    x0, y0, x1, y1 = SCREEN
    for k in range(9):
        px = x0 - 10 + (k * 37 + i * (1 + k % 3)) % (x1 - x0 + 30)
        py = y0 - 8 + (k * 23 + int(4 * math.sin((i + k * 2) / 3))) % (y1 - y0 + 24)
        d.point((px, py), fill=(90, 170, 160) if k % 2 else (60, 120, 116))
    # неоновое сердечко мигает
    nx, ny = 152 + MID, 24
    col = (240, 60, 96) if i not in (3, 4, 11) else (90, 24, 40)
    d.line([(nx + 9, ny + 20), (nx, ny + 10), (nx, ny + 4), (nx + 4, ny), (nx + 9, ny + 4), (nx + 14, ny),
            (nx + 18, ny + 4), (nx + 18, ny + 10), (nx + 9, ny + 20)], fill=col, width=1)
    # гирлянда под потолком
    colors = (RED, TEAL_DIM, (170, 40, 50), (60, 150, 140))
    pts = [(x, 6 + int(3 * math.sin(x / 14))) for x in range(0, W + 1, 4)]
    d.line(pts, fill=(30, 20, 26))
    for n, x in enumerate(range(6, W, 14)):
        y = 7 + int(3 * math.sin(x / 14))
        on = (n + i // 2) % 3 != 0
        c = colors[n % len(colors)] if on else tuple(v // 5 for v in colors[n % len(colors)])
        d.ellipse((x - 2, y, x + 2, y + 4), fill=c)
    # экран монитора (если логов нет — бегущий «код»)
    x0, y0, x1, y1 = SCREEN
    d.rectangle(SCREEN, fill=(6, 22, 26))
    for row in range(9):
        line_n = row + i // 2
        ln = 8 + (line_n * 7) % 30
        indent = (line_n * 3) % 3 * 4
        d.line((x0 + 3 + indent, y0 + 3 + row * 4, min(x1 - 3, x0 + 3 + indent + ln), y0 + 3 + row * 4),
               fill=TEAL if row != 8 else TEAL_DIM)
    return img


# ---------------- персонаж ----------------
CHAR_W = 150
GRAY_TO_RGB = (  # оттенок серого на рисунке -> цвет в сцене (бледная холодная кожа, тёмные сливовые волосы)
    (0, (4, 3, 8)), (45, (9, 6, 13)), (75, (26, 16, 30)), (150, (70, 52, 68)),
    (200, (150, 168, 172)), (255, (184, 200, 200)))
RIM_LEFT, RIM_RIGHT = np.array((170, 28, 48), np.float32), np.array((40, 160, 158), np.float32)


def _colorize(gray):
    xs = [p[0] for p in GRAY_TO_RGB]
    out = np.zeros(gray.shape + (3,), np.float32)
    for c in range(3):
        out[..., c] = np.interp(gray, xs, [p[1][c] for p in GRAY_TO_RGB])
    return out


def _silhouette(gray):
    """Маска персонажа: всё, что не связано со светлым фоном по краям картинки."""
    bg = (gray > 215).astype(np.uint8) * 255
    m = Image.fromarray(bg).copy()           # copy: иначе floodfill не меняет картинку
    h, w = gray.shape
    seeds = [(x, 0) for x in range(0, w, 6)] + [(0, y) for y in range(0, h, 6)] + [(w - 1, y) for y in range(0, h, 6)]
    for sx, sy in seeds:
        if m.getpixel((sx, sy)) == 255:
            ImageDraw.floodfill(m, (sx, sy), 128)
    inside = (np.array(m) != 128).astype(np.uint8) * 255
    # чуть ужимаем край (без белой «обводки») и скругляем зубцы контура: размытие + порог
    im = Image.fromarray(inside).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(2.5))
    return np.array(im) > 140


def _alpha(mask):
    """Мягкий край (сглаживание) для смешивания персонажа с фоном."""
    a = Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(1.2))
    return np.array(a, np.float32) / 255


def _light(rgb, mask, gray):
    """Свет комнаты на персонаже: общий полумрак, красный контровой слева, бирюзовый справа."""
    h, w = mask.shape
    m = Image.fromarray(mask.astype(np.uint8) * 255)
    near_edge = np.array(m.filter(ImageFilter.MinFilter(7))) == 0      # полоса у края силуэта
    edge = (mask & near_edge).astype(np.float32)
    edge = np.array(Image.fromarray((edge * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2.5)),
                    np.float32) / 255 * mask
    # светлые пиксели у самого края — это остатки белого фона: делаем их цветом волос
    rgb = np.where(((gray > 190) & near_edge & mask)[..., None], np.array((26, 16, 30), np.float32), rgb)
    xs = np.linspace(0, 1, w)[None, :]
    rim = edge[..., None] * ((1 - xs)[..., None] * RIM_LEFT + xs[..., None] * RIM_RIGHT)
    # общий градиент: сверху чуть светлее, к низу темнее, лёгкий красный оттенок слева
    ys = np.linspace(0, 1, h)[:, None]
    shade = (0.95 - 0.35 * ys)[..., None]
    tint = (1 - xs)[..., None] * np.array((18, 0, 6), np.float32) + xs[..., None] * np.array((0, 8, 10), np.float32)
    out = rgb * shade + tint * mask[..., None] + rim * 0.6
    return np.clip(out, 0, 255)


def load_character(images, source_color=0.0):
    """images: {имя кадра: путь к картинке или PIL.Image}. -> {имя: (rgb, mask)} размером CHAR_W x ?"""
    out = {}
    cache = {}
    for name, src in images.items():
        key = src if isinstance(src, str) else id(src)
        if key not in cache:
            if isinstance(src, str):
                with Image.open(src) as opened:
                    img = opened.convert('RGB' if source_color else 'L')
            else:
                img = src.convert('RGB' if source_color else 'L')
            h = int(img.height * CHAR_W / img.width)
            img = img.resize((CHAR_W, h), Image.LANCZOS)
            gray = np.array(img.convert('L'), dtype=np.float32)
            mask = _silhouette(gray)
            rgb = _colorize(gray)
            if source_color:
                # Просветы внутри причёски и между рукой и корпусом тоже показывают комнату.
                # Мелкие блики глаз и светлый контур рта сохраняются.
                paper = Image.fromarray((gray > 213).astype(np.uint8) * 255)
                gaps = paper.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(9))
                mask &= ~((np.asarray(gaps) > 0) & (gray > 198))
                source = np.asarray(img, dtype=np.float32)
                rgb = rgb * (1 - source_color) + source * source_color
                # Голубая радужка должна читаться и при вечернем освещении.
                blue = np.clip((source[..., 2] - source[..., 0] - 35) / 125, 0, 1)
                iris = Image.fromarray((blue * 255).astype(np.uint8))
                soft_edge = np.asarray(iris.filter(ImageFilter.MaxFilter(5))
                                       .filter(ImageFilter.GaussianBlur(1.1)), dtype=np.float32) / 255
                rgb += (soft_edge * source_color)[..., None] * np.array((96, 145, 158))
            cache[key] = (_light(rgb, mask, gray), mask)
        out[name] = cache[key]
    return out


class Scene:
    """cols x rows — размер области сцены в клетках консоли (без окна диалога снизу оно наложится поверх)."""
    def __init__(self, char_images, cols=116, rows=46, source_color=0.0):
        tw, th = cols * 2, rows * 4                                  # целевой размер в точках
        bw = max(BASE_W, int(round(H * tw / th / 2)) * 2)            # шире окно — шире комната
        self.room_width = bw
        _layout(bw)
        s = tw / bw
        oh = max(4, int(H * s) // 4 * 4)
        self.size = (tw, oh)
        self.rows, self.cols = oh // 4, cols

        def fit(img_arr, resample=Image.LANCZOS):
            im = Image.fromarray(np.clip(img_arr, 0, 255).astype(np.uint8))
            return np.array(im.resize(self.size, resample), np.float32)

        static = _room_static()
        self.bg_base = [fit(np.array(_room_frame(static, i))) for i in range(BG_FRAMES)]
        self.bg_px = self.bg_base
        self.sky_mask = fit(np.array(_sky_mask().convert('RGB'))).mean(-1, keepdims=True) / 255
        self.sky_rows = (24 * s, 97 * s)                             # окно по вертикали, в точках
        self.period, self.char_light = "night", 1.0
        chars = load_character(char_images, source_color)
        self.char, done = {}, {}
        for name, (rgb, mask) in chars.items():
            key = id(rgb)
            if key not in done:
                ch = rgb.shape[0] - rgb.shape[0] % 4
                rgb, mask = rgb[:ch], mask[:ch]
                canvas = np.zeros((H, W, 3), np.float32)
                cmask = np.zeros((H, W), bool)
                y0 = max(0, H - ch)
                hh = min(ch, H)
                canvas[y0:y0 + hh, CHAR_X:CHAR_X + CHAR_W] = rgb[ch - hh:]
                cmask[y0:y0 + hh, CHAR_X:CHAR_X + CHAR_W] = mask[ch - hh:]
                alpha = fit(_alpha(cmask) * 255) / 255
                cellmask = alpha.reshape(self.rows, 4, self.cols, 2).mean(axis=(1, 3)) >= 0.35
                done[key] = (fit(canvas), alpha[..., None], cellmask)
            self.char[name] = done[key]
        # экран монитора в клетках
        x0, y0, x1, y1 = SCREEN
        self.screen = (int(math.ceil(x0 * s / 2)), int(math.ceil(y0 * s / 4)),
                       int(x1 * s / 2), int(y1 * s / 4))
        self.screen_cols = self.screen[2] - self.screen[0]
        self.screen_rows = self.screen[3] - self.screen[1]
        self._cache = {}
        self._clock_time = None

    def _update_clock(self):
        now = time.localtime()
        clock_time = (now.tm_hour % 12, now.tm_min)
        if clock_time == self._clock_time:
            return
        hour, minute = clock_time
        hands = Image.new('RGBA', (self.room_width, H))
        draw = ImageDraw.Draw(hands)
        for turns, length, color in (
            ((hour + minute / 60) / 12, 4, (155, 130, 137)),
            (minute / 60, 6, (127, 170, 167)),
        ):
            angle = math.tau * turns
            end = (133 + round(length * math.sin(angle)), 25 - round(length * math.cos(angle)))
            draw.line(((133, 25), end), fill=color)
        draw.point((133, 25), fill=(162, 151, 155))
        hands = hands.resize(self.size, Image.Resampling.BILINEAR)
        left, top, right, bottom = hands.getbbox()
        self._clock_area = np.s_[top:bottom, left:right]
        patch = np.asarray(hands.crop((left, top, right, bottom)), dtype=np.float32)
        self._clock_rgb = patch[..., :3]
        self._clock_alpha = patch[..., 3:] / 255
        self._clock_time = clock_time
        self._cache.clear()

    def set_period(self, period):
        """Время суток: утро / день / вечер / ночь — свет в комнате и небо в окне."""
        if period == self.period or period not in PERIODS:
            return False
        mul, tint, sky_top, sky_bot, light = PERIODS[period]
        if period == "night":
            self.bg_px = self.bg_base
        else:
            h = self.size[1]
            y0, y1 = self.sky_rows
            t = np.clip((np.arange(h) - y0) / max(1.0, y1 - y0), 0, 1)[:, None, None]
            sky = np.array(sky_top, np.float32) * (1 - t) + np.array(sky_bot, np.float32) * t
            m = self.sky_mask * 0.88
            self.bg_px = [np.clip((b * mul + np.array(tint, np.float32)) * (1 - m) + sky * m, 0, 255)
                          for b in self.bg_base]
        self.period, self.char_light = period, light
        self._cache.clear()
        return True

    def _cells(self, frame, tick):
        self._update_clock()
        key = (frame, tick % BG_FRAMES)
        got = self._cache.get(key)
        if got is None:
            canvas, alpha, cellmask = self.char.get(frame) or self.char['idle']
            background = self.bg_px[key[1]]
            px = background * (1 - alpha) + canvas * (alpha * self.char_light)
            area = self._clock_area
            px[area] += (self._clock_rgb - background[area]) * self._clock_alpha * (1 - alpha[area])
            got = to_cells(px) + (cellmask,)
            if len(self._cache) > 600:
                self._cache.clear()
            self._cache[key] = got
        return got

    def arrays(self, frame, tick, screen_lines=None):
        """-> (символы, цвет точек, цвет фона) всей сцены как массивы rows x cols. Логи — на экране монитора."""
        codes, fg, bg, cmask = self._cells(frame, tick)
        chars = BRAILLE[codes]
        fg = (fg // 6 * 6).astype(np.uint8)          # меньше разных цветов -> меньше кодов в консоль
        bg = (bg // 6 * 6).astype(np.uint8)
        if screen_lines:
            chars, fg, bg = chars.copy(), fg.copy(), bg.copy()
            c0, r0, c1, r1 = self.screen
            width, height = c1 - c0, r1 - r0
            shown = screen_lines[-height:]
            dim_until = len(shown) - 3                                      # свежие 3 строки ярче
            cells = {}
            for i, line in enumerate(shown):
                for j, ch in enumerate(line[:width]):
                    cells[(r0 + i, c0 + j)] = (ch, i < dim_until)
            if shown and tick % 8 < 4:                                      # мигающий курсор
                cells[(r0 + len(shown) - 1, c0 + min(len(shown[-1]), width - 1))] = ('▌', False)
            for r in range(r0, r0 + height):
                for c in range(c0, c1):
                    if cmask[r, c]:
                        continue
                    ch, dim = cells.get((r, c), (' ', False))
                    chars[r, c] = ch
                    fg[r, c] = TEXT_FG_OLD if dim else TEXT_FG
                    bg[r, c] = TEXT_BG
        return chars, fg, bg

    def render(self, frame, tick, screen_lines=None):
        """-> список строк с ANSI-цветами (вся сцена целиком)."""
        chars, fg, bg = self.arrays(frame, tick, screen_lines)
        return [span(chars, fg, bg, r, 0, self.cols) + "\x1b[0m" for r in range(self.rows)]


BRAILLE = np.array([chr(0x2800 + i) for i in range(256)])


def span(chars, fg, bg, r, c0, c1):
    """Кусок строки r (столбцы c0..c1) в виде текста с ANSI-цветами; цвет пишется только когда меняется."""
    parts, lf, lb = [], None, None
    frow, brow, crow = fg[r], bg[r], chars[r]
    for c in range(c0, c1):
        f, b = tuple(frow[c]), tuple(brow[c])
        if f != lf and b != lb:
            parts.append(f"\x1b[38;2;{f[0]};{f[1]};{f[2]};48;2;{b[0]};{b[1]};{b[2]}m")
        elif f != lf:
            parts.append(f"\x1b[38;2;{f[0]};{f[1]};{f[2]}m")
        elif b != lb:
            parts.append(f"\x1b[48;2;{b[0]};{b[1]};{b[2]}m")
        lf, lb = f, b
        parts.append(crow[c])
    return "".join(parts)


TEXT_FG, TEXT_FG_OLD, TEXT_BG = (96, 214, 200), (38, 104, 102), (6, 22, 26)


def character_images(folder, frame_names, builtin_render=None):
    """Картинки кадров из папки face (с подстановкой недостающих), иначе встроенный персонаж."""
    import face_art
    if folder and os.path.isdir(folder):
        files = {os.path.splitext(f)[0].lower(): os.path.join(folder, f)
                 for f in os.listdir(folder) if f.lower().endswith(face_art.IMAGE_EXT)}
        if files:
            files.setdefault('idle', sorted(files.values())[0])
            return {n: next(files[k] for k in face_art.fallback_chain(n) if k in files) for n in frame_names}
    # встроенная Джарвис-тян: белые линии на чёрном -> тёмные линии на светлом
    return {n: Image.eval(face_art.render(n), lambda v: 255 - v) for n in frame_names}
