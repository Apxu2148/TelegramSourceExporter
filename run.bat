@echo off
setlocal EnableExtensions

cd /d "%~dp0"
set "PYTHON=%CD%\.venv\Scripts\python.exe"
set "PIP=%CD%\.venv\Scripts\pip.exe"
set "URL=http://127.0.0.1:8501"
set "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false"

if not exist "%PYTHON%" (
    echo Creating local virtual environment: .venv
    py -3.11 -m venv .venv
    if errorlevel 1 (
        python -m venv .venv
    )
)

if not exist "%PYTHON%" (
    echo Could not create .venv. Check Python 3.10+ installation.
    pause
    exit /b 1
)

echo Installing dependencies into local .venv...
"%PIP%" install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed.
    pause
    exit /b 1
)

echo Checking existing Streamlit server: %URL%
powershell.exe -NoProfile -Command "try { $response = Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -TimeoutSec 2; if ($response.StatusCode -lt 500) { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 (
    echo Streamlit is already running. Opening: %URL%
    start "" "%URL%"
    endlocal
    exit /b 0
)

echo Opening: %URL%
start "" powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process '%URL%'"

"%PYTHON%" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501

endlocal
