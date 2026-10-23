# Runs a command in the aclopi-sim container with the limits used for every L4 measurement.
# Usage, from the repository root (arguments are passed to the container unchanged):
#   .\docker\run.ps1 python scripts/run_all_rules.py
#   .\docker\run.ps1 bash -c 'python -m pytest -q'
# Extra environment for the container: set $env:ACLOPI_DOCKER_ENV, e.g. "ACLOPI_JVM_ARGS=-Xmx768m".

$repoRoot = Split-Path -Parent $PSScriptRoot
$results = Join-Path $repoRoot "results"
New-Item -ItemType Directory -Force $results | Out-Null

$envArgs = @()
if ($env:ACLOPI_DOCKER_ENV) { $envArgs = @("-e", $env:ACLOPI_DOCKER_ENV) }

docker run --rm `
    --cpus=4 --cpuset-cpus=0-3 --memory=6g --memory-swap=6g `
    -v "${results}:/app/results" `
    @envArgs `
    aclopi-sim @args
exit $LASTEXITCODE
