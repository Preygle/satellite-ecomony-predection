@echo off
REM Run the Phase 1 pipeline using the project virtual environment.
REM   run_pipeline.bat            full run (uses Earth Engine if authenticated)
REM   run_pipeline.bat --no-gee   open data only

setlocal
set "HERE=%~dp0"

if not exist "%HERE%.venv\Scripts\python.exe" (
    echo [!] No virtual environment found at .venv
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo     .venv\Scripts\python.exe -m pip install -e .
    exit /b 1
)

if not exist "%HERE%data\raw\ghsl" (
    echo [i] No input data yet - downloading first ^(~330 MB, 30-45 min^)...
    "%HERE%.venv\Scripts\python.exe" "%HERE%scripts\prefetch.py"
    if errorlevel 1 (
        echo [!] Download failed. Re-run to resume - completed files are cached.
        exit /b 1
    )
)

"%HERE%.venv\Scripts\python.exe" -m urbanintel.pipeline %*
endlocal
