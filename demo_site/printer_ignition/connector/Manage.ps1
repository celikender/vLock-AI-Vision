param([ValidateSet('Start','Restart','Configure','Uninstall')][string]$Action='Restart')
$ErrorActionPreference='Stop'
$taskPrincipal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $taskArgs='-NoProfile -ExecutionPolicy Bypass -File "'+$PSCommandPath+'" -Action '+$Action
    $taskProcess=Start-Process powershell.exe -Verb RunAs -ArgumentList $taskArgs -Wait -PassThru
    exit $taskProcess.ExitCode
}
try {
    $taskFolder=Join-Path $env:ProgramData 'BambuP1SConnector'
    if ($Action -eq 'Configure') {
        & (Join-Path $taskFolder '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'configure.py') --config-dir $taskFolder
        if ($LASTEXITCODE -ne 0) { exit 1 }
        Restart-Service 'BambuP1SConnector'
    } elseif ($Action -eq 'Uninstall') {
        Stop-Service 'BambuP1SConnector' -ErrorAction SilentlyContinue
        & (Join-Path $taskFolder 'BambuP1SConnector.exe') uninstall
        if ($LASTEXITCODE -ne 0) { throw 'Could not unregister the service.' }
        Write-Host 'Service removed. Configuration and logs are retained in ProgramData.'
    } elseif ($Action -eq 'Start') {
        Start-Service 'BambuP1SConnector'
    } else { Restart-Service 'BambuP1SConnector' }
} catch { Write-Host $_.Exception.Message -ForegroundColor Red;Read-Host 'Press Enter';exit 1 }
