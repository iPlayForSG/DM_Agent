[CmdletBinding()]
param(
    [switch]$ExitOnReady
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$LogDir = Join-Path $BackendDir "runtime-logs"
$FrontendRuntimeEnvFile = Join-Path $FrontendDir ".env.development.local"
$RuntimeStateFile = Join-Path $LogDir "runtime-state.json"
$BackendOutLog = Join-Path $LogDir "backend.out.log"
$BackendErrLog = Join-Path $LogDir "backend.err.log"
$FrontendOutLog = Join-Path $LogDir "frontend.out.log"
$FrontendErrLog = Join-Path $LogDir "frontend.err.log"
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

function Test-UrlReady {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url
    )

    try {
        $null = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
        return $true
    }
    catch {
        return $false
    }
}

function Test-PortAvailable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BindHost,
        [Parameter(Mandatory = $true)]
        [int]$Port
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
        [Parameter(Mandatory = $true)]
        [string]$BindHost,
        [Parameter(Mandatory = $true)]
        [int]$PreferredPort,
        [int]$Span = 20
    )

    for ($port = $PreferredPort; $port -lt ($PreferredPort + $Span); $port++) {
        if (Test-PortAvailable -BindHost $BindHost -Port $port) {
            return $port
        }
    }

    throw "No usable TCP port was found near $PreferredPort on $BindHost."
}

function Wait-UrlReady {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [Parameter(Mandatory = $false)]
        [System.Diagnostics.Process]$Process,
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

function Get-ExecutableCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Names
    )

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
        return [pscustomobject]@{
            Command       = $env:DM_AGENT_PYTHON
            BaseArguments = @()
            Display       = $env:DM_AGENT_PYTHON
        }
    }

    $preferredPython = "C:\Users\iPlayForSG\.conda\envs\DM_Agent\python.exe"
    if (Test-Path $preferredPython) {
        return [pscustomobject]@{
            Command       = $preferredPython
            BaseArguments = @()
            Display       = $preferredPython
        }
    }

    if ($env:CONDA_PREFIX) {
        $condaPrefixPython = Join-Path $env:CONDA_PREFIX "python.exe"
        if (Test-Path $condaPrefixPython) {
            return [pscustomobject]@{
                Command       = $condaPrefixPython
                BaseArguments = @()
                Display       = $condaPrefixPython
            }
        }
    }

    if ($env:CONDA_EXE -and (Test-Path $env:CONDA_EXE)) {
        return [pscustomobject]@{
            Command       = $env:CONDA_EXE
            BaseArguments = @("run", "-n", "DM_Agent", "python")
            Display       = "$($env:CONDA_EXE) run -n DM_Agent python"
        }
    }

    $condaExecutable = Get-ExecutableCommand -Names @("conda.exe", "conda.bat")
    if ($condaExecutable) {
        return [pscustomobject]@{
            Command       = $condaExecutable
            BaseArguments = @("run", "-n", "DM_Agent", "python")
            Display       = "$condaExecutable run -n DM_Agent python"
        }
    }

    $pythonExecutable = Get-ExecutableCommand -Names @("python.exe", "python")
    if ($pythonExecutable) {
        return [pscustomobject]@{
            Command       = $pythonExecutable
            BaseArguments = @()
            Display       = $pythonExecutable
        }
    }

    throw "Could not find a usable Python runtime. Set DM_AGENT_PYTHON or install the DM_Agent environment first."
}

function Invoke-Runner {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Runner,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $Runner.Command @($Runner.BaseArguments + $Arguments)
    return $LASTEXITCODE
}

function Test-ProcessAlive {
    param(
        [Parameter(Mandatory = $false)]
        [System.Diagnostics.Process]$Process
    )

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

function Stop-StartedProcess {
    param(
        [Parameter(Mandatory = $false)]
        [System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)]
        [bool]$WasStartedByScript
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
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

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
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [hashtable]$Payload
    )

    $Payload | ConvertTo-Json | Set-Content -Path $Path -Encoding utf8
}

function Write-FrontendRuntimeEnv {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$BackendUrl,
        [Parameter(Mandatory = $true)]
        [string]$FrontendHostValue,
        [Parameter(Mandatory = $true)]
        [int]$FrontendPortValue
    )

    @(
        "VITE_BACKEND_URL=$BackendUrl"
        "VITE_DEV_HOST=$FrontendHostValue"
        "VITE_DEV_PORT=$FrontendPortValue"
    ) | Set-Content -Path $Path -Encoding ascii
}

function Set-BackendLogPaths {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $script:BackendOutLog = Join-Path $LogDir "backend-$Port.out.log"
    $script:BackendErrLog = Join-Path $LogDir "backend-$Port.err.log"
}

function Set-FrontendLogPaths {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $script:FrontendOutLog = Join-Path $LogDir "frontend-$Port.out.log"
    $script:FrontendErrLog = Join-Path $LogDir "frontend-$Port.err.log"
}

function Start-BackendProcess {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Runner,
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    Set-Content -Path $BackendOutLog -Value ""
    Set-Content -Path $BackendErrLog -Value ""

    return Start-Process `
        -FilePath $Runner.Command `
        -ArgumentList @($Runner.BaseArguments + @("-m", "uvicorn", "main:app", "--host", $BackendHost, "--port", $Port.ToString())) `
        -WorkingDirectory $BackendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $BackendOutLog `
        -RedirectStandardError $BackendErrLog `
        -PassThru
}

function Start-FrontendProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NpmCommand,
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    Set-Content -Path $FrontendOutLog -Value ""
    Set-Content -Path $FrontendErrLog -Value ""

    return Start-Process `
        -FilePath $NpmCommand `
        -ArgumentList @("run", "dev", "--", "--host", $FrontendHost, "--port", $Port.ToString()) `
        -WorkingDirectory $FrontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $FrontendOutLog `
        -RedirectStandardError $FrontendErrLog `
        -PassThru
}

function Open-FrontendInBrowser {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url
    )

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

    $nativePreferenceVar = Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $previousNativeErrorPreference = $null
    if ($null -ne $nativePreferenceVar) {
        $previousNativeErrorPreference = [bool]$nativePreferenceVar.Value
        $PSNativeCommandUseErrorActionPreference = $false
    }
    try {
        Invoke-Runner -Runner $pythonRunner -Arguments @(
            "-c",
            "import fastapi, uvicorn, langgraph, langchain_openai"
        ) *> $null
    }
    finally {
        if ($null -ne $nativePreferenceVar) {
            $PSNativeCommandUseErrorActionPreference = $previousNativeErrorPreference
        }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Backend Python dependencies are missing. Run: $($pythonRunner.Display) -m pip install -r backend/requirements.txt"
    }

    if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
        Write-Host "Installing frontend dependencies..."
        Push-Location $FrontendDir
        try {
            & $npmCommand install
        }
        finally {
            Pop-Location
        }
    }

    $runtimeState = Read-RuntimeState -Path $RuntimeStateFile

    $backendPort = $null
    $backendUrl = $null
    $backendHealthUrl = $null

    if ($null -ne $runtimeState -and $runtimeState.backendHealthUrl -and (Test-UrlReady -Url $runtimeState.backendHealthUrl)) {
        $backendPort = [int]$runtimeState.backendPort
        $backendUrl = [string]$runtimeState.backendUrl
        $backendHealthUrl = [string]$runtimeState.backendHealthUrl
        if ($runtimeState.backendOutLog -and $runtimeState.backendErrLog) {
            $BackendOutLog = [string]$runtimeState.backendOutLog
            $BackendErrLog = [string]$runtimeState.backendErrLog
        }
        else {
            Set-BackendLogPaths -Port $backendPort
        }
        Write-Host "Backend already running at $backendUrl"
    }
    else {
        $defaultBackendUrl = "http://${BackendHost}:$DefaultBackendPort"
        $defaultBackendHealthUrl = "$defaultBackendUrl/api/v1/health"
        if (Test-UrlReady -Url $defaultBackendHealthUrl) {
            $backendPort = $DefaultBackendPort
            $backendUrl = $defaultBackendUrl
            $backendHealthUrl = $defaultBackendHealthUrl
            Set-BackendLogPaths -Port $backendPort
            Write-Host "Backend already running at $backendUrl"
        }
        else {
            $backendPort = Get-AvailablePort -BindHost $BackendHost -PreferredPort $DefaultBackendPort -Span $PortSearchSpan
            $backendUrl = "http://${BackendHost}:$backendPort"
            $backendHealthUrl = "$backendUrl/api/v1/health"
            Set-BackendLogPaths -Port $backendPort
            Write-Host "Starting backend at $backendUrl..."
            $backendProcess = Start-BackendProcess -Runner $pythonRunner -Port $backendPort
            $startedBackend = $true
            Wait-UrlReady -Name "Backend" -Url $backendHealthUrl -Process $backendProcess -Attempts 120
        }
    }

    $frontendPort = $null
    $frontendUrl = $null
    $reusedFrontend = $false

    if (
        $null -ne $runtimeState -and
        $runtimeState.frontendUrl -and
        $runtimeState.backendUrl -eq $backendUrl -and
        (Test-UrlReady -Url $runtimeState.frontendUrl)
    ) {
        $frontendPort = [int]$runtimeState.frontendPort
        $frontendUrl = [string]$runtimeState.frontendUrl
        if ($runtimeState.frontendOutLog -and $runtimeState.frontendErrLog) {
            $FrontendOutLog = [string]$runtimeState.frontendOutLog
            $FrontendErrLog = [string]$runtimeState.frontendErrLog
        }
        else {
            Set-FrontendLogPaths -Port $frontendPort
        }
        $reusedFrontend = $true
        Write-Host "Frontend already running at $frontendUrl"
    }
    else {
        $frontendPort = Get-AvailablePort -BindHost $FrontendHost -PreferredPort $DefaultFrontendPort -Span $PortSearchSpan
        $frontendUrl = "http://${FrontendHost}:$frontendPort"
        Set-FrontendLogPaths -Port $frontendPort
        Write-FrontendRuntimeEnv `
            -Path $FrontendRuntimeEnvFile `
            -BackendUrl $backendUrl `
            -FrontendHostValue $FrontendHost `
            -FrontendPortValue $frontendPort
        Write-Host "Starting frontend at $frontendUrl..."
        $frontendProcess = Start-FrontendProcess -NpmCommand $npmCommand -Port $frontendPort
        $startedFrontend = $true
        Wait-UrlReady -Name "Frontend" -Url $frontendUrl -Process $frontendProcess -Attempts 120
    }

    Write-RuntimeState -Path $RuntimeStateFile -Payload @{
        backendHost      = $BackendHost
        backendPort      = $backendPort
        backendUrl       = $backendUrl
        backendHealthUrl = $backendHealthUrl
        backendOutLog    = $BackendOutLog
        backendErrLog    = $BackendErrLog
        frontendHost     = $FrontendHost
        frontendPort     = $frontendPort
        frontendUrl      = $frontendUrl
        frontendOutLog   = $FrontendOutLog
        frontendErrLog   = $FrontendErrLog
        updatedAt        = (Get-Date).ToString("s")
    }

    Write-Host ""
    Write-Host "DM_Agent is ready."
    Write-Host "Frontend: $frontendUrl"
    Write-Host "Backend:  $backendUrl"
    Write-Host "Logs:"
    Write-Host "  $BackendOutLog"
    Write-Host "  $BackendErrLog"
    Write-Host "  $FrontendOutLog"
    Write-Host "  $FrontendErrLog"

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
    if (Test-Path $BackendErrLog) {
        Write-Host "Backend log:  $BackendErrLog"
    }
    if (Test-Path $FrontendErrLog) {
        Write-Host "Frontend log: $FrontendErrLog"
    }
    exit 1
}
finally {
    if (-not $startupSucceeded) {
        Stop-StartedProcess -Process $frontendProcess -WasStartedByScript $startedFrontend
        Stop-StartedProcess -Process $backendProcess -WasStartedByScript $startedBackend
    }
}
