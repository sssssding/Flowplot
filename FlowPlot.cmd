@echo off
setlocal
pushd "%~dp0"
if defined FLOWPILOT_PYTHON (
    "%FLOWPILOT_PYTHON%" -X utf8 src\flowpilot\launcher.py %*
) else if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -X utf8 src\flowpilot\launcher.py %*
) else (
    python -X utf8 src\flowpilot\launcher.py %*
)
set "FLOWPILOT_EXIT=%ERRORLEVEL%"
popd
if not "%FLOWPILOT_EXIT%"=="0" if not defined FLOWPILOT_NO_PAUSE pause
exit /b %FLOWPILOT_EXIT%
