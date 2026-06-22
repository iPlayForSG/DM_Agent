@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%POWERSHELL_EXE%" (
  echo PowerShell was not found.
  pause
  exit /b 1
)

set "DM_AGENT_START_ROOT=%SCRIPT_DIR%"
set "TMP_PS1=%TEMP%\DM_Agent_start_%RANDOM%_%RANDOM%.ps1"

"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command "$raw = Get-Content -LiteralPath '%~f0' -Raw; $marker = '### POWERSHELL PAYLOAD ###'; $index = $raw.LastIndexOf($marker); if ($index -lt 0) { exit 2 }; $script = $raw.Substring($index + $marker.Length); Set-Content -LiteralPath '%TMP_PS1%' -Value $script -Encoding UTF8"
if errorlevel 1 (
  echo Failed to extract startup payload.
  pause
  exit /b 1
)

"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%TMP_PS1%" %*
set "EXIT_CODE=%ERRORLEVEL%"
del "%TMP_PS1%" >nul 2>nul

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Startup failed. Press any key to close...
  pause >nul
)

exit /b %EXIT_CODE%

### POWERSHELL PAYLOAD ###
[CmdletBinding()]
param(
    [switch]$ExitOnReady
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RootDir = $env:DM_AGENT_START_ROOT
if (-not $RootDir) {
    $RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$RootDir = [System.IO.Path]::GetFullPath($RootDir)
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$LogDir = Join-Path $BackendDir "runtime-logs"
$FrontendRuntimeEnvFile = Join-Path $FrontendDir ".env.development.local"
$RuntimeStateFile = Join-Path $LogDir "runtime-state.json"
$BackendHost = "127.0.0.1"
$FrontendHost = "127.0.0.1"
$DefaultBackendPort = 23333
$DefaultFrontendPort = 5173
$PortSearchSpan = 30

$backendProcess = $null
$frontendProcess = $null
$startedBackend = $false
$startedFrontend = $false
$startupSucceeded = $false
$backendOutLog = $null
$backendErrLog = $null
$frontendOutLog = $null
$frontendErrLog = $null

function Repair-PathEnvironment {
    $pathValue = [System.Environment]::GetEnvironmentVariable("Path", "Process")
    if (-not $pathValue) {
        $pathValue = [System.Environment]::GetEnvironmentVariable("PATH", "Process")
    }
    if (-not $pathValue) {
        return
    }

    [System.Environment]::SetEnvironmentVariable("PATH", $null, "Process")
    [System.Environment]::SetEnvironmentVariable("Path", $null, "Process")
    [System.Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")
}

Repair-PathEnvironment

function Test-UrlReady {
    param([Parameter(Mandatory = $true)][string]$Url)
    try {
        $null = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
        return $true
    }
    catch {
        return $false
    }
}

function Test-BackendCompatible {
    param([Parameter(Mandatory = $true)][string]$HealthUrl)
    try {
        $payload = Invoke-RestMethod -UseBasicParsing -Uri $HealthUrl -TimeoutSec 3
        return [bool]($payload.api_features -and $payload.api_features.batch_delete)
    }
    catch {
        return $false
    }
}

function Test-PortAvailable {
    param(
        [Parameter(Mandatory = $true)][string]$BindHost,
        [Parameter(Mandatory = $true)][int]$Port
    )

    $listener = $null
    try {
        $address = [System.Net.IPAddress]::Parse($BindHost)
        $listener = [System.Net.Sockets.TcpListener]::new($address, $Port)
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $listener) {
            $listener.Stop()
        }
    }
}

function Get-AvailablePort {
    param(
        [Parameter(Mandatory = $true)][string]$BindHost,
        [Parameter(Mandatory = $true)][int]$PreferredPort,
        [int]$Span = 20
    )

    for ($port = $PreferredPort; $port -lt ($PreferredPort + $Span); $port++) {
        if (Test-PortAvailable -BindHost $BindHost -Port $port) {
            return $port
        }
    }
    throw "No usable TCP port was found near $PreferredPort on $BindHost."
}

function Get-ExecutableCommand {
    param([Parameter(Mandatory = $true)][string[]]$Names)
    foreach ($name in $Names) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $command -and $command.Source) {
            return $command.Source
        }
    }
    return $null
}

function Resolve-PythonRunner {
    if ($env:DM_AGENT_PYTHON) {
        if (-not (Test-Path $env:DM_AGENT_PYTHON)) {
            throw "DM_AGENT_PYTHON points to a missing file: $($env:DM_AGENT_PYTHON)"
        }
        return [pscustomobject]@{ Command = $env:DM_AGENT_PYTHON; Arguments = @(); Display = $env:DM_AGENT_PYTHON }
    }

    $preferredPython = "C:\Users\iPlayForSG\.conda\envs\DM_Agent\python.exe"
    if (Test-Path $preferredPython) {
        return [pscustomobject]@{ Command = $preferredPython; Arguments = @(); Display = $preferredPython }
    }

    if ($env:CONDA_PREFIX) {
        $condaPrefixPython = Join-Path $env:CONDA_PREFIX "python.exe"
        if (Test-Path $condaPrefixPython) {
            return [pscustomobject]@{ Command = $condaPrefixPython; Arguments = @(); Display = $condaPrefixPython }
        }
    }

    if ($env:CONDA_EXE -and (Test-Path $env:CONDA_EXE)) {
        return [pscustomobject]@{
            Command = $env:CONDA_EXE
            Arguments = @("run", "-n", "DM_Agent", "python")
            Display = "$($env:CONDA_EXE) run -n DM_Agent python"
        }
    }

    $condaExecutable = Get-ExecutableCommand -Names @("conda.exe", "conda.bat")
    if ($condaExecutable) {
        return [pscustomobject]@{
            Command = $condaExecutable
            Arguments = @("run", "-n", "DM_Agent", "python")
            Display = "$condaExecutable run -n DM_Agent python"
        }
    }

    $pythonExecutable = Get-ExecutableCommand -Names @("python.exe", "python")
    if ($pythonExecutable) {
        return [pscustomobject]@{ Command = $pythonExecutable; Arguments = @(); Display = $pythonExecutable }
    }

    throw "Could not find a usable Python runtime. Set DM_AGENT_PYTHON or install the DM_Agent environment first."
}

function Invoke-Runner {
    param(
        [Parameter(Mandatory = $true)][pscustomobject]$Runner,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $Runner.Command @($Runner.Arguments + $Arguments)
    return $LASTEXITCODE
}

function Test-ProcessAlive {
    param([Parameter(Mandatory = $false)][System.Diagnostics.Process]$Process)
    if ($null -eq $Process) {
        return $false
    }
    try {
        $null = Get-Process -Id $Process.Id -ErrorAction Stop
        return $true
    }
    catch {
        return $false
    }
}

function Wait-UrlReady {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $false)][System.Diagnostics.Process]$Process,
        [int]$Attempts = 90
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        if (Test-UrlReady -Url $Url) {
            return
        }
        if ($null -ne $Process -and -not (Test-ProcessAlive -Process $Process)) {
            throw "$Name process exited before becoming ready."
        }
        Start-Sleep -Seconds 1
    }
    throw "$Name did not become ready in time."
}

function Stop-StartedProcess {
    param(
        [Parameter(Mandatory = $false)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][bool]$WasStartedByScript
    )

    if (-not $WasStartedByScript) {
        return
    }
    if (-not (Test-ProcessAlive -Process $Process)) {
        return
    }
    Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
}

function Read-RuntimeState {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path $Path)) {
        return $null
    }
    try {
        return Get-Content -Raw -Path $Path | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Write-RuntimeState {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][hashtable]$Payload
    )

    $Payload | ConvertTo-Json | Set-Content -Path $Path -Encoding utf8
}

function Write-FrontendRuntimeEnv {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$BackendUrl,
        [Parameter(Mandatory = $true)][string]$FrontendHostValue,
        [Parameter(Mandatory = $true)][int]$FrontendPortValue
    )

    @(
        "VITE_BACKEND_URL=$BackendUrl"
        "VITE_DEV_HOST=$FrontendHostValue"
        "VITE_DEV_PORT=$FrontendPortValue"
    ) | Set-Content -Path $Path -Encoding ascii
}

function Test-PythonDependencies {
    param([Parameter(Mandatory = $true)][pscustomobject]$Runner)

    $nativePreferenceVar = Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $previousNativeErrorPreference = $null
    if ($null -ne $nativePreferenceVar) {
        $previousNativeErrorPreference = [bool]$nativePreferenceVar.Value
        $PSNativeCommandUseErrorActionPreference = $false
    }
    try {
        Invoke-Runner -Runner $Runner -Arguments @("-c", "import fastapi, uvicorn, langgraph, langchain_openai") *> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        if ($null -ne $nativePreferenceVar) {
            $PSNativeCommandUseErrorActionPreference = $previousNativeErrorPreference
        }
    }
}

function Start-BackendProcess {
    param(
        [Parameter(Mandatory = $true)][pscustomobject]$Runner,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$OutLog,
        [Parameter(Mandatory = $true)][string]$ErrLog
    )

    Set-Content -Path $OutLog -Value ""
    Set-Content -Path $ErrLog -Value ""

    return Start-Process `
        -FilePath $Runner.Command `
        -ArgumentList @($Runner.Arguments + @("-m", "uvicorn", "main:app", "--host", $BackendHost, "--port", $Port.ToString(), "--reload")) `
        -WorkingDirectory $BackendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog `
        -PassThru
}

function Start-FrontendProcess {
    param(
        [Parameter(Mandatory = $true)][string]$NpmCommand,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$OutLog,
        [Parameter(Mandatory = $true)][string]$ErrLog
    )

    Set-Content -Path $OutLog -Value ""
    Set-Content -Path $ErrLog -Value ""

    return Start-Process `
        -FilePath $NpmCommand `
        -ArgumentList @("run", "dev", "--", "--host", $FrontendHost, "--port", $Port.ToString()) `
        -WorkingDirectory $FrontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog `
        -PassThru
}

function Open-FrontendInBrowser {
    param([Parameter(Mandatory = $true)][string]$Url)
    try {
        Start-Process $Url | Out-Null
    }
    catch {
        Write-Host "Browser was not opened automatically. Open this URL manually: $Url"
    }
}

try {
    if (-not (Test-Path (Join-Path $BackendDir ".env"))) {
        throw "Missing backend/.env. Copy backend/.env.example to backend/.env and fill in your API settings first."
    }

    $npmCommand = Get-ExecutableCommand -Names @("npm.cmd", "npm")
    if (-not $npmCommand) {
        throw "npm is required but was not found in PATH."
    }

    $pythonRunner = Resolve-PythonRunner
    $null = New-Item -ItemType Directory -Force -Path $LogDir

    if (-not (Test-PythonDependencies -Runner $pythonRunner)) {
        throw "Backend Python dependencies are missing. Run: $($pythonRunner.Display) -m pip install -r backend/requirements.txt"
    }

    if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
        Write-Host "Installing frontend dependencies..."
        Push-Location $FrontendDir
        try {
            & $npmCommand install
            if ($LASTEXITCODE -ne 0) {
                throw "npm install failed."
            }
        }
        finally {
            Pop-Location
        }
    }

    $runtimeState = Read-RuntimeState -Path $RuntimeStateFile

    $backendPort = $null
    $backendUrl = $null
    $backendHealthUrl = $null
    $backendOutLog = $null
    $backendErrLog = $null

    if (
        $null -ne $runtimeState -and
        $runtimeState.backendHealthUrl -and
        (Test-UrlReady -Url $runtimeState.backendHealthUrl) -and
        (Test-BackendCompatible -HealthUrl $runtimeState.backendHealthUrl)
    ) {
        $backendPort = [int]$runtimeState.backendPort
        $backendUrl = [string]$runtimeState.backendUrl
        $backendHealthUrl = [string]$runtimeState.backendHealthUrl
        if ($runtimeState.backendOutLog) {
            $backendOutLog = [string]$runtimeState.backendOutLog
        }
        else {
            $backendOutLog = Join-Path $LogDir "backend-$backendPort.out.log"
        }
        if ($runtimeState.backendErrLog) {
            $backendErrLog = [string]$runtimeState.backendErrLog
        }
        else {
            $backendErrLog = Join-Path $LogDir "backend-$backendPort.err.log"
        }
        Write-Host "Backend already running at $backendUrl"
    }
    elseif ($null -ne $runtimeState -and $runtimeState.backendHealthUrl -and (Test-UrlReady -Url $runtimeState.backendHealthUrl)) {
        Write-Host "Ignoring older backend at $($runtimeState.backendUrl); it does not expose the current API."
    }

    if (-not $backendUrl) {
        $defaultBackendUrl = "http://${BackendHost}:$DefaultBackendPort"
        $defaultBackendHealthUrl = "$defaultBackendUrl/api/v1/health"
        if ((Test-UrlReady -Url $defaultBackendHealthUrl) -and (Test-BackendCompatible -HealthUrl $defaultBackendHealthUrl)) {
            $backendPort = $DefaultBackendPort
            $backendUrl = $defaultBackendUrl
            $backendHealthUrl = $defaultBackendHealthUrl
            $backendOutLog = Join-Path $LogDir "backend-$backendPort.out.log"
            $backendErrLog = Join-Path $LogDir "backend-$backendPort.err.log"
            Write-Host "Backend already running at $backendUrl"
        }
        elseif (Test-UrlReady -Url $defaultBackendHealthUrl) {
            Write-Host "Ignoring older backend at $defaultBackendUrl; it does not expose the current API."
        }
    }

    if (-not $backendUrl) {
        $backendPort = Get-AvailablePort -BindHost $BackendHost -PreferredPort $DefaultBackendPort -Span $PortSearchSpan
        $backendUrl = "http://${BackendHost}:$backendPort"
        $backendHealthUrl = "$backendUrl/api/v1/health"
        $backendOutLog = Join-Path $LogDir "backend-$backendPort.out.log"
        $backendErrLog = Join-Path $LogDir "backend-$backendPort.err.log"
        Write-Host "Starting backend at $backendUrl..."
        $backendProcess = Start-BackendProcess -Runner $pythonRunner -Port $backendPort -OutLog $backendOutLog -ErrLog $backendErrLog
        $startedBackend = $true
        Wait-UrlReady -Name "Backend" -Url $backendHealthUrl -Process $backendProcess -Attempts 120
    }

    $frontendPort = $null
    $frontendUrl = $null
    $frontendOutLog = $null
    $frontendErrLog = $null
    $reusedFrontend = $false

    if (
        $null -ne $runtimeState -and
        $runtimeState.frontendUrl -and
        $runtimeState.backendUrl -eq $backendUrl -and
        (Test-UrlReady -Url $runtimeState.frontendUrl)
    ) {
        $frontendPort = [int]$runtimeState.frontendPort
        $frontendUrl = [string]$runtimeState.frontendUrl
        if ($runtimeState.frontendOutLog) {
            $frontendOutLog = [string]$runtimeState.frontendOutLog
        }
        else {
            $frontendOutLog = Join-Path $LogDir "frontend-$frontendPort.out.log"
        }
        if ($runtimeState.frontendErrLog) {
            $frontendErrLog = [string]$runtimeState.frontendErrLog
        }
        else {
            $frontendErrLog = Join-Path $LogDir "frontend-$frontendPort.err.log"
        }
        $reusedFrontend = $true
        Write-Host "Frontend already running at $frontendUrl"
    }
    else {
        $frontendPort = Get-AvailablePort -BindHost $FrontendHost -PreferredPort $DefaultFrontendPort -Span $PortSearchSpan
        $frontendUrl = "http://${FrontendHost}:$frontendPort"
        $frontendOutLog = Join-Path $LogDir "frontend-$frontendPort.out.log"
        $frontendErrLog = Join-Path $LogDir "frontend-$frontendPort.err.log"
        Write-FrontendRuntimeEnv -Path $FrontendRuntimeEnvFile -BackendUrl $backendUrl -FrontendHostValue $FrontendHost -FrontendPortValue $frontendPort
        Write-Host "Starting frontend at $frontendUrl..."
        $frontendProcess = Start-FrontendProcess -NpmCommand $npmCommand -Port $frontendPort -OutLog $frontendOutLog -ErrLog $frontendErrLog
        $startedFrontend = $true
        Wait-UrlReady -Name "Frontend" -Url $frontendUrl -Process $frontendProcess -Attempts 120
    }

    Write-RuntimeState -Path $RuntimeStateFile -Payload @{
        backendHost = $BackendHost
        backendPort = $backendPort
        backendUrl = $backendUrl
        backendHealthUrl = $backendHealthUrl
        backendOutLog = $backendOutLog
        backendErrLog = $backendErrLog
        frontendHost = $FrontendHost
        frontendPort = $frontendPort
        frontendUrl = $frontendUrl
        frontendOutLog = $frontendOutLog
        frontendErrLog = $frontendErrLog
        updatedAt = (Get-Date).ToString("s")
    }

    Write-Host ""
    Write-Host "DM_Agent is ready."
    Write-Host "Frontend: $frontendUrl"
    Write-Host "Backend:  $backendUrl"
    Write-Host "Logs:"
    Write-Host "  $backendOutLog"
    Write-Host "  $backendErrLog"
    Write-Host "  $frontendOutLog"
    Write-Host "  $frontendErrLog"

    $startupSucceeded = $true

    if (-not $ExitOnReady) {
        if ($reusedFrontend) {
            Write-Host "Opening the existing frontend in your default browser..."
        }
        else {
            Write-Host "Opening DM_Agent in your default browser..."
        }
        Open-FrontendInBrowser -Url $frontendUrl
    }
}
catch {
    Write-Host ""
    Write-Host "DM_Agent failed to start."
    Write-Host $_.Exception.Message
    if ($backendErrLog) {
        Write-Host "Backend log:  $backendErrLog"
    }
    if ($frontendErrLog) {
        Write-Host "Frontend log: $frontendErrLog"
    }
    exit 1
}
finally {
    if (-not $startupSucceeded) {
        Stop-StartedProcess -Process $frontendProcess -WasStartedByScript $startedFrontend
        Stop-StartedProcess -Process $backendProcess -WasStartedByScript $startedBackend
    }
}
