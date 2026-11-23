"""Джарвис-тян (оригинальный персонаж) и превращение картинок в текст из точек Брайля.

Персонаж: каре с косичкой сбоку, наушники, заколка-звёздочка, худи.
Лицо собирается из частей: глаза, брови, рот, детали, жест — так получаются все эмоции,
повороты взгляда и кадры речи в каждой эмоции.
"""
import math

from PIL import Image, ImageDraw

W, H = 150, 184          # размер рисунка в пикселях -> 75 x 46 символов Брайля
INK = 255
EYE_X = (46, 82)         # левый край левого и правого глаза


# ---------------- неизменная часть ----------------
def _base(d):
    # задние волосы
    d.chord((24, 14, 126, 116), 180, 360, outline=INK, width=2)
    d.line((24, 65, 22, 128), fill=INK, width=2)
    d.line((126, 65, 128, 128), fill=INK, width=2)
    d.line((22, 128, 34, 136), fill=INK, width=2)
    d.line((128, 128, 116, 136), fill=INK, width=2)
    for x in (30, 36, 114, 120):
        d.line((x, 70, x - (2 if x < 75 else -2), 128), fill=INK, width=1)
    # лицо
    d.line((38, 62, 38, 96), fill=INK, width=2)
    d.line((112, 62, 112, 96), fill=INK, width=2)
    d.line([(38, 96), (46, 108), (58, 118), (70, 123), (80, 123), (92, 118), (104, 108), (112, 96)],
           fill=INK, width=2, joint='curve')
    d.line([(36, 60), (34, 80), (35, 100), (40, 114)], fill=INK, width=2, joint='curve')
    d.line([(114, 60), (116, 80), (115, 100), (110, 114)], fill=INK, width=2, joint='curve')
    # чёлка
    d.line([(34, 66), (40, 46), (47, 64), (56, 42), (62, 60), (70, 40), (76, 66),
            (84, 42), (92, 62), (100, 44), (108, 64), (114, 50), (116, 62)], fill=INK, width=2)
    for x0, y0, x1, y1 in ((52, 22, 46, 50), (70, 18, 66, 46), (88, 20, 92, 46), (104, 26, 108, 50)):
        d.line((x0, y0, x1, y1), fill=INK, width=1)
    # косичка
    for i in range(5):
        y = 108 + i * 11
        d.ellipse((118, y, 132, y + 12), outline=INK, width=2)
    d.polygon([(121, 164), (129, 164), (125, 172)], outline=INK)
    # наушники
    d.arc((20, 6, 130, 110), 195, 345, fill=INK, width=4)
    d.rounded_rectangle((12, 70, 30, 102), radius=6, outline=INK, width=3)
    d.rounded_rectangle((120, 70, 138, 102), radius=6, outline=INK, width=3)
    d.line((16, 80, 16, 92), fill=INK, width=2)
    d.line((134, 80, 134, 92), fill=INK, width=2)
    # заколка-звёздочка
    _star(d, 44, 36, 7, 3)
    # шея и худи
    d.line((66, 122, 66, 134), fill=INK, width=2)
    d.line((84, 122, 84, 134), fill=INK, width=2)
    d.line((66, 134, 30, 146), fill=INK, width=2)
    d.line((84, 134, 120, 146), fill=INK, width=2)
    d.line((30, 146, 18, 184), fill=INK, width=2)
    d.line((120, 146, 132, 184), fill=INK, width=2)
    d.arc((52, 124, 98, 150), 20, 160, fill=INK, width=2)
    d.line((68, 146, 66, 166), fill=INK, width=1)
    d.line((82, 146, 84, 166), fill=INK, width=1)
    d.ellipse((64, 165, 69, 170), fill=INK)
    d.ellipse((81, 165, 86, 170), fill=INK)
    d.line((50, 172, 100, 172), fill=INK, width=1)
    d.line((50, 172, 46, 184), fill=INK, width=1)
    d.line((100, 172, 104, 184), fill=INK, width=1)


def _star(d, cx, cy, r1, r2):
    pts = []
    for k in range(10):
        a = -math.pi / 2 + k * math.pi / 5
        r = r1 if k % 2 == 0 else r2
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    d.polygon(pts, fill=INK)


# ---------------- глаза ----------------
def _eye_open(d, x0, look=(0, 0), small_iris=False, lid=None):
    dx, dy = look
    d.line((x0 - 3, 69, x0 + 23, 67), fill=INK, width=3)            # ресницы
    d.line((x0 + 23, 67, x0 + 26, 62), fill=INK, width=2)
    d.ellipse((x0, 69, x0 + 22, 97), outline=INK, width=2)
    if small_iris:                                                   # удивление: маленький зрачок
        d.ellipse((x0 + 7 + dx, 77 + dy, x0 + 15 + dx, 89 + dy), fill=INK)
        d.ellipse((x0 + 8 + dx, 78 + dy, x0 + 11 + dx, 81 + dy), fill=0)
    else:
        d.ellipse((x0 + 4 + dx, 73 + dy, x0 + 18 + dx, 95 + dy), fill=INK)
        d.ellipse((x0 + 6 + dx, 75 + dy, x0 + 12 + dx, 81 + dy), fill=0)
        d.ellipse((x0 + 13 + dx, 87 + dy, x0 + 16 + dx, 90 + dy), fill=0)
    if lid:                                                          # прикрытое веко (грусть, злость)
        inner_left = x0 == EYE_X[0]
        ya, yb = lid
        if not inner_left:
            ya, yb = yb, ya
        d.polygon([(x0 - 1, 66), (x0 + 23, 66), (x0 + 23, yb), (x0 - 1, ya)], fill=0)
        d.line((x0 - 1, ya, x0 + 23, yb), fill=INK, width=2)


def _eye_closed(d, x0):
    d.arc((x0, 74, x0 + 21, 90), 20, 160, fill=INK, width=3)
    d.line((x0 - 2, 81, x0 + 2, 79), fill=INK, width=2)


def _eye_happy(d, x0):
    d.arc((x0 + 1, 76, x0 + 20, 96), 200, 340, fill=INK, width=3)    # ^


def _eye_wink(d, x0):
    d.line((x0 + 2, 84, x0 + 11, 80), fill=INK, width=3)            # >
    d.line((x0 + 2, 84, x0 + 11, 88), fill=INK, width=3)


def eyes(d, style, look=(0, 0)):
    for i, x0 in enumerate(EYE_X):
        if style == 'open':
            _eye_open(d, x0, look)
        elif style == 'closed':
            _eye_closed(d, x0)
        elif style == 'happy':
            _eye_happy(d, x0)
        elif style == 'surprised':
            _eye_open(d, x0, look, small_iris=True)
        elif style == 'sad':
            _eye_open(d, x0, (look[0], 2), lid=(78, 72))             # внешний край века ниже
        elif style == 'angry':
            _eye_open(d, x0, look, lid=(72, 79))                     # внутренний край ниже
        elif style == 'wink':
            if i == 0:
                _eye_open(d, x0, look)
            else:
                _eye_wink(d, x0)


# ---------------- брови ----------------
def brows(d, style):
    if style == 'normal':
        d.line((50, 60, 64, 58), fill=INK, width=2)
        d.line((86, 58, 100, 60), fill=INK, width=2)
    elif style == 'up':          # грусть: внутренние концы вверх
        d.line((50, 61, 64, 55), fill=INK, width=2)
        d.line((86, 55, 100, 61), fill=INK, width=2)
    elif style == 'down':        # злость: внутренние концы вниз
        d.line((50, 55, 64, 62), fill=INK, width=2)
        d.line((86, 62, 100, 55), fill=INK, width=2)
    elif style == 'raised':      # удивление
        d.arc((48, 50, 66, 60), 200, 340, fill=INK, width=2)
        d.arc((84, 50, 102, 60), 200, 340, fill=INK, width=2)


# ---------------- рот ----------------
def mouth(d, kind):
    if kind == 'smile':
        d.arc((68, 104, 82, 112), 20, 160, fill=INK, width=2)
    elif kind == 'small':
        d.ellipse((71, 106, 79, 112), outline=INK, width=2)
    elif kind == 'open':
        d.chord((67, 102, 83, 116), 0, 180, outline=INK, width=2)
        d.line((67, 109, 83, 109), fill=INK, width=2)
    elif kind == 'grin':
        d.chord((64, 101, 86, 118), 0, 180, outline=INK, width=2)
        d.line((64, 109, 86, 109), fill=INK, width=2)
        d.arc((70, 110, 80, 118), 200, 340, fill=INK, width=1)       # язычок
    elif kind == 'flat':
        d.line((70, 109, 80, 108), fill=INK, width=2)
    elif kind == 'frown':
        d.arc((68, 106, 82, 116), 200, 340, fill=INK, width=2)
    elif kind == 'pout':
        d.line([(69, 109), (72, 107), (75, 109), (78, 107), (81, 109)], fill=INK, width=2)
    elif kind == 'o':
        d.ellipse((70, 104, 80, 116), outline=INK, width=2)
    elif kind == 'wavy':
        d.line([(68, 109), (71, 107), (74, 110), (77, 107), (80, 110), (82, 108)], fill=INK, width=1)


# ---------------- детали ----------------
def blush(d, heavy=False):
    xs = (42, 45, 48, 51, 54, 96, 99, 102, 105, 108) if heavy else (44, 48, 52, 98, 102, 106)
    for x in xs:
        d.line((x, 100, x - 3, 105), fill=INK, width=1)


def extras(d, kinds):
    for k in kinds:
        if k == 'think':          # капелька у виска
            d.polygon([(118, 52), (114, 62), (122, 62)], outline=INK)
            d.ellipse((114, 58, 122, 66), outline=INK)
        elif k == 'listen':       # звуковые волны у наушника
            for r in (8, 14, 20):
                d.arc((138 - r, 86 - r, 138 + r, 86 + r), -40, 40, fill=INK, width=1)
        elif k == 'tear':
            d.polygon([(50, 96), (47, 104), (53, 104)], fill=INK)
            d.ellipse((47, 101, 53, 107), fill=INK)
        elif k == 'anger':        # «венка» в углу
            for a, b in (((108, 24), (114, 30)), ((114, 24), (108, 30)), ((111, 22), (111, 32)), ((106, 27), (116, 27))):
                d.line((*a, *b), fill=INK, width=2)
            d.rectangle((109, 25, 113, 29), fill=0)
        elif k == 'sparkle':
            for cx, cy in ((22, 40), (128, 36), (136, 58)):
                d.line((cx - 4, cy, cx + 4, cy), fill=INK, width=1)
                d.line((cx, cy - 4, cx, cy + 4), fill=INK, width=1)
        elif k == 'question':     # «?» над головой
            d.arc((112, 6, 124, 18), 180, 90, fill=INK, width=2)
            d.line((118, 18, 118, 22), fill=INK, width=2)
            d.ellipse((117, 25, 119, 27), fill=INK)
        elif k == 'exclaim':      # «!» над головой
            d.line((124, 6, 124, 18), fill=INK, width=3)
            d.ellipse((122, 22, 126, 26), fill=INK)
        elif k == 'wave':         # машет левой рукой у плеча
            d.line((30, 147, 16, 140), fill=INK, width=2)              # предплечье
            d.line((34, 156, 20, 146), fill=INK, width=2)
            d.ellipse((6, 126, 24, 146), outline=INK, width=2)         # ладонь
            for fx in (8, 12, 16, 20):
                d.line((fx, 128, fx - 2, 114), fill=INK, width=2)      # пальцы
            d.line((23, 132, 28, 124), fill=INK, width=2)              # большой палец
            d.arc((0, 108, 12, 124), 120, 220, fill=INK, width=1)      # чёрточки движения
            d.arc((22, 104, 36, 120), -40, 60, fill=INK, width=1)


# ---------------- эмоции ----------------
# эмоция: (глаза, брови, рот в покое, рот «приоткрыт», рот «открыт», детали, сильный румянец)
EMOTIONS = {
    'neutral':   ('open', 'normal', 'smile', 'small', 'open', [], False),
    'happy':     ('happy', 'normal', 'grin', 'small', 'grin', ['sparkle'], False),
    'sad':       ('sad', 'up', 'frown', 'small', 'o', ['tear'], False),
    'angry':     ('angry', 'down', 'pout', 'small', 'open', ['anger'], False),
    'surprised': ('surprised', 'raised', 'o', 'o', 'open', ['exclaim'], False),
    'shy':       ('open', 'up', 'wavy', 'small', 'small', [], True),
    'wink':      ('wink', 'normal', 'grin', 'small', 'open', ['sparkle'], False),
    'think':     ('open', 'normal', 'flat', 'small', 'open', ['think', 'question'], False),
    'wave':      ('happy', 'normal', 'grin', 'small', 'open', ['wave'], False),
}
LOOKS = {'look_left': (-3, 0), 'look_right': (3, 0), 'look_up': (1, -4), 'look_down': (0, 3)}


def render_face(emotion='neutral', talk=0, look=(0, 0), closed=False, extra=()):
    e, b, m0, m1, m2, ex, heavy = EMOTIONS.get(emotion, EMOTIONS['neutral'])
    img = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(img)
    _base(d)
    eyes(d, 'closed' if closed else e, (2, -3) if emotion == 'think' and look == (0, 0) else look)
    brows(d, b)
    mouth(d, (m0, m1, m2)[talk])
    blush(d, heavy)
    extras(d, list(ex) + list(extra))
    return img


def frame_specs():
    """Имя кадра -> параметры. Для эмоции X есть кадры X, X_talk1, X_talk2."""
    specs = {}
    for emo in EMOTIONS:
        specs[emo] = dict(emotion=emo)
        specs[f'{emo}_talk1'] = dict(emotion=emo, talk=1)
        specs[f'{emo}_talk2'] = dict(emotion=emo, talk=2)
    specs['idle'] = dict(emotion='neutral')
    specs['blink'] = dict(emotion='neutral', closed=True)
    specs['talk1'] = dict(emotion='neutral', talk=1)
    specs['talk2'] = dict(emotion='neutral', talk=2)
    specs['listen'] = dict(emotion='neutral', talk=1, look=(-1, 0), extra=('listen',))
    for name, look in LOOKS.items():
        specs[name] = dict(emotion='neutral', look=look)
    return specs


FRAMES = frame_specs()


def render(name):
    return render_face(**FRAMES[name])


def to_braille(img, threshold=128):
    """Каждые 2x4 пикселя -> один символ Брайля."""
    px = img.load()
    w, h = img.size
    bits = ((0, 0, 0x01), (0, 1, 0x02), (0, 2, 0x04), (1, 0, 0x08),
            (1, 1, 0x10), (1, 2, 0x20), (0, 3, 0x40), (1, 3, 0x80))
    lines = []
    for cy in range(0, h - h % 4, 4):
        row = []
        for cx in range(0, w - w % 2, 2):
            code = 0
            for dx, dy, bit in bits:
                if px[cx + dx, cy + dy] >= threshold:
                    code |= bit
            row.append(chr(0x2800 + code))
        lines.append(''.join(row))
    return lines


def to_ascii(img):
    """Запасной вариант для старых консолей без шрифта Брайля."""
    px = img.load()
    w, h = img.size
    ramp = ' .:-=+*#'
    lines = []
    for cy in range(0, h - h % 4, 4):
        row = []
        for cx in range(0, w - w % 2, 2):
            n = sum(1 for dx in (0, 1) for dy in range(4) if px[cx + dx, cy + dy] >= 128)
            row.append(ramp[min(n, len(ramp) - 1)])
        lines.append(''.join(row))
    return lines


def all_frames(style='braille'):
    conv = to_braille if style == 'braille' else to_ascii
    return {name: conv(render(name)) for name in FRAMES}


# ---------------- своя картинка ----------------
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif')


def image_to_bitmap(path, width_chars=75, max_rows=48, invert=False, contrast=1.4):
    """Любая картинка -> точечный рисунок с дизерингом (тени тоже превращаются в точки).
    invert=False: точки там, где на картинке темно; invert=True: где светло."""
    from PIL import ImageEnhance, ImageOps
    img = Image.open(path)
    if getattr(img, 'is_animated', False):
        img.seek(0)
    img = img.convert('RGBA')
    bg = Image.new('RGBA', img.size, (0, 0, 0, 255) if invert else (255, 255, 255, 255))
    img = Image.alpha_composite(bg, img).convert('L')
    w = width_chars * 2
    h = int(img.height * w / img.width)
    if h > max_rows * 4:
        h = max_rows * 4
        w = int(img.width * h / img.height)
    img = img.resize((max(2, w), max(4, h)), Image.LANCZOS)
    img = ImageOps.autocontrast(img, cutoff=2)
    img = ImageEnhance.Contrast(img).enhance(contrast)
    if not invert:
        img = ImageOps.invert(img)
    return img.convert('1').convert('L')


def lineart_to_bitmap(path, width_chars=75, max_rows=48, line_thr=40, fill=0.08, thick=3):
    """Для рисунков с контуром: линии -> сплошные точки, тёмная заливка (волосы, одежда) -> редкие точки,
    светлое -> пусто. Так тёмные волосы не сливаются в одно пятно, а лицо остаётся читаемым."""
    from PIL import ImageFilter
    img = Image.open(path)
    if getattr(img, 'is_animated', False):
        img.seek(0)
    img = img.convert('RGBA')
    img = Image.alpha_composite(Image.new('RGBA', img.size, (255, 255, 255, 255)), img).convert('L')
    w = width_chars * 2
    h = int(img.height * w / img.width)
    if h > max_rows * 4:
        h = max_rows * 4
        w = int(img.width * h / img.height)
    px = img.load()
    lines = img.point(lambda v: 255 if v < line_thr else 0).filter(ImageFilter.MaxFilter(thick))
    fills = img.point(lambda v: 255 if line_thr <= v < 170 else 0)
    lines = lines.resize((w, h), Image.BOX)
    fills = fills.resize((w, h), Image.BOX)
    lp, fp = lines.load(), fills.load()
    out = Image.new('L', (w, h), 0)
    op = out.load()
    for y in range(h):
        for x in range(w):
            op[x, y] = 255 if lp[x, y] > 90 else int(fp[x, y] * fill)
    return out.convert('1').convert('L')                     # дизеринг заливки


def fallback_chain(name):
    """Какой кадр взять, если нужного нет: happy_talk1 -> talk1 -> happy -> idle."""
    chain = [name]
    if '_talk' in name:
        emo, talk = name.split('_talk')
        chain += [f'talk{talk}', emo]
    if name == 'blink':
        chain.append('idle')
    chain.append('idle')
    return chain


def load_frames(style='braille', folder=None, invert=False, width_chars=75, mode='dither'):
    """Своя картинка из папки face (idle.png обязателен, остальные кадры — по желанию,
    имена как у встроенных: happy, sad, angry, surprised, shy, wink, think, wave, blink,
    talk1, talk2, happy_talk1, look_left, look_right, look_up, listen…). Иначе — встроенная Джарвис-тян."""
    import os
    conv = to_braille if style == 'braille' else to_ascii
    if folder and os.path.isdir(folder):
        files = {os.path.splitext(f)[0].lower(): os.path.join(folder, f)
                 for f in os.listdir(folder) if f.lower().endswith(IMAGE_EXT)}
        if 'idle' not in files and files:
            files['idle'] = sorted(files.values())[0]
        if files:
            cache, frames = {}, {}
            names = list(FRAMES)
            names.extend(n for n in ('wave_alt', 'wave_alt_talk1', 'wave_alt_talk2') if n in files)
            for name in names:
                path = next(files[n] for n in fallback_chain(name) if n in files)
                if path not in cache:
                    bmp = lineart_to_bitmap(path, width_chars) if mode == 'lineart' \
                        else image_to_bitmap(path, width_chars, invert=invert)
                    cache[path] = conv(bmp)
                frames[name] = cache[path]
            return frames
    return all_frames(style)


if __name__ == '__main__':
    print(len(FRAMES), 'кадров')
    for line in all_frames()['happy']:
        print(line)
