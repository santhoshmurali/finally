# Starts FinAlly in Docker at http://localhost:8000. Safe to run more than once.
# Usage: .\scripts\start_windows.ps1 [-Build] [-Open]
param(
    [switch]$Build,
    [switch]$Open
)

$ImageName = 'finally'
$ContainerName = 'finally-app'
$VolumeName = 'finally-data'
$Url = 'http://localhost:8000'
$StartupWaitSeconds = 10
$RepoRoot = Split-Path -Parent $PSScriptRoot

Push-Location $RepoRoot
try {
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker is not running. Start Docker Desktop and try again.' }

    docker image inspect $ImageName *> $null
    $ImageMissing = $LASTEXITCODE -ne 0
    if ($Build -or $ImageMissing) {
        docker build -t $ImageName .
        if ($LASTEXITCODE -ne 0) { throw 'docker build failed.' }
        docker image prune -f --filter 'label=finally.project=finally' *> $null
    }

    # Replace any previous container; the named volume is never touched.
    docker rm -f $ContainerName *> $null

    $RunArgs = @('run', '-d', '--name', $ContainerName, '-p', '8000:8000', '-v', "${VolumeName}:/app/db")
    if (Test-Path '.env') { $RunArgs += @('--env-file', '.env') }
    $RunArgs += $ImageName
    docker @RunArgs | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'docker run failed. See the Docker error above.' }

    # A bad configuration (for example an expired Dhan token) makes the app exit within seconds.
    $Running = 'true'
    for ($Second = 1; $Second -le $StartupWaitSeconds; $Second++) {
        Start-Sleep -Seconds 1
        $Running = docker inspect -f '{{.State.Running}}' $ContainerName
        if ($Running -ne 'true') { break }
    }
    if ($Running -ne 'true') {
        docker logs --tail 10 $ContainerName
        throw 'FinAlly exited on startup. The log lines above show why.'
    }

    Write-Host "FinAlly is starting at $Url"
    if ($Open) { Start-Process $Url }
}
catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
