@echo off
REM Train, test and run the growth model in this console window (the command-line
REM version of the demo). Prints every step, a live tree counter and the metrics.
REM   train_model.bat                  random forest, 300 trees
REM   train_model.bat --model lr       logistic regression
REM   train_model.bat --no-roads       without the road-density driver
REM   train_model.bat --help           all options

setlocal
set "HERE=%~dp0"
set "PY=%HERE%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%HERE%demo\train.py" %*
echo.
pause
endlocal
