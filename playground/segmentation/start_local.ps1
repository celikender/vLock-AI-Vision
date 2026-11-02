$ErrorActionPreference = 'Stop'
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
