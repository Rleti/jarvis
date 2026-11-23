@echo off
cd /d "%~dp0"
if "%~1"=="" (
  echo Drag and drop an audio file onto this .bat
  pause
  exit /b
)
.venv\Scripts\python -c "import sys, librosa, soundfile as sf; a, sr = librosa.load(sys.argv[1], sr=22050, mono=True); a = a[: sr * 30]; sf.write('voices/my_voice.wav', a, sr); print('Saved voices/my_voice.wav, seconds:', round(len(a) / sr, 1))" "%~1"
pause
