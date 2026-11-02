$ErrorActionPreference = 'Stop'
$probe = [System.Net.Sockets.TcpClient]::new()
$portOpen = $false
try {
    $connection = $probe.ConnectAsync('127.0.0.1', 5052)
    $portOpen = $connection.Wait(1000) -and $probe.Connected
} catch {
    $portOpen = $false
} finally {
    $probe.Dispose()
}
if ($portOpen) {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:5052/health' -TimeoutSec 5
        if ($health.video_window_frames -eq 4 -and $null -ne $health.model_loads -and
            $health.ready -is [bool] -and $health.cuda -is [bool]) {
            Write-Host 'Local SAM worker is already running on http://127.0.0.1:5052. Reusing it.'
            return
        }
    } catch {
        # An occupied port is never permission to stop an unknown process.
    }
    throw 'Port 5052 is occupied but the SAM worker could not be identified. No process was stopped.'
}
$worker = Join-Path $PSScriptRoot 'local_worker.py'
$linuxWorker = & wsl.exe -d Ubuntu --exec wslpath -a -u $worker
if ($LASTEXITCODE -ne 0 -or -not $linuxWorker) {
    throw 'Cannot resolve the worker path in Ubuntu.'
}
$linuxHome = & wsl.exe -d Ubuntu --exec printenv HOME
if ($LASTEXITCODE -ne 0 -or -not $linuxHome) {
    throw 'Cannot resolve the Ubuntu home directory.'
}
$linuxPython = $linuxHome.TrimEnd('/') + '/.local/share/vlock-vision/sam-env/bin/python'
# Pass separate arguments directly; a shell command string loses path quoting.
& wsl.exe -d Ubuntu --exec $linuxPython $linuxWorker.Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Local SAM worker exited with code $LASTEXITCODE."
}
