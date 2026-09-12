@echo off
title AURA
cd /d "D:\AURA\AURA"

:: Start server in its own minimized window (NOT /B — that detaches audio).
:: The window title "AURA Server" lets us target it cleanly on shutdown.
start "AURA Server" /MIN ".venv\Scripts\python.exe" server.py

:: Launch GUI in the foreground
".venv\Scripts\python.exe" roadmap_gui.py

:: When GUI closes, kill ONLY the server window, not every python.exe
taskkill /F /FI "WINDOWTITLE eq AURA Server" >nul 2>&1
