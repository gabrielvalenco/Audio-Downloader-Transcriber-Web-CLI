# Requires PowerShell 5+
Param(
    [switch]$ForceRecreateVenv
)

$ErrorActionPreference = "Stop"

function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$venvPath = Join-Path $root ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

if ($ForceRecreateVenv -and (Test-Path $venvPath)) {
    Write-Info "Removing existing virtual environment..."
    Remove-Item $venvPath -Recurse -Force
}

if (!(Test-Path $venvPython)) {
    Write-Info "Creating virtual environment..."
    python -m venv $venvPath
}

Write-Info "Upgrading pip and installing requirements..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $root "requirements.txt")

try {
    $ffmpegCmd = Get-Command ffmpeg -ErrorAction Stop
    Write-Info "FFmpeg found: $($ffmpegCmd.Source)"
} catch {
    Write-Warn "FFmpeg not found on PATH. Install via winget or choco:"
    Write-Warn " winget install Gyan.FFmpeg"
    Write-Warn " choco install ffmpeg"
}

Write-Info "Environment ready. Activate with: .\.venv\\Scripts\\activate"
Write-Info "Run CLI: .\.venv\\Scripts\\python.exe src\\download_audio.py --help"