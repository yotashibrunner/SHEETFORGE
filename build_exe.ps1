<#
  build_exe.ps1 — package forge_gui.py into SheetForge.exe with PyInstaller.

  Produces .\dist\SheetForge.exe and copies it to the project root so it sits next
  to forge_trends.py / .venv (the GUI looks for those alongside itself).

  Run:  .\build_exe.ps1
  Optional: drop an icon.ico in the project root and it will be used.
#>
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Write-Host "[build] ensuring PyInstaller is installed..." -ForegroundColor Cyan
& $py -m pip install --quiet --upgrade pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed" }

$iconArgs = @()
if (Test-Path ".\icon.ico") {
    $iconArgs = @("--icon", ".\icon.ico")
    Write-Host "[build] using icon.ico" -ForegroundColor DarkGray
}

Write-Host "[build] running PyInstaller (onefile, windowed)..." -ForegroundColor Cyan
& $py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name SheetForge @iconArgs forge_gui.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Copy-Item ".\dist\SheetForge.exe" ".\SheetForge.exe" -Force
Write-Host "`n[build] Done -> .\SheetForge.exe (and .\dist\SheetForge.exe)" -ForegroundColor Green
Write-Host "[build] Double-click SheetForge.exe to launch. Keep it in this folder." -ForegroundColor Green
