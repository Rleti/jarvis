"""Заранее скачивает модели кодового слова, Whisper и голос Silero, чтобы первый запуск был быстрым."""
import sys

import config

ok = True

try:
    import openwakeword.utils
    try:
        openwakeword.utils.download_models(model_names=[config.WAKE_MODEL])
    except TypeError:
        openwakeword.utils.download_models()
    print("  OK: wake word")
except Exception as e:
    ok = False
    print("  FAIL wake word:", e)

try:
    from faster_whisper.utils import download_model
    download_model(config.WHISPER_MODEL)
    download_model(config.WHISPER_CPU_MODEL)
    print("  OK: whisper")
except Exception as e:
    ok = False
    print("  FAIL whisper:", e)

try:
    from tts import silero_dir
    if silero_dir():
        import torch
        torch.hub.load(silero_dir(), "silero_tts", source="local", language="ru", speaker="v4_ru")
        print("  OK: silero")
    else:
        print("  SKIP: silero (not downloaded)")
except Exception as e:
    ok = False
    print("  FAIL silero:", e)

try:
    import os
    if config.TTS_ENGINE != "xtts":
        raise ImportError
    os.environ["COQUI_TOS_AGREED"] = "1"
    from TTS.api import TTS
    TTS("tts_models/multilingual/multi-dataset/xtts_v2")
    print("  OK: xtts")
except ImportError:
    print("  SKIP: xtts (not installed or not used on this GPU)")
except Exception as e:
    ok = False
    print("  FAIL xtts:", e)

sys.exit(0 if ok else 1)
