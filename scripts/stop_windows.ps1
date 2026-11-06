# Stop and remove the FinAlly container and image, then clean up the superseded
# images that earlier rebuilds left behind. The finally-data volume is kept.
$ErrorActionPreference = "Continue"

docker rm -f finally 2>$null | Out-Null
docker rmi finally 2>$null | Out-Null

# Only dangling images carrying the app=finally label are removed, so other
# projects' unused images on this machine are left alone.
$pruned = docker image prune -f --filter "label=app=finally" 2>$null
$removed = @($pruned | Where-Object { $_ -match "^deleted:" }).Count

Write-Output "FinAlly stopped. Data volume finally-data was kept."
if ($removed -gt 0) { Write-Output "Removed $removed unused FinAlly image(s)." }
