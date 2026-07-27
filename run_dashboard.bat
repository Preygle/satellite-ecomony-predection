@echo off
REM Launch the dashboard using the project virtual environment.
REM Avoids needing `streamlit` on PATH or the venv activated.

setlocal
set "HERE=%~dp0"

if not exist "%HERE%.venv\Scripts\python.exe" (
    echo [!] No virtual environment found at .venv
    echo     Create it first:
    echo         python -m venv .venv
    echo         .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo         .venv\Scripts\python.exe -m pip install -e .
    exit /b 1
)

if not exist "%HERE%outputs\varanasi_summary.json" (
    echo [!] No pipeline output found. Run the pipeline first:
    echo         run_pipeline.bat
    exit /b 1
)

echo Starting dashboard at http://localhost:8501
"%HERE%.venv\Scripts\python.exe" -m streamlit run "%HERE%dashboard\app.py" %*
endlocal
