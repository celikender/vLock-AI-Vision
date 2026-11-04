$ErrorActionPreference = 'Stop'
$taskIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$taskPrincipal = New-Object Security.Principal.WindowsPrincipal($taskIdentity)
if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $taskArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"'
    $taskProcess = Start-Process powershell.exe -Verb RunAs -ArgumentList $taskArgs -Wait -PassThru
    exit $taskProcess.ExitCode
}
try {
    $taskInstall = Join-Path $env:ProgramData 'BambuP1SConnector'
    $taskServiceName = 'BambuP1SConnector'
    if (Get-Service -Name $taskServiceName -ErrorAction SilentlyContinue) {
        Write-Host 'The connector service is already installed. Use Configure.cmd or Restart.cmd; no reinstall is needed.'
        Read-Host 'Press Enter to close'
        exit 0
    }
    $taskPython = $null
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        $taskPython = & py.exe -3 -c "import sys; assert sys.version_info >= (3,11); print(sys.executable)"
        if ($LASTEXITCODE -ne 0) { $taskPython = $null }
    }
    if (-not $taskPython -and (Get-Command python.exe -ErrorAction SilentlyContinue)) {
        $taskPython = & python.exe -c "import sys; assert sys.version_info >= (3,11); print(sys.executable)"
        if ($LASTEXITCODE -ne 0) { $taskPython = $null }
    }
    if (-not $taskPython) {
        Start-Process 'https://www.python.org/downloads/windows/'
        throw 'Install Python 3.11 or newer (with the launcher and Tcl/Tk), then double-click Setup.cmd again.'
    }
    if ((Get-CimInstance Win32_OperatingSystem).OSArchitecture -notmatch '64') { throw 'This installer requires 64-bit Windows.' }
    $taskExisting = Get-Service -Name $taskServiceName -ErrorAction SilentlyContinue
    if ($taskExisting -and $taskExisting.Status -ne 'Stopped') {
        Stop-Service -Name $taskServiceName -Force
        $taskExisting.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(25))
    }
    New-Item -ItemType Directory -Path $taskInstall -Force | Out-Null
    foreach ($taskFile in @('p1s_service.py','configure.py','requirements.txt','Manage.ps1')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $taskFile) -Destination (Join-Path $taskInstall $taskFile) -Force
    }
    if (-not (Test-Path -LiteralPath (Join-Path $taskInstall '.env'))) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot '.env.example') -Destination (Join-Path $taskInstall '.env')
    }
    $taskVenv = Join-Path $taskInstall '.venv'
    & $taskPython -m venv $taskVenv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
    $taskVenvPython = Join-Path $taskVenv 'Scripts\python.exe'
    & $taskVenvPython -m pip install --disable-pip-version-check -r (Join-Path $taskInstall 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the MQTT dependency. Check internet access.' }
    & $taskVenvPython (Join-Path $taskInstall 'configure.py')
    if ($LASTEXITCODE -ne 0) { throw 'Configuration was cancelled. Existing credentials were not replaced.' }
    # Credential file: administrators and the Windows service account only.
    & icacls.exe (Join-Path $taskInstall '.env') /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not set local credential file permissions.' }
    $taskWrapper = Join-Path $taskInstall 'BambuP1SConnector.exe'
    $taskDownload = Join-Path $taskInstall 'WinSW-download.exe'
    $taskExpectedHash = '05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da'
    if (-not (Test-Path $taskWrapper) -or (Get-FileHash -Algorithm SHA256 $taskWrapper).Hash.ToLower() -ne $taskExpectedHash) {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe' -OutFile $taskDownload
        if ((Get-FileHash -Algorithm SHA256 $taskDownload).Hash.ToLower() -ne $taskExpectedHash) {
            Remove-Item $taskDownload -Force
            throw 'Service wrapper checksum did not match. Installation stopped.'
        }
        Move-Item $taskDownload $taskWrapper -Force
    }
    $taskEscape = { param($text) [Security.SecurityElement]::Escape($text) }
    $taskExeXml = & $taskEscape $taskVenvPython
    $taskScriptXml = & $taskEscape (Join-Path $taskInstall 'p1s_service.py')
    $taskWorkXml = & $taskEscape $taskInstall
    $taskXml = @"
<service>
  <id>BambuP1SConnector</id>
  <name>Bambu P1S Connector</name>
  <description>Local real-printer MQTT and camera connector for Ignition.</description>
  <executable>$taskExeXml</executable>
  <arguments>"$taskScriptXml"</arguments>
  <workingdirectory>$taskWorkXml</workingdirectory>
  <startmode>Automatic</startmode>
  <delayedAutoStart>true</delayedAutoStart>
  <stoptimeout>15 sec</stoptimeout>
  <onfailure action="restart" delay="5 sec"/>
  <log mode="roll"/>
</service>
"@
    [IO.File]::WriteAllText((Join-Path $taskInstall 'BambuP1SConnector.xml'),$taskXml,(New-Object Text.UTF8Encoding($false)))
    if (-not $taskExisting) {
        & $taskWrapper install
        if ($LASTEXITCODE -ne 0) { throw 'Could not register the Windows service.' }
    }
    Start-Service -Name $taskServiceName
    Start-Sleep -Seconds 2
    $taskHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8876/health' -TimeoutSec 10
    Write-Host ('Connector installed and running. Configuration present: ' + $taskHealth.configured) -ForegroundColor Green
    Write-Host 'Import printer-farm-perspective.zip into Ignition, then open its Perspective session.'
    Write-Host 'It will start automatically with Windows. No daily terminal commands are required.'
    Read-Host 'Press Enter to close'
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}
