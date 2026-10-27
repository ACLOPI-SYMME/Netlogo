# L5.2: time from `docker run` until /health/ready answers 200 (container start + Python + 7 warmed-up workers).
# Usage, from the repository root (image aclopi-sim already built):
#   .\scripts\l5\measure_api_ready.ps1 [-Port 8000]
param([int]$Port = 8000, [int]$TimeoutS = 600)

$name = "aclopi-api-ready"
docker rm -f $name 2>$null | Out-Null
$sw = [System.Diagnostics.Stopwatch]::StartNew()
& (Join-Path $PSScriptRoot "..\..\docker\run_api.ps1") -Port $Port -Detach -Name $name | Out-Null
$firstLive = $null
$statuses = New-Object System.Collections.Generic.List[string]
while ($true) {
    if ($sw.Elapsed.TotalSeconds -gt $TimeoutS) { Write-Output "TIMEOUT"; break }
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://localhost:$Port/health/ready"
        if ($null -eq $firstLive) { $firstLive = $sw.Elapsed.TotalSeconds }
        if ($r.StatusCode -eq 200) { break }
    } catch {
        $resp = $_.Exception.Response
        if ($null -ne $resp) {
            if ($null -eq $firstLive) { $firstLive = $sw.Elapsed.TotalSeconds }
            $code = [int]$resp.StatusCode
            if (-not $statuses.Contains("$code")) { $statuses.Add("$code") }
        }
    }
    Start-Sleep -Milliseconds 250
}
$ready = $sw.Elapsed.TotalSeconds
$health = Invoke-RestMethod "http://localhost:$Port/health"
Write-Output ("first HTTP answer: {0:N1} s" -f $firstLive)
Write-Output ("/health/ready codes before ready: {0}" -f ($statuses -join ","))
Write-Output ("ready (200): {0:N1} s after docker run" -f $ready)
Write-Output ("health: status={0} startup_s={1} workers ready={2}" -f $health.status, $health.startup_s, (@($health.workers | Where-Object { $_.ready }).Count))
docker stop $name | Out-Null
docker logs $name 2>&1 | Select-Object -Last 3
docker rm $name | Out-Null
