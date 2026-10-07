@echo off
rem Construye DriloReview para Windows: dist\DriloReview-<version>-portable-win64.zip
rem Crea el entorno .venv si hace falta y llama a build.py, que hace el resto.
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
    if errorlevel 1 goto :error
)
.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
.venv\Scripts\python.exe -m pip install --quiet PySide6-Essentials pyinstaller
if errorlevel 1 goto :error
.venv\Scripts\python.exe build.py
if errorlevel 1 goto :error
echo.
echo Listo: la carpeta dist\DriloReview y el zip portable.
pause
exit /b 0
:error
echo.
echo ERROR: la construccion ha fallado. Mira los mensajes de arriba.
pause
exit /b 1
