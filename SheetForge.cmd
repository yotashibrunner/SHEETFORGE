@echo off
setlocal enabledelayedexpansion
title SheetForge
cd /d "%~dp0"

:menu
cls
echo ==============================================
echo               S H E E T F O R G E
echo ==============================================
echo.
echo   [1]  Offline smoke test   (no network, no API key)
echo   [2]  Build 2 products     (offline signals)   *needs API key
echo   [3]  Build 8 products     (live trends)        *needs API key
echo   [4]  Custom flags
echo   [Q]  Quit
echo.
set "choice="
set /p "choice=Choose an option: "

if /i "%choice%"=="1" set "ARGS=--offline" & goto run
if /i "%choice%"=="2" set "ARGS=--offline --build --top 2" & goto needkey
if /i "%choice%"=="3" set "ARGS=--build --top 8" & goto needkey
if /i "%choice%"=="4" goto custom
if /i "%choice%"=="Q" goto end
echo.
echo Invalid choice. Press a key to try again.
pause >nul
goto menu

:custom
echo.
echo Enter forge_trends flags (e.g. --build --top 4 --etsy):
set "ARGS="
set /p "ARGS=> "
echo %ARGS% | find "--build" >nul && goto needkey
goto run

:needkey
if not "%ANTHROPIC_API_KEY%"=="" goto run
echo.
echo This build needs your Anthropic API key.
echo (Tip: run  setx ANTHROPIC_API_KEY "sk-ant-..."  once to skip this every time.)
set "ANTHROPIC_API_KEY="
set /p "ANTHROPIC_API_KEY=Paste API key: "
if "%ANTHROPIC_API_KEY%"=="" (
    echo No key entered - returning to menu. Press a key.
    pause >nul
    goto menu
)
goto run

:run
echo.
echo Launching: forge_trends.py %ARGS%
echo ----------------------------------------------
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %ARGS%
echo ----------------------------------------------
echo Done. Outputs (if any) are in the .\catalog folder.
echo.
pause
goto menu

:end
endlocal
