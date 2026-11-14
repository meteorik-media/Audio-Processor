@echo off
cd /d "%~dp0"
where python >nul 2>nul && (python audio_processor.py serve) || (py audio_processor.py serve)
if errorlevel 1 pause
