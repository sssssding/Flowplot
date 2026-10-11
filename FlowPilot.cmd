@echo off
setlocal
pushd "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -X utf8 src\flowpilot\desktop.py %*
) else (
    python -X utf8 src\flowpilot\desktop.py %*
)
set "FLOWPILOT_EXIT=%ERRORLEVEL%"
popd
if not "%FLOWPILOT_EXIT%"=="0" pause
exit /b %FLOWPILOT_EXIT%
