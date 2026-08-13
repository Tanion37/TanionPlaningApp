@echo off
chcp 65001 >nul
cd /d "%~dp0.."

REM Без консоли: pyw, иначе pythonw. Иконка на панели задач – через AppUserModelID в приложении.
where pyw >nul 2>&1
if %ERRORLEVEL%==0 (
  start "" pyw -3 -m app
  exit /b 0
)
where pythonw >nul 2>&1
if %ERRORLEVEL%==0 (
  start "" pythonw -3 -m app
  exit /b 0
)

REM Запасной вариант с консолью
py -3 -m app
if errorlevel 1 python -m app
pause
