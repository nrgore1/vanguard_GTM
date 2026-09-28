# Vanguard-GTM one-click start (Windows PowerShell).
# Run from this folder with:   powershell -ExecutionPolicy Bypass -File .\start.ps1
# First run: finds Python 3.11+, creates .venv, installs, creates .env and your two sign-ins.
# Every run after that: just starts the web app at http://localhost:8080
param([switch]$Demo)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Test-Py([string[]]$cmd) {
    try {
        $exe = $cmd[0]; $args0 = @(); if ($cmd.Length -gt 1) { $args0 = $cmd[1..($cmd.Length-1)] }
        $out = & $exe @args0 -c "import sys; print(int(sys.version_info >= (3, 11)), sys.version.split()[0])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out -match '^1 ') { return $out.Split(' ')[1] }
    } catch { }
    return $null
}

$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    $candidates = @(
        @("py", "-3.13"), @("py", "-3.12"), @("py", "-3.11"), @("py", "-3"),
        @("python"), @("python3"),
        @("$env:USERPROFILE\anaconda3\python.exe"),
        @("$env:USERPROFILE\miniconda3\python.exe"),
        @("$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"),
        @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"),
        @("$env:LOCALAPPDATA\Programs\Python\Python311\python.exe")
    )
    $found = $null
    foreach ($c in $candidates) {
        $v = Test-Py $c
        if ($v) { $found = $c; Write-Host "Using Python $v -> $($c -join ' ')"; break }
    }
    if (-not $found) {
        Write-Host ""
        Write-Host "No Python 3.11+ found. Install it with:" -ForegroundColor Yellow
        Write-Host "    winget install Python.Python.3.12"
        Write-Host "then close PowerShell, open a new window, and run this script again."
        exit 1
    }
    Write-Host "Creating .venv ..."
    $exe = $found[0]; $rest = @(); if ($found.Length -gt 1) { $rest = $found[1..($found.Length-1)] }
    & $exe @rest -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "could not create .venv" }
    Write-Host "Installing Vanguard-GTM (about a minute) ..."
    & $venvPy -m pip install --upgrade pip -q
    & $venvPy -m pip install -e . -q
    if ($LASTEXITCODE -ne 0) { throw "pip install failed - see the messages above" }
}

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Created .env from .env.example" }

# load .env into this session
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
        $val = ($matches[2] -replace '\s+#.*$', '').Trim()
        if ($val -ne '') { [Environment]::SetEnvironmentVariable($matches[1], $val, "Process") }
    }
}

$vg = Join-Path $PSScriptRoot ".venv\Scripts\vanguard.exe"
if (-not (Test-Path "data\users_seeded.flag")) {
    Write-Host ""
    Write-Host "Creating your sign-ins. SAVE THESE PASSWORDS - they are shown only once:" -ForegroundColor Yellow
    & $vg seed-users
    New-Item -ItemType Directory -Force data | Out-Null
    New-Item -ItemType File -Force "data\users_seeded.flag" | Out-Null
    Write-Host ""
    Read-Host "Press Enter once you've saved the passwords"
}
if ($Demo) { & $vg demo-data }

Write-Host ""
Write-Host "Starting Vanguard-GTM at http://localhost:8080  (press Ctrl+C to stop)" -ForegroundColor Green
Start-Process "http://localhost:8080"
& $vg serve --host 127.0.0.1 --port 8080
