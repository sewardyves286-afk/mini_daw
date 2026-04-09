@echo off
title mini_daw — Compilation EXE

:: Guard contre double execution
if defined MINIDAW_BUILDING (
    echo [IGNORE] build_exe.bat deja en cours, instance ignoree.
    exit /b 0
)
set MINIDAW_BUILDING=1

echo ============================================
echo   mini_daw — Creation du .exe
echo ============================================
echo.

cd /d "%~dp0"
echo Dossier : %CD%
echo.

echo [1/4] Installation PyInstaller...
pip install pyinstaller --quiet --upgrade

echo [2/4] Nettoyage...
if exist build         rmdir /s /q build
if exist dist          rmdir /s /q dist
if exist mini_daw.exe  del mini_daw.exe
if exist mini_daw.spec del mini_daw.spec

echo [3/4] Compilation...
pyinstaller ^
  --onefile ^
  --windowed ^
  --noconsole ^
  --icon=assets\logo.ico ^
  --name=mini_daw ^
  --add-data "assets\logo.ico;assets" ^
  --add-data "assets\logo.png;assets" ^
  --collect-all sounddevice ^
  --collect-all soundfile ^
  --hidden-import numpy ^
  --hidden-import pydub ^
  --hidden-import tkinter ^
  --hidden-import tkinter.ttk ^
  --hidden-import engine ^
  --hidden-import gui ^
  --hidden-import recorder ^
  --hidden-import clip_editor ^
  --hidden-import pattern_editor ^
  --hidden-import project_manager ^
  --hidden-import metronome ^
  --hidden-import file_explorer ^
  main.py

echo [4/4] Copie...
if exist dist\mini_daw.exe (
    copy dist\mini_daw.exe mini_daw.exe
    echo.
    echo ============================================
    echo   SUCCESS : mini_daw.exe cree !
    echo.
    echo   Lance ensuite :
    echo   python create_association.py
    echo ============================================
) else (
    echo.
    echo ============================================
    echo   ERREUR : compilation echouee
    echo   Consulte les logs ci-dessus
    echo ============================================
)

set MINIDAW_BUILDING=
echo.
pause
