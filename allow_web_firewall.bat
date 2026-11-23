@echo off
rem Allows the phone on your home network to open the Jarvis web interface (port 8765).
net session >nul 2>&1 || (powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" & exit /b)
netsh advfirewall firewall delete rule name="Jarvis web" >nul 2>&1
netsh advfirewall firewall add rule name="Jarvis web" dir=in action=allow protocol=TCP localport=8765 profile=private,domain
echo.
echo Done: phone can now open Jarvis web interface (port 8765, home network only).
pause
