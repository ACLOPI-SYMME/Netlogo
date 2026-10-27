# Runs the API (python -m aclopi.api) in the aclopi-sim container with the L4 limits and publishes its port.
# Usage, from the repository root:
#   .\docker\run_api.ps1                 # foreground, Ctrl+C to stop
#   .\docker\run_api.ps1 -Detach         # background; prints the container id
#   .\docker\run_api.ps1 -Detach -Restart on-failure
# Extra environment: $env:ACLOPI_DOCKER_ENV, e.g. "ACLOPI_SESSION_IDLE_TIMEOUT_S=600".
param(
    [int]$Port = 8000,
    [switch]$Detach,
    [string]$Name = "aclopi-api",
    [string]$Restart = "no"
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$results = Join-Path $repoRoot "results"
New-Item -ItemType Directory -Force $results | Out-Null

$envArgs = @()
if ($env:ACLOPI_DOCKER_ENV) { $envArgs = @("-e", $env:ACLOPI_DOCKER_ENV) }
$modeArgs = @("--rm")
if ($Detach) { $modeArgs = @("-d") }
if ($Restart -ne "no") { $modeArgs = @("-d", "--restart=$Restart") }

docker run @modeArgs --name $Name `
    --cpus=4 --cpuset-cpus=0-3 --memory=6g --memory-swap=6g `
    -p "${Port}:8000" `
    -v "${results}:/app/results" `
    @envArgs `
    aclopi-sim python -m aclopi.api
exit $LASTEXITCODE
