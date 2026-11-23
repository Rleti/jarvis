"""Прослушать все голоса и эффекты. Запуск: .venv\\Scripts\\python voice_demo.py"""
import sounddevice as sd

import config
from tts import EFFECTS, SR, TTS, apply_effect, voice

config.TTS_ENGINE = "silero"
tts = TTS()
phrase = "Слушаю, хозяин. Чем могу помочь?"

print("=== Голоса ===")
for speaker in ["aidar", "eugene", "baya", "kseniya", "xenia"]:
    print("Голос:", speaker)
    sd.play(tts.model.apply_tts(text=phrase, speaker=speaker, sample_rate=SR).numpy(), SR)
    sd.wait()

print("=== Эффекты (голос из config.py) ===")
base = tts.model.apply_tts(text=phrase, speaker=voice()[0], sample_rate=SR).numpy()
for name in EFFECTS:
    print("Эффект:", name)
    sd.play(apply_effect(base, name), SR)
    sd.wait()

print("Понравившееся впиши в config.py: SILERO_SPEAKER и VOICE_EFFECT")
input("Enter — выход")
