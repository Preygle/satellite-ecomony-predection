@echo off
REM Live demo website: trains and runs the growth model on this laptop.
REM Opens http://127.0.0.1:8765 in the browser. Close this window to stop.
REM Works offline once the processed data is present (pipeline run or data bundle).

setlocal
set "HERE=%~dp0"
set "PY=%HERE%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%HERE%demo\server.py" %*
endlocal
