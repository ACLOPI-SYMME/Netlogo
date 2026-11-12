# Stop and remove the WHOLE local stack, the real agent included (docs/deploy-local.md).
# `docker compose down` alone ignores the services of profiles that are not active (the real agent is in
# the "agent" profile), so it would keep running; --profile "*" includes every profile.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
docker compose --profile "*" down --remove-orphans
exit $LASTEXITCODE
