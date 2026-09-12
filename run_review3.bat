@echo off
REM Review 3, end to end: tests -> pipeline -> growth models -> validation -> figures.
REM
REM   run_review3.bat           everything, reusing cached downloads (a few minutes)
REM   run_review3.bat --fetch   also re-download the Earth Engine layers and Indian datasets
REM
REM Needs internet and a one-time Earth Engine login for the pipeline and the
REM two Indian-data validations; the tests, growth models and figures run offline.
REM Every step prints its start and finish time, so the run can be shown live.

setlocal
set "HERE=%~dp0"
set "PY=%HERE%.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [!] No virtual environment found at .venv
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)

call :run "1  Unit tests"                  "%HERE%tests\test_core.py"                || goto :fail
if /i "%~1"=="--fetch" (
    call :run "   Earth Engine layers"      "%HERE%scripts\export_review3_layers.py"  || goto :fail
    call :run "   Indian datasets"          "%HERE%scripts\fetch_indian_data.py"      || goto :fail
)
call :run "2  Analysis pipeline"           "-m urbanintel.pipeline"                  || goto :fail
call :run "3  Growth models"               "%HERE%scripts\run_growth_model.py"       || goto :fail
call :run "4  Typology hold-out test"      "%HERE%scripts\validate_typology.py"      || goto :fail
call :run "5  Satellite cross-checks"      "%HERE%scripts\cross_checks.py"           || goto :fail
call :run "6  Population vs Census"        "%HERE%scripts\validate_population.py"    || goto :fail
call :run "7  Night lights vs economy"     "%HERE%scripts\validate_economy.py"       || goto :fail
call :run "8  Figures and results pack"    "%HERE%scripts\make_figures.py"           || goto :fail
call :run "9  Zone evidence cards"         "%HERE%scripts\make_zone_cards.py"        || goto :fail
call :run "10 Architecture diagrams"      "%HERE%scripts\make_diagrams.py"          || goto :fail

echo.
echo [OK] Review 3 run complete.
echo      Numbers : outputs\review3_results.json
echo      Figures : docs\figures\
echo      Diagrams: docs\diagrams\
echo      Report  : docs\REVIEW3_REPORT.md
echo      Dashboard: run_dashboard.bat
endlocal
exit /b 0

:run
echo.
echo ==== %~1   (start %time%)
if "%~2"=="-m urbanintel.pipeline" (
    "%PY%" -m urbanintel.pipeline
) else (
    "%PY%" "%~2"
)
if errorlevel 1 exit /b 1
echo ==== %~1   (done  %time%)
exit /b 0

:fail
echo.
echo [!] A step failed - see the messages above. Completed downloads are cached,
echo     so re-running resumes from where it stopped.
endlocal
exit /b 1
