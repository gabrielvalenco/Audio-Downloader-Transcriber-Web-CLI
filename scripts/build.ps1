# Build a standalone Windows executable using PyInstaller
Param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Err($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$venvPath = Join-Path $root ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

if (!(Test-Path $venvPython)) {
    Write-Err "Virtual environment not found. Run scripts/setup.ps1 first."
    exit 1
}

Write-Info "Installing PyInstaller..."
& $venvPython -m pip install --upgrade pyinstaller

if ($Clean) {
    Write-Info "Cleaning previous builds..."
    Remove-Item (Join-Path $root "build") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $root "dist") -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Info "Building executable..."
& $venvPython -m PyInstaller --onefile --name download_audio (Join-Path $root "src\download_audio.py")

$exe = Join-Path $root "dist\download_audio.exe"
if (Test-Path $exe) {
    Write-Info "Build complete: $exe"
} else {
    Write-Err "Build failed. Check PyInstaller output above."
    exit 1
}