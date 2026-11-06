# Build the FinAlly image if needed and start the container on http://localhost:8000.
# Usage: scripts\start_windows.ps1 [-Build] [-Open]
param(
    [switch]$Build,
    [switch]$Open
)

$ErrorActionPreference = "Stop"
$Image = "finally"
$Container = "finally"
$Port = 8000
$Url = "http://localhost:$Port"

Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".env")) {
    Write-Error "Missing .env. Copy .env.example to .env and fill it in."
    exit 1
}

$imageId = docker images -q $Image
if ($Build -or -not $imageId) {
    docker build -t $Image .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

docker rm -f $Container 2>$null | Out-Null
docker run -d --name $Container -p "${Port}:8000" --env-file .env `
    -v finally-data:/app/db --restart unless-stopped $Image | Out-Null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Output "FinAlly is running at $Url"

if ($Open) {
    Start-Process $Url
}
