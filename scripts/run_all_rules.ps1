# Runs the headless validation for rules 1, 2 and 3 with seed 42 (Stochastic).
# Usage, from any directory:  .\scripts\run_all_rules.ps1
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$script = Join-Path $repoRoot "scripts\validate_headless.py"
$seed = 42
$failed = @()

foreach ($rule in 1, 2, 3) {
    Write-Host "=== Rule $rule, seed $seed, Stochastic ==="
    & $python $script --rule $rule --seed $seed --modeling-type Stochastic
    if ($LASTEXITCODE -ne 0) { $failed += $rule }
}

if ($failed.Count -gt 0) {
    Write-Host "Validation FAILED for rules: $($failed -join ', ')"
    exit 1
}
Write-Host "Validation OK for rules 1, 2, 3"
