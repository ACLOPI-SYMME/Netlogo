# Start the local stack (docs/deploy-local.md) with Linea A's real agent (default) or the mock agent (tests only).
#   .\docker\up.ps1              real agent (profile "agent", image rebuilt so it has the current code)
#   .\docker\up.ps1 -Agent mock  mock agent (profile "mock"), only for automatic tests
# The other agent is removed first if it was left running. ACLOPI_AGENT_URL is set here for this command only,
# so the platform always talks to the agent that was started: it is not read from .env.
# Stop everything with .\docker\down.ps1.
param([ValidateSet("real", "mock")][string]$Agent = "real")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if ($Agent -eq "real") {
    docker compose --profile mock rm --stop --force agent-mock
    $env:ACLOPI_AGENT_URL = "http://agent:8100"
    docker compose --profile agent up -d --build
} else {
    docker compose --profile agent rm --stop --force agent
    $env:ACLOPI_AGENT_URL = "http://agent-mock:8100"
    docker compose --profile mock up -d --build
}
$code = $LASTEXITCODE
Remove-Item Env:ACLOPI_AGENT_URL
if ($code -ne 0) { exit $code }
Write-Host "Stack up with the $Agent agent. /health shows it under 'agent' (kind, url); stop it with .\docker\down.ps1"
