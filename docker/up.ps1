# Start the local stack (docs/deploy-local.md) with the mock agent (default) or Linea A's real agent.
#   .\docker\up.ps1              mock agent (agent-mock)
#   .\docker\up.ps1 -Agent real  real agent (profile "agent", image rebuilt so it has the current code)
# ACLOPI_AGENT_URL is set here for this command only, so the platform always talks to the agent that was
# started: it is not read from .env. Stop everything with .\docker\down.ps1.
param([ValidateSet("mock", "real")][string]$Agent = "mock")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if ($Agent -eq "real") {
    $env:ACLOPI_AGENT_URL = "http://agent:8100"
    docker compose --profile agent up -d --build
} else {
    $env:ACLOPI_AGENT_URL = "http://agent-mock:8100"
    docker compose --profile agent rm --stop --force agent  # a real agent left from an earlier start
    docker compose up -d --build
}
$code = $LASTEXITCODE
Remove-Item Env:ACLOPI_AGENT_URL
if ($code -ne 0) { exit $code }
Write-Host "Stack up with the $Agent agent. /health shows it under 'agent' (kind, url); stop it with .\docker\down.ps1"
