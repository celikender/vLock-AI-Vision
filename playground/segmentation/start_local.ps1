$ErrorActionPreference = 'Stop'
$worker = Join-Path $PSScriptRoot 'local_worker.py'
$linuxWorker = (wsl -d Ubuntu -- wslpath -a -u $worker).Trim()
wsl -d Ubuntu -- bash -lc ('exec ~/.local/share/vlock-vision/sam-env/bin/python "' + $linuxWorker + '"')