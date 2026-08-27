@echo off
title Monitor Peppinopizza
cd /d "%~dp0"
:loop
python monitor_web.py
echo Se cerro el monitor. Reintentando en 30s...
timeout /t 30 /nobreak
goto loop
