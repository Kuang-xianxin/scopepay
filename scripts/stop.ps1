$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$record = Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'runtime.json') | ConvertFrom-Json
$process = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
if (-not $process) { Write-Output 'Recorded process is already stopped.'; exit 0 }
$recordedStart = [datetime]$record.started_at
if (($process.Path -ne $record.executable) -or ($process.StartTime.ToUniversalTime().Ticks -ne $recordedStart.ToUniversalTime().Ticks)) {
    throw 'PID no longer matches the recorded ScopePay process. Nothing was stopped.'
}
Stop-Process -Id $process.Id
Write-Output "Stopped ScopePay PID $($process.Id). No files deleted."
