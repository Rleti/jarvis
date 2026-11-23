"""Автоподбор моделей под железо: смотрит видеопамять (NVIDIA) и оперативку.

В config.py любое значение "auto" заменяется на подходящее для этого ПК.
Своё значение (например OLLAMA_MODEL = "qwen3:14b") автоподбор не трогает.
Проверить, что выберется:  .venv\\Scripts\\python hardware.py
"""
import ctypes
import os
import subprocess

# Профили по видеопамяти. vram_mb — нижняя граница (карта «16 ГБ» показывает ~16300 МБ).
PROFILES = [
    dict(name="16+ ГБ", vram_mb=15000,
         OLLAMA_MODEL="qwen3:8b", OLLAMA_NUM_CTX=8192,
         WHISPER_MODEL="large-v3-turbo", WHISPER_DEVICE="cuda", WHISPER_COMPUTE="float16",
         TTS_ENGINE="xtts", XTTS_DEVICE="cuda", VISION_MODEL="qwen3-vl:8b"),
    dict(name="12 ГБ", vram_mb=11000,
         OLLAMA_MODEL="qwen3:8b", OLLAMA_NUM_CTX=4096,
         WHISPER_MODEL="large-v3-turbo", WHISPER_DEVICE="cuda", WHISPER_COMPUTE="int8_float16",
         TTS_ENGINE="xtts", XTTS_DEVICE="cuda", VISION_MODEL="qwen3-vl:4b"),
    dict(name="8 ГБ", vram_mb=7500,
         OLLAMA_MODEL="qwen3:4b", OLLAMA_NUM_CTX=4096,
         WHISPER_MODEL="large-v3-turbo", WHISPER_DEVICE="cuda", WHISPER_COMPUTE="int8_float16",
         TTS_ENGINE="xtts", XTTS_DEVICE="cuda", VISION_MODEL="qwen3-vl:2b"),
    dict(name="4–6 ГБ", vram_mb=3500,
         OLLAMA_MODEL="qwen3:4b", OLLAMA_NUM_CTX=4096,
         WHISPER_MODEL="small", WHISPER_DEVICE="cuda", WHISPER_COMPUTE="int8_float16",
         TTS_ENGINE="silero", XTTS_DEVICE="cpu", VISION_MODEL="qwen3-vl:2b"),
]
CPU_ONLY = dict(name="без видеокарты NVIDIA", vram_mb=0,
                OLLAMA_MODEL="qwen3:1.7b", OLLAMA_NUM_CTX=4096,
                WHISPER_MODEL="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE="int8",
                TTS_ENGINE="silero", XTTS_DEVICE="cpu", VISION_MODEL="")
KEYS = [k for k in CPU_ONLY if k.isupper()]


def gpu():
    """-> (название, МБ видеопамяти) самой большой карты NVIDIA или (None, 0)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000 if os.name == "nt" else 0)          # без мелькающего окна
        cards = []
        for line in out.stdout.strip().splitlines():
            name, mb = line.rsplit(",", 1)
            cards.append((name.strip(), int(float(mb))))
        return max(cards, key=lambda c: c[1]) if cards else (None, 0)
    except Exception:
        return None, 0


def ram_mb():
    try:
        class MS(ctypes.Structure):
            _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong),
                        ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
        m = MS(); m.len = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.total // 2**20
    except Exception:
        try:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // 2**20
        except Exception:
            return 0


_cached = None


def pick():
    global _cached
    if _cached is None:
        name, vram = gpu()
        prof = next((p for p in PROFILES if vram >= p["vram_mb"]), CPU_ONLY)
        prof = dict(prof)
        ram = ram_mb()
        if prof is not None and prof["vram_mb"] == 0 and ram >= 15000:
            prof["OLLAMA_MODEL"] = "qwen3:4b"           # без видеокарты, но памяти много — модель поумнее
        prof.update(gpu_name=name, vram=vram, ram=ram)
        _cached = prof
    return _cached


def apply(cfg: dict):
    """Заполняет значения "auto" в config.py."""
    p = pick()
    for k in KEYS:
        if cfg.get(k) == "auto":
            cfg[k] = p[k]
    cfg["HW_PROFILE"] = p["name"]


if __name__ == "__main__":
    p = pick()
    print(f"Видеокарта: {p['gpu_name'] or 'нет NVIDIA'} ({p['vram'] / 1024:.1f} ГБ), ОЗУ {p['ram'] / 1024:.0f} ГБ")
    print("Профиль:", p["name"])
    import config
    for k in KEYS:
        print(f"  {k:16} = {getattr(config, k)!r}")
