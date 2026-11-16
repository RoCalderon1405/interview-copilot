@echo off
setlocal
pushd "%~dp0" || exit /b 1

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Local Python environment not found: "%~dp0.venv\Scripts\python.exe" >&2
    echo Restore the existing .venv or follow the README setup instructions. >&2
    pause
    popd
    exit /b 1
)

echo Starting Interview Copilot API at http://127.0.0.1:8765
".venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir apps\api --host 127.0.0.1 --port 8765 --ws-max-size 64000 --ws-max-queue 4
set "api_exit_code=%errorlevel%"
if not "%api_exit_code%"=="0" (
    echo ERROR: API exited with code %api_exit_code%. >&2
    pause
)
popd
exit /b %api_exit_code%
