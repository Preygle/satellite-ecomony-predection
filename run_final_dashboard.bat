@echo off
REM Launch the final city dashboard with a Python that has torch and earthengine-api.

setlocal
set "HERE=%~dp0"
set "PY=python"
if exist "%HERE%.venv\Scripts\python.exe" (
    "%HERE%.venv\Scripts\python.exe" -c "import torch, ee" >nul 2>&1 && set "PY=%HERE%.venv\Scripts\python.exe"
)
"%PY%" -c "import torch, ee, streamlit, streamlit_folium" >nul 2>&1
if errorlevel 1 (
    echo [!] %PY% is missing torch, earthengine-api, streamlit or streamlit-folium.
    echo     pip install -r requirements.txt -r requirements-dl.txt streamlit-folium
    exit /b 1
)
cd /d "%HERE%"
echo Starting the dashboard at http://localhost:8501
"%PY%" -m streamlit run "%HERE%dashboard\final_app.py" %*
endlocal
