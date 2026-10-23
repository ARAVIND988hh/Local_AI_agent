@echo off
cd /d %USERPROFILE%\jarvis
tasklist | find /i "ollama.exe" >nul || start "" /min ollama serve
timeout /t 3 >nul
call venv\Scripts\activate
python jarvis.py
pause