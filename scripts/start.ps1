$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv/Scripts/python.exe'
$port = 8215
if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port 8215 already has a listener. Inspect it; this script will not replace it."
}
$dataPath = Join-Path $projectRoot 'data'
[IO.Directory]::CreateDirectory($dataPath) | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stdoutPath = Join-Path $dataPath "server-$stamp.stdout.log"
$stderrPath = Join-Path $dataPath "server-$stamp.stderr.log"
$allow = @('PATH','SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','TEMP','TMP','USERPROFILE','APPDATA','LOCALAPPDATA','PROGRAMFILES','PROGRAMDATA','HOMEDRIVE','HOMEPATH','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE')
$removedEnv = @{}
try {
    foreach ($entry in [Environment]::GetEnvironmentVariables('Process').GetEnumerator()) {
        if ($allow -notcontains $entry.Key.ToUpperInvariant()) {
            $removedEnv[$entry.Key] = $entry.Value
            [Environment]::SetEnvironmentVariable($entry.Key, $null, 'Process')
        }
    }
    $process = Start-Process -FilePath $pythonExe -ArgumentList @('-m','uvicorn','main:app','--host','127.0.0.1','--port','8215','--workers','1') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
} finally {
    foreach ($entry in $removedEnv.GetEnumerator()) { [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process') }
}
for ($attempt=0; $attempt -lt 40; $attempt++) {
    $listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) { break }
    Start-Sleep -Milliseconds 250
}
if (-not $listener) { throw "ScopePay failed to listen. Inspect $stderrPath; launcher PID is $($process.Id)." }
$worker = Get-Process -Id $listener.OwningProcess
$workerInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($worker.Id)"
if (($worker.Id -ne $process.Id) -and ($workerInfo.ParentProcessId -ne $process.Id)) {
    throw 'Listener does not belong to the process launched here. No process was stopped.'
}
$record = @{ pid=$worker.Id; launcher_pid=$process.Id; port=$port; url='http://127.0.0.1:8215'; started_at=$worker.StartTime.ToUniversalTime().ToString('o'); executable=$worker.Path; stdout=$stdoutPath; stderr=$stderrPath; stop='Run scripts/stop.ps1 (verifies executable path and start time).' }
[IO.File]::WriteAllText((Join-Path $projectRoot 'runtime.json'), ($record | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
$record | ConvertTo-Json
