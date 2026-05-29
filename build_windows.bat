@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo [1/4] Installing Python dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo [2/4] Hardware verification...
if /I "%1"=="--verify-hardware" (
  python verify_ch347.py
  if errorlevel 1 goto :fail
) else (
  echo Skipped. Run build_windows.bat --verify-hardware to verify CH347 before packaging.
)

echo [3/4] Building DNTCLightDebug.exe...
python -m PyInstaller --noconfirm DNTCLightDebug.spec
if errorlevel 1 goto :fail

echo [4/4] Done.
echo Output: %CD%\dist\DNTCLightDebug.exe
exit /b 0

:fail
echo Build/verification failed. See messages above.
exit /b 1
