@echo off
rem Runs DriloReview from source, without a console window.
rem The first time it creates the environment and installs PySide6.
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
    where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
    .venv\Scripts\python.exe -m pip install PySide6-Essentials
)
start "" ".venv\Scripts\pythonw.exe" "driloreview.py" %*
