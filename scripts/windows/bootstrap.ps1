param(
  [switch]$Dev = $true
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
  py -3.12 -m venv .venv
}

& .\.venv\Scripts\Activate.ps1
python -m pip install -U pip

if ($Dev) {
  python -m pip install -e ".[dev]"
} else {
  python -m pip install -e .
}

Write-Host "Ready. Try: spec2-hybrid demo --dry-run   (or --no-dry-run)" -ForegroundColor Green

