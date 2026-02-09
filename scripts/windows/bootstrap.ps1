param(
  [switch]$Dev = $true,
  # Requested Python version for the launcher, e.g. 3.12, 3.13
  [string]$PyVersion = "3.12"
)

$ErrorActionPreference = "Stop"

function Get-PyLauncher {
  $cmd = Get-Command py -ErrorAction SilentlyContinue
  if ($null -eq $cmd) { return $null }
  return $cmd.Source
}

function Get-InstalledPythonVersions {
  # Returns versions like "3.13", "3.12"
  $py = Get-PyLauncher
  if ($null -eq $py) { return @() }

  $out = & $py --list 2>$null
  if ($LASTEXITCODE -ne 0) { return @() }

  $versions = @()
  foreach ($line in ($out -split "`r?`n")) {
    if ($line -match "\b(\d+\.\d+)(?:-\d+)?\b") {
      $versions += $Matches[1]
    }
  }

  return ($versions | Sort-Object -Unique)
}

function Assert-Python312PlusInstalled {
  $py = Get-PyLauncher
  if ($null -eq $py) {
    throw "Python launcher 'py' not found. Install Python 3.12+ and re-run."
  }

  $installed = Get-InstalledPythonVersions
  if ($installed.Count -eq 0) {
    throw "Python launcher found, but no runtimes detected. Run: py --list   (or set PYLAUNCHER_ALLOW_INSTALL=1 to allow installing via winget/Microsoft Store)."
  }

  $ok = $false
  foreach ($v in $installed) {
    try {
      if ([version]$v -ge [version]"3.12") { $ok = $true; break }
    } catch {
      # ignore parse issues
    }
  }

  if (-not $ok) {
    throw ("No suitable Python runtime found (need Python >= 3.12). Detected: " + ($installed -join ", ") + ". Install Python 3.12+ and re-run.")
  }
}

Assert-Python312PlusInstalled

if (-not (Test-Path ".venv")) {
  $py = Get-PyLauncher
  $installed = Get-InstalledPythonVersions

  # Try the requested version first, then highest installed >= 3.12.
  $candidates = @($PyVersion) + ($installed | Sort-Object { [version]$_ } -Descending)
  $used = $null

  foreach ($v in $candidates) {
    try {
      if ([version]$v -lt [version]"3.12") { continue }
    } catch {
      continue
    }

    & $py "-$v" -m venv .venv 2>$null
    if ($LASTEXITCODE -eq 0 -and (Test-Path ".venv")) { $used = $v; break }
  }

  if ($null -eq $used) {
    throw "Failed to create .venv. Run 'py --list' to see installed versions, then retry with: .\\scripts\\windows\\bootstrap.ps1 -PyVersion 3.12"
  }
}

if (-not (Test-Path ".venv\\Scripts\\Activate.ps1")) {
  throw "Virtualenv activation script not found at .venv\\Scripts\\Activate.ps1. Something went wrong creating the venv."
}

& .\.venv\Scripts\Activate.ps1
python -m pip install -U pip

if ($Dev) {
  python -m pip install -e ".[dev,gui]"
} else {
  python -m pip install -e ".[gui]"
}

Write-Host "Ready. Try: gpt-web-driver demo --dry-run   (or --no-dry-run)" -ForegroundColor Green
Write-Host "Run tests: python -m pytest" -ForegroundColor Green
