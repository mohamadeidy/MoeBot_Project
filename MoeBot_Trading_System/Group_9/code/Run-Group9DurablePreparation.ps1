$ErrorActionPreference = 'Stop'
$python = 'C:\Python312\python.exe'
$log = 'C:\MoeBotWork\group9_durable_preparation_20261128.log'
$manifest = Join-Path $PSScriptRoot 'runtime_manifest.json'
$expected = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
foreach ($f in $expected.files) {
    $p = Join-Path $PSScriptRoot $f.name
    if ((Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant() -ne $f.sha256) {
        throw "PINNED_RUNTIME_HASH_MISMATCH: $($f.name)"
    }
}
Add-Content -LiteralPath $log -Value ("RUN_START=" + [DateTimeOffset]::Now.ToString('o') + " COMMIT=" + $expected.commit)
# Task Scheduler excludes concurrent instances. Each stage has independently
# verified receipts; successful checkpoints are reused after reboot.
foreach ($script in @('group9_wyckoff_semantic_audit.py','group9_wyckoff_population_census.py')) {
    Add-Content -LiteralPath $log -Value ("START_STAGE=" + $script)
    $p = Join-Path $PSScriptRoot $script
    # Native stderr redirection is captured without PowerShell treating native
    # warnings as terminating exceptions. Exit code is checked explicitly.
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $python -u $p 2>&1 | ForEach-Object { $_.ToString() } | Out-File -FilePath $log -Append -Encoding utf8
    $rc = $LASTEXITCODE
    $ErrorActionPreference = $old
    Add-Content -LiteralPath $log -Value ("STAGE_EXIT=" + $script + " RC=" + $rc)
    if ($rc -ne 0) { exit $rc }
}
Add-Content -LiteralPath $log -Value 'PREPARATION_COMPLETE_ANNUAL_NOT_AUTHORIZED'
exit 0
