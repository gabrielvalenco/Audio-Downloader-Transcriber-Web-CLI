# Downloads and installs a local FFmpeg under tools/ffmpeg
$ErrorActionPreference = "Stop"
function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Err($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$tools = Join-Path $root "tools"
New-Item -ItemType Directory -Force -Path $tools | Out-Null

$url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$zipPath = Join-Path $tools "ffmpeg-release-essentials.zip"
$destPath = $tools

Write-Info "Downloading FFmpeg release essentials from: $url"
Invoke-WebRequest -Uri $url -OutFile $zipPath

Write-Info "Extracting archive..."
Expand-Archive -Path $zipPath -DestinationPath $destPath -Force

$ffDir = Get-ChildItem -Directory $destPath | Where-Object { $_.Name -like "ffmpeg*essentials*" } | Select-Object -First 1
if (-not $ffDir) {
    Write-Err "Failed to locate extracted FFmpeg folder."
    exit 1
}

$binPath = Join-Path $ffDir.FullName "bin"
if (-not (Test-Path (Join-Path $binPath "ffmpeg.exe"))) {
    Write-Err "ffmpeg.exe not found in $binPath"
    exit 1
}

Write-Info "FFmpeg installed locally at: $binPath"
Write-Info "Use with the CLI via: --ffmpeg '$binPath'"