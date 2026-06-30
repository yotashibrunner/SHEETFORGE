<#
  run.ps1 — SheetForge launcher

  Sets up the environment (venv Python, LibreOffice on PATH, API-key check) and
  runs forge_trends.py, forwarding any arguments you pass.

  Examples:
    .\run.ps1                       # safe smoke test: --offline (no network, no API spend)
    .\run.ps1 --offline --build --top 2
    .\run.ps1 --build --top 8       # live trend discovery + build
    .\run.ps1 --etsy --ip-check     # extra signal sources

  Any flags you pass are handed straight to forge_trends.py (see its --help).
#>
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ForgeArgs
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Default to the safe, no-spend smoke test when called with no arguments.
if (-not $ForgeArgs -or $ForgeArgs.Count -eq 0) {
    $ForgeArgs = @("--offline")
    Write-Host "No args given -> running the offline smoke test (--offline)." -ForegroundColor Yellow
    Write-Host "For a real build:  .\run.ps1 --build --top 8`n" -ForegroundColor Yellow
}

# --- Python: prefer the project venv, fall back to whatever's on PATH ----------
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = "python"
    Write-Host "[run] .venv not found; using system python." -ForegroundColor Yellow
    Write-Host "      Set it up: python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt" -ForegroundColor Yellow
}

# --- LibreOffice: needed for the QA gate + PDFs; put soffice on PATH -----------
if (-not (Get-Command soffice -ErrorAction SilentlyContinue)) {
    $candidates = @(
        "C:\Program Files\LibreOffice\program",
        "C:\Program Files (x86)\LibreOffice\program"
    )
    $loDir = $candidates | Where-Object { Test-Path (Join-Path $_ "soffice.exe") } | Select-Object -First 1
    if ($loDir) {
        $env:PATH = "$loDir;$env:PATH"
        Write-Host "[run] LibreOffice added to PATH for this run ($loDir)." -ForegroundColor DarkGray
    } else {
        Write-Host "[run] WARNING: LibreOffice (soffice) not found. The QA gate will reject every" -ForegroundColor Red
        Write-Host "      build (total_errors: -1). Install it or set `$env:SOFFICE_BIN. See README." -ForegroundColor Red
    }
}

# --- API key: only the build/listing steps need it ----------------------------
$wantsBuild = $ForgeArgs -contains "--build"
if ($wantsBuild -and -not $env:ANTHROPIC_API_KEY) {
    Write-Host "[run] WARNING: ANTHROPIC_API_KEY is not set, but --build needs it for the spec" -ForegroundColor Red
    Write-Host "      and listing steps. Set it:  `$env:ANTHROPIC_API_KEY = 'sk-ant-...'" -ForegroundColor Red
}

# --- Launch -------------------------------------------------------------------
Write-Host "[run] $py forge_trends.py $($ForgeArgs -join ' ')`n" -ForegroundColor Cyan
& $py forge_trends.py @ForgeArgs
exit $LASTEXITCODE
