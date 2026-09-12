@echo off
setlocal EnableExtensions

rem Always run relative to this repository, including when launched by double-click.
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [CryptoScope] No .venv Python or system python was found.
        echo Create the environment first:
        echo   py -m venv .venv
        echo   .venv\Scripts\python.exe -m pip install -r webapp\requirements-server.txt
        exit /b 1
    )
    set "PYTHON=python"
)

if not exist "%~dp0scripts\run_radar_measurement.py" (
    echo [CryptoScope] scripts\run_radar_measurement.py was not found.
    exit /b 1
)

rem No arguments: show usage instead of silently starting a scan.
if "%~1"=="" (
    echo Usage examples:
    echo   run_cloudflare_radar.cmd --top 1000 --resume
    echo   run_cloudflare_radar.cmd --top 1000 --measure-policy --authorization-manifest scope.json --resume
    echo.
    "%PYTHON%" "%~dp0scripts\run_radar_measurement.py" --help
    exit /b 0
)

"%PYTHON%" "%~dp0scripts\run_radar_measurement.py" %*
set "EXITCODE=%ERRORLEVEL%"
if "%EXITCODE%"=="2" (
    echo [CryptoScope] The coverage threshold was not reached; results were kept. Use --resume to continue.
)
exit /b %EXITCODE%
