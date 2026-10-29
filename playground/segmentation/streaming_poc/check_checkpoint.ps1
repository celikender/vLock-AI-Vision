$ErrorActionPreference = 'Stop'
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
wsl -d Ubuntu --cd $workspaceRoot -- playground/outputs/streaming-env-linux/bin/python playground/segmentation/streaming_poc/compatibility.py --local-only
exit $LASTEXITCODE
