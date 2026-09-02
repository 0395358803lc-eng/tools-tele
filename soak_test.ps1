param([double]$Hours = 8, [int]$IntervalSeconds = 30)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Out = Join-Path $Root "data\logs\soak.csv"
New-Item -ItemType Directory -Force -Path (Split-Path $Out) | Out-Null
"timestamp,health,database,connected,working_set_mb,cpu_seconds" | Set-Content $Out
$End = (Get-Date).AddHours($Hours)
while ((Get-Date) -lt $End) {
    $health = Invoke-RestMethod -TimeoutSec 5 http://127.0.0.1:8000/api/health
    $connection = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction Stop | Select-Object -First 1
    $process = Get-Process -Id $connection.OwningProcess
    $line = '{0},{1},{2},{3},{4:N1},{5:N1}' -f (
        (Get-Date).ToString('s'), $health.ok, $health.database,
        $health.clients.connected, ($process.WorkingSet64 / 1MB), $process.CPU
    )
    Add-Content $Out $line
    Start-Sleep -Seconds $IntervalSeconds
}
Write-Host "Soak test completed: $Out"
