# Jarvis one-click installer: Python, Ollama, LLM model, packages, voice models, autostart.
# Messages are in English on purpose: Windows PowerShell 5.1 mangles Cyrillic in .ps1 files.

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Dir
$Tmp = Join-Path $env:TEMP "jarvis_setup"
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null

function Step($text) { Write-Host ""; Write-Host "=== $text ===" -ForegroundColor Cyan }
function Ok($text)   { Write-Host "  OK: $text" -ForegroundColor Green }
function Warn($text) { Write-Host "  WARNING: $text" -ForegroundColor Yellow }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}
function Download($url, $out) {
    # curl.exe ships with Windows 10/11 and shows a progress bar
    & curl.exe -L --fail --retry 3 -o $out $url
    if ($LASTEXITCODE -ne 0) { throw "Download failed: $url" }
}

# stop a running Jarvis, otherwise Windows won't let pip replace files it uses
Get-Process pythonw, python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "$Dir*" } | Stop-Process -Force -ErrorAction SilentlyContinue

# ---------------- 1. Python 3.11 ----------------
Step "1/7 Python"
$Py = $null
foreach ($cand in @(
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Program Files\Python312\python.exe")) {
    if (Test-Path $cand) { $Py = $cand; break }
}
if (-not $Py) {
    Write-Host "  Python not found, installing 3.11.9..."
    $inst = Join-Path $Tmp "python-3.11.9-amd64.exe"
    Download "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" $inst
    Start-Process $inst -Wait -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0"
    $Py = "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    if (-not (Test-Path $Py)) { throw "Python install failed" }
}
Ok $Py

# ---------------- 2. Ollama ----------------
Step "2/7 Ollama"
Refresh-Path
$Ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
if (-not (Test-Path $Ollama)) {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { $Ollama = $cmd.Source }
}
if (-not (Test-Path $Ollama)) {
    Write-Host "  Ollama not found, installing..."
    $inst = Join-Path $Tmp "OllamaSetup.exe"
    Download "https://ollama.com/download/OllamaSetup.exe" $inst
    Start-Process $inst -Wait -ArgumentList "/VERYSILENT /NORESTART /SUPPRESSMSGBOXES"
    Refresh-Path
    if (-not (Test-Path $Ollama)) { throw "Ollama install failed" }
}
Ok $Ollama

function Ollama-Up {
    try { Invoke-RestMethod "http://127.0.0.1:11434/api/version" -TimeoutSec 3 | Out-Null; return $true }
    catch { return $false }
}
if (-not (Ollama-Up)) {
    Start-Process $Ollama -ArgumentList "serve" -WindowStyle Hidden
    for ($i = 0; $i -lt 30 -and -not (Ollama-Up); $i++) { Start-Sleep 1 }
}
if (-not (Ollama-Up)) { throw "Ollama server did not start" }
Ok "Ollama server is running"

# ---------------- 3. Virtual environment + packages ----------------
Step "3/7 Python packages (several GB, takes a while)"
$VenvPy = Join-Path $Dir ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) { & $Py -m venv .venv }
& $VenvPy -m pip install --upgrade pip --quiet
# PyTorch 2.8 with CUDA 12.8 (RTX 50xx support). Not newer: 2.9+ needs torchcodec + system FFmpeg for XTTS.
$Torch = @("torch==2.8.0", "torchaudio==2.8.0", "--index-url", "https://download.pytorch.org/whl/cu128")
& $VenvPy -m pip install @Torch
if ($LASTEXITCODE -ne 0) { throw "PyTorch install failed" }
& $VenvPy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
& $VenvPy -m pip install coqui-tts
if ($LASTEXITCODE -ne 0) { Warn "XTTS (own voice) failed to install - Silero voice will be used" }
& $VenvPy -m pip install @Torch      # coqui-tts may pull a newer torch - pin 2.8 back
Ok "packages installed"

# ---------------- 4. LLM model ----------------
Step "4/7 Language model"
& $VenvPy hardware.py            # shows GPU / RAM and the picked model profile
$Model = (& $VenvPy -c "import config; print(config.OLLAMA_MODEL)").Trim()
Write-Host "  Model: $Model"
& $Ollama pull $Model
if ($LASTEXITCODE -ne 0) { throw "ollama pull failed" }
Ok $Model
$Vision = (& $VenvPy -c "import config; print(config.VISION_MODEL)").Trim()
if ($Vision) {
    Write-Host "  Vision model: $Vision"
    & $Ollama pull $Vision
    if ($LASTEXITCODE -ne 0) { Warn "vision model failed, 'what is on screen' will not work" } else { Ok $Vision }
} else { Warn "vision disabled for this GPU" }

# ---------------- 5. Silero voice (GitHub is often throttled) ----------------
Step "5/7 Silero voice"
$HubDir = Join-Path $env:USERPROFILE ".cache\torch\hub"
$Silero = Join-Path $HubDir "snakers4_silero-models_master"
if (-not (Test-Path (Join-Path $Silero "hubconf.py"))) {
    New-Item -ItemType Directory -Force -Path $HubDir | Out-Null
    $zip = Join-Path $Tmp "silero.zip"
    # abort if slower than 20 KB/s for 30 s (throttled GitHub) instead of hanging for hours
    & curl.exe -L --fail --retry 2 --speed-limit 20000 --speed-time 30 -o $zip `
        "https://github.com/snakers4/silero-models/archive/refs/heads/master.zip"
    if ($LASTEXITCODE -eq 0) {
        $ex = Join-Path $Tmp "silero_x"
        if (Test-Path $ex) { Remove-Item $ex -Recurse -Force }
        Expand-Archive $zip -DestinationPath $ex -Force
        if (Test-Path $Silero) { Remove-Item $Silero -Recurse -Force }
        Move-Item (Join-Path $ex "silero-models-master") $Silero
        Ok "Silero code downloaded"
    } else {
        Warn "GitHub is too slow. Jarvis will use the Windows voice for now."
        Warn "Turn on a VPN and run setup.bat again to get the Silero voice."
    }
} else { Ok "already downloaded" }

# ---------------- 6. Pre-download wake word, Whisper, Silero weights ----------------
Step "6/7 Speech models"
& $VenvPy prefetch.py
if ($LASTEXITCODE -ne 0) { Warn "some models failed, they will be retried on first start" }

# ---------------- Minecraft companion (Node.js + mineflayer) ----------------
Step "Minecraft companion"
Refresh-Path
$Node = $null
$cmd = Get-Command node -ErrorAction SilentlyContinue
if ($cmd) { $Node = $cmd.Source } elseif (Test-Path "C:\Program Files\nodejs\node.exe") { $Node = "C:\Program Files\nodejs\node.exe" }
if (-not $Node) {
    Write-Host "  Node.js not found, installing LTS via winget..."
    try {
        winget install -e --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements
        Refresh-Path
        if (Test-Path "C:\Program Files\nodejs\node.exe") { $Node = "C:\Program Files\nodejs\node.exe" }
    } catch { }
}
if ($Node) {
    $Npm = Join-Path (Split-Path $Node) "npm.cmd"
    Push-Location (Join-Path $Dir "minecraft")
    & $Npm install --legacy-peer-deps --no-audit --no-fund
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -eq 0) { Ok "Minecraft bot installed" } else { Warn "npm install failed - Minecraft companion will not work" }
} else {
    Warn "Node.js not installed - install it from https://nodejs.org (LTS) and run setup.bat again"
}

# ---------------- 7. Autostart + launch ----------------
Step "7/7 Autostart"
$PyW = Join-Path $Dir ".venv\Scripts\pythonw.exe"
$lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "Jarvis.lnk"
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = $PyW
$s.Arguments = '"' + (Join-Path $Dir "jarvis.py") + '"'
$s.WorkingDirectory = $Dir
$s.Save()
Ok "Jarvis will start with Windows"

# web interface for the phone: allow port 8765 on home (private) networks
try {
    Start-Process -FilePath (Join-Path $Dir "allow_web_firewall.bat") -Verb RunAs -Wait
    Ok "firewall: web interface allowed on home network"
} catch { Warn "firewall rule skipped - run allow_web_firewall.bat later to use Jarvis from the phone" }

Start-Process $PyW -ArgumentList ('"' + (Join-Path $Dir "jarvis.py") + '"') -WorkingDirectory $Dir
Write-Host ""
Write-Host "ALL DONE. Jarvis is starting (tray icon). Hold Right Ctrl and speak." -ForegroundColor Green
