# Stops FinAlly and removes its container and image. The finally-data volume is kept.
# Usage: .\scripts\stop_windows.ps1

$ImageName = 'finally'
$ContainerName = 'finally-app'

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Docker is not running, so there is nothing to stop.'
    exit 0
}

docker rm -f $ContainerName *> $null
docker image rm $ImageName *> $null
docker image prune -f --filter 'label=finally.project=finally' *> $null
Write-Host 'FinAlly stopped. Data in the finally-data volume is kept.'
exit 0
