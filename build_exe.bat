@echo off
REM Baut die .exe-Dateien unter Windows. Voraussetzung: Python 3.10+ (python.org)
REM Aufruf: build_exe.bat   (im Projektordner)
setlocal
cd /d "%~dp0"
if not exist .venv-build (
    python -m venv .venv-build || goto :fehler
)
call .venv-build\Scripts\activate.bat || goto :fehler
python -m pip install --upgrade pip || goto :fehler
python -m pip install -r requirements-build.txt || goto :fehler
python -m unittest discover -s tests -t . || goto :fehler
pyinstaller --noconfirm --clean packaging\secret_sanitizer.spec || goto :fehler
echo.
echo Fertig. Die Programme liegen im Ordner dist\
goto :eof
:fehler
echo.
echo Build fehlgeschlagen (siehe Meldungen oben).
exit /b 1
