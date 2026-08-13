# Portable-сборка (exe без Python у получателя).
# Usage: powershell -File scripts\build_portable.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$PyCmd = Get-Command py -ErrorAction SilentlyContinue
if ($PyCmd) {
    $Py = $PyCmd.Source
    $PyArgs = @("-3")
} else {
    $PyExe = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PyExe) { throw "Python not found. Install Python 3.11+ and enable PATH." }
    $Py = $PyExe.Source
    $PyArgs = @()
}

Write-Host "Installing/checking PyInstaller..."
& $Py @PyArgs -m pip install --user -q pyinstaller

$DistBuild = Join-Path $Root "dist\TanionPlaning"
$Out = Join-Path $Root "dist\TanionPlaning-portable"
$Spec = Join-Path $Root "packaging\TanionPlaning.spec"

Write-Host "Building (PyInstaller onedir)..."
& $Py @PyArgs -m PyInstaller --noconfirm --clean --distpath (Join-Path $Root "dist") --workpath (Join-Path $Root "build\pyinstaller") $Spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

if (-not (Test-Path (Join-Path $DistBuild "TanionPlaning.exe"))) {
    throw "Exe not found in $DistBuild"
}

Write-Host "Copying to $Out ..."
if (Test-Path $Out) {
    Remove-Item -Recurse -Force $Out
}
New-Item -ItemType Directory -Path $Out | Out-Null
Copy-Item -Path (Join-Path $DistBuild "*") -Destination $Out -Recurse -Force

$data = Join-Path $Out "data"
New-Item -ItemType Directory -Path $data -Force | Out-Null
$tasks = Join-Path $data "tasks.xlsx"
if (Test-Path $tasks) { Remove-Item -Force $tasks }

& $Py @PyArgs -c @"
from pathlib import Path
from openpyxl import Workbook
from app.xlsx_store import COLUMNS, TASKS_SHEET
p = Path(r'$data') / 'tasks.xlsx'
wb = Workbook()
ws = wb.active
ws.title = TASKS_SHEET
ws.append(list(COLUMNS))
wb.create_sheet('lists')
wb.save(p)
print('empty xlsx:', p)
"@

$readme = @"
TanionPlaning - планировщик задач (portable)

Запуск: TanionPlaning.exe

Задачи: папка data\ рядом с программой (tasks.xlsx).
Чистая копия без чужих задач. Python не нужен.

Копируй всю папку целиком (exe + _internal + data).

Кратко:
  +          новая задача
  двойной клик  правка
  drag на тег   повесить тег
  клик по тегу  кисть -> клики по задачам
  стрелки / свайп  смена экранов
  Esc          сброс режима / fullscreen
  готово / корзина      сделано / отменена

Полное руководство: portable-user-guide.md (в этой же папке).
"@
Set-Content -Path (Join-Path $Out "README.txt") -Value $readme -Encoding UTF8

$guideSrc = Join-Path $Root "docs\portable-user-guide.md"
if (Test-Path $guideSrc) {
    Copy-Item -Path $guideSrc -Destination (Join-Path $Out "portable-user-guide.md") -Force
}

Write-Host "Done: $Out"
Get-ChildItem $Out | Select-Object Name, Length
