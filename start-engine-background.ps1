<#
.SYNOPSIS
    Start the Icarus engine + dashboard in the background, exactly once.

.DESCRIPTION
    The pid file alone is not proof the dashboard is up. A cmd.exe wrapper can
    die and leave its pid recorded, or Windows can recycle the id onto an
    unrelated process -- and then every later launch sees a "running" engine
    that is not serving anything, and refuses to replace it. That failure is
    silent and it persists until someone deletes the file by hand.

    So liveness is decided by the only authority that can answer it: the
    dashboard's own /healthz endpoint. A pid file whose endpoint does not
    answer is stale by definition, and gets removed rather than obeyed.

    The probe is aimed at 127.0.0.1 deliberately. The server rejects requests
    carrying a foreign Host header (DNS-rebinding defence), so a probe sent to
    a hostname that resolves elsewhere would come back 403 and be misread as
    "dead" on a dashboard that is perfectly healthy.

.PARAMETER Port
    Dashboard port. Matches the CLI default in icarus_engine/cli.py.

.EXAMPLE
    .\start-engine-background.ps1
    .\start-engine-background.ps1 -Port 8800 -Force
#>
[CmdletBinding()]
param(
    [int]    $Port    = 8791,
    [string] $Token   = $env:ICARUS_ADMIN_TOKEN,
    [string] $PidFile = (Join-Path $PSScriptRoot ".engine.pid"),
    [string] $LogFile = (Join-Path $PSScriptRoot "logs\engine.log"),
    [switch] $Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$pidFile = $PidFile
$healthUrl = "http://127.0.0.1:$Port/healthz"

function Test-DashboardLive {
    param([string] $Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -eq 200
    } catch {
        # Refused, timed out, or answered non-200: not serving. Either way the
        # recorded pid is not a dashboard we can use.
        return $false
    }
}

if (Test-DashboardLive -Url $healthUrl) {
    if (-not $Force) {
        Write-Host "Engine already serving on $healthUrl - nothing to do."
        Write-Host "Pass -Force to stop it and start a replacement."
        exit 0
    }
    if (Test-Path $pidFile) {
        $livePid = (Get-Content $pidFile -Raw).Trim()
        Write-Host "-Force given: stopping live engine (pid $livePid)."
        Stop-Process -Id $livePid -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
}

# Past this point nothing is answering, so any pid file is stale by definition.
if (Test-Path $pidFile) {
    Write-Host "Stale pid file at $pidFile (no answer from $healthUrl) - clearing it."
    Remove-Item $pidFile -Force
}

$logDir = Split-Path -Parent $LogFile
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

$arguments = @("-m", "icarus_engine.cli", "run", "--port", "$Port")
if ($Token) { $arguments += @("--token", $Token) }

$process = Start-Process -FilePath "python" `
                         -ArgumentList $arguments `
                         -WorkingDirectory $PSScriptRoot `
                         -RedirectStandardOutput $LogFile `
                         -RedirectStandardError "$LogFile.err" `
                         -WindowStyle Hidden `
                         -PassThru

Set-Content -Path $pidFile -Value $process.Id -Encoding ascii

# Record the pid only after the endpoint answers, so the file never claims a
# process that failed on startup -- the exact condition this script exists to
# stop from wedging the next launch.
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    if (Test-DashboardLive -Url $healthUrl) {
        Write-Host "Engine up: http://127.0.0.1:$Port/  (pid $($process.Id), log $LogFile)"
        exit 0
    }
    Start-Sleep -Milliseconds 500
}

Write-Warning "Engine did not answer $healthUrl within 30s. See $LogFile.err"
if (Test-Path $pidFile) { Remove-Item $pidFile -Force }
exit 1
