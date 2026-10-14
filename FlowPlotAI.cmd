@echo off
setlocal
pushd "%~dp0"
if defined FLOWPILOT_PYTHON (
    "%FLOWPILOT_PYTHON%" -X utf8 src\flowpilot\ai_launcher.py %*
) else if exist ".venv-tests\Scripts\python.exe" (
    ".venv-tests\Scripts\python.exe" -X utf8 src\flowpilot\ai_launcher.py %*
) else if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -X utf8 src\flowpilot\ai_launcher.py %*
) else (
    python -X utf8 src\flowpilot\ai_launcher.py %*
)
set "FLOWPLOT_AI_EXIT=%ERRORLEVEL%"
popd
if not "%FLOWPLOT_AI_EXIT%"=="0" if not defined FLOWPILOT_NO_PAUSE pause
exit /b %FLOWPLOT_AI_EXIT%
