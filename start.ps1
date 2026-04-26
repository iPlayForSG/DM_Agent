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
$BackendOutLog = Join-Path $LogDir "backend.out.log"
$BackendErrLog = Join-Path $LogDir "backend.err.log"
$FrontendOutLog = Join-Path $LogDir "frontend.out.log"
$FrontendErrLog = Join-Path $LogDir "frontend.err.log"
$BackendUrl = "http://127.0.0.1:23333"
$BackendHealthUrl = "$BackendUrl/api/v1/health"
$FrontendUrl = "http://127.0.0.1:5173"

$backendProcess = $null
$frontendProcess = $null
$startedBackend = $false
$startedFrontend = $false

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
            throw "$Name process exited before becoming ready: $Url"
        }
        Start-Sleep -Seconds 1
    }

    throw "$Name did not become ready: $Url"
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
            Command      = $env:DM_AGENT_PYTHON
            BaseArguments = @()
            Display      = $env:DM_AGENT_PYTHON
        }
    }

    $preferredPython = "C:\Users\iPlayForSG\.conda\envs\DM_Agent\python.exe"
    if (Test-Path $preferredPython) {
        return [pscustomobject]@{
            Command      = $preferredPython
            BaseArguments = @()
            Display      = $preferredPython
        }
    }

    if ($env:CONDA_PREFIX) {
        $condaPrefixPython = Join-Path $env:CONDA_PREFIX "python.exe"
        if (Test-Path $condaPrefixPython) {
            return [pscustomobject]@{
                Command      = $condaPrefixPython
                BaseArguments = @()
                Display      = $condaPrefixPython
            }
        }
    }

    if ($env:CONDA_EXE -and (Test-Path $env:CONDA_EXE)) {
        return [pscustomobject]@{
            Command      = $env:CONDA_EXE
            BaseArguments = @("run", "-n", "DM_Agent", "python")
            Display      = "$($env:CONDA_EXE) run -n DM_Agent python"
        }
    }

    $condaExecutable = Get-ExecutableCommand -Names @("conda.exe", "conda.bat")
    if ($condaExecutable) {
        return [pscustomobject]@{
            Command      = $condaExecutable
            BaseArguments = @("run", "-n", "DM_Agent", "python")
            Display      = "$condaExecutable run -n DM_Agent python"
        }
    }

    $pythonExecutable = Get-ExecutableCommand -Names @("python.exe", "python")
    if ($pythonExecutable) {
        return [pscustomobject]@{
            Command      = $pythonExecutable
            BaseArguments = @()
            Display      = $pythonExecutable
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

    if (Test-UrlReady -Url $BackendHealthUrl) {
        Write-Host "Backend already running at $BackendUrl"
    }
    else {
        Write-Host "Starting backend..."
        Set-Content -Path $BackendOutLog -Value ""
        Set-Content -Path $BackendErrLog -Value ""
        $backendProcess = Start-Process `
            -FilePath $pythonRunner.Command `
            -ArgumentList @($pythonRunner.BaseArguments + @("main.py")) `
            -WorkingDirectory $BackendDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput $BackendOutLog `
            -RedirectStandardError $BackendErrLog `
            -PassThru
        $startedBackend = $true
    }

    if (Test-UrlReady -Url $FrontendUrl) {
        Write-Host "Frontend already running at $FrontendUrl"
    }
    else {
        Write-Host "Starting frontend..."
        Set-Content -Path $FrontendOutLog -Value ""
        Set-Content -Path $FrontendErrLog -Value ""
        $frontendProcess = Start-Process `
            -FilePath $npmCommand `
            -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1") `
            -WorkingDirectory $FrontendDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput $FrontendOutLog `
            -RedirectStandardError $FrontendErrLog `
            -PassThru
        $startedFrontend = $true
    }

    if ($startedBackend) {
        try {
            Wait-UrlReady -Name "Backend" -Url $BackendHealthUrl -Process $backendProcess -Attempts 120
        }
        catch {
            Write-Host "Backend logs:"
            Write-Host "  $BackendOutLog"
            Write-Host "  $BackendErrLog"
            throw
        }
    }

    if ($startedFrontend) {
        try {
            Wait-UrlReady -Name "Frontend" -Url $FrontendUrl -Process $frontendProcess -Attempts 120
        }
        catch {
            Write-Host "Frontend logs:"
            Write-Host "  $FrontendOutLog"
            Write-Host "  $FrontendErrLog"
            throw
        }
    }

    Write-Host ""
    Write-Host "DM_Agent is ready."
    Write-Host "Frontend: $FrontendUrl"
    Write-Host "Backend:  $BackendUrl"
    Write-Host "Logs:"
    Write-Host "  $BackendOutLog"
    Write-Host "  $BackendErrLog"
    Write-Host "  $FrontendOutLog"
    Write-Host "  $FrontendErrLog"

    if ($ExitOnReady) {
        return
    }

    if (-not $startedBackend -and -not $startedFrontend) {
        return
    }

    Write-Host ""
    Write-Host "Press Ctrl+C to stop the services started by this script."

    while ($true) {
        if ($startedBackend -and -not (Test-ProcessAlive -Process $backendProcess)) {
            Write-Host "Backend process exited unexpectedly."
            Write-Host "Backend logs:"
            Write-Host "  $BackendOutLog"
            Write-Host "  $BackendErrLog"
            throw "Backend process exited unexpectedly."
        }

        if ($startedFrontend -and -not (Test-ProcessAlive -Process $frontendProcess)) {
            Write-Host "Frontend process exited unexpectedly."
            Write-Host "Frontend logs:"
            Write-Host "  $FrontendOutLog"
            Write-Host "  $FrontendErrLog"
            throw "Frontend process exited unexpectedly."
        }

        Start-Sleep -Seconds 2
    }
}
finally {
    Stop-StartedProcess -Process $frontendProcess -WasStartedByScript $startedFrontend
    Stop-StartedProcess -Process $backendProcess -WasStartedByScript $startedBackend
}
