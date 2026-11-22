@echo off
setlocal
cd /d "%~dp0"
python -m immich_dvd
if errorlevel 1 pause
