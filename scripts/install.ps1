# dsnode one-line installer for Windows
#
# Usage (behind Caddy/Nginx, the API base is https://hub.example.com/api;
# when connecting directly to the hub API it is http://hub.example.com:9090):
#   $env:GITHUB_REPO="unikii/dsentry"; $env:API_ENDPOINT="https://hub.example.com/api"; $env:PUSH_KEY="uuid_push_key"; iwr -useb https://raw.githubusercontent.com/unikii/dsentry/master/scripts/install.ps1 | iex
#
# Or:
#   .\install.ps1 -ApiEndpoint "https://hub.example.com/api" -PushKey "uuid_push_key" -GithubRepo "unikii/dsentry"
#
# Safe to re-run for upgrades: the download is verified before it
# replaces the live binary, and dsnode.toml / dsnode.json are preserved.

param(
    [string]$ApiEndpoint = $env:API_ENDPOINT,
    [string]$PushKey = $env:PUSH_KEY,
    [string]$InstallDir = "C:\Program Files\dSentry",
    [string]$GithubRepo = $env:GITHUB_REPO,
    [switch]$SkipSmartctlCheck
)

$ErrorActionPreference = "Stop"

if (-not $GithubRepo) {
    $GithubRepo = "unikii/dsentry"
}

if (-not $ApiEndpoint -or -not $PushKey) {
    Write-Host "Error: API endpoint and push key are required." -ForegroundColor Red
    Write-Host "Usage: .\install.ps1 -ApiEndpoint 'https://hub.example.com/api' -PushKey 'uuid_push_key' -GithubRepo 'unikii/dsentry'"
    exit 1
}

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Warning: not running as Administrator. Installing to '$InstallDir' and querying disks with smartctl both normally require elevation." -ForegroundColor Yellow
}

if (-not $SkipSmartctlCheck -and -not (Get-Command smartctl -ErrorAction SilentlyContinue)) {
    Write-Host "Error: 'smartctl' not found on PATH." -ForegroundColor Red
    Write-Host "dsnode shells out to smartctl (smartmontools) for every scan, so it cannot report anything without it."
    Write-Host "Install it from https://www.smartmontools.org/wiki/Download#InstalltheWindowspackage (tick 'Add to PATH' during setup), then re-run this installer."
    Write-Host "To bypass this check: .\install.ps1 ... -SkipSmartctlCheck"
    exit 1
}

# A running dsnode.exe holds a file lock, so it must be stopped before
# the binary can be replaced.
$running = Get-Process dsnode -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "Error: dsnode is currently running (PID $($running.Id -join ', ')). Stop it first so dsnode.exe can be replaced:" -ForegroundColor Red
    Write-Host "  nssm stop dsnode   # if installed via NSSM"
    Write-Host "  Stop-ScheduledTask -TaskName dsnode   # if via Scheduled Task"
    exit 1
}

$ReleasesUrl = "https://github.com/$GithubRepo/releases"
Write-Host "=== dsnode Installer ===" -ForegroundColor Green

$os = "windows"
$arch = switch ([System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture) {
    "X64"  { "amd64" }
    "Arm64" { "arm64" }
    default {
        Write-Host "Unsupported architecture: $([System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture)" -ForegroundColor Red
        exit 1
    }
}

$binary = "dsnode-${os}-${arch}.exe"
$downloadUrl = "${ReleasesUrl}/latest/download/${binary}"
$checksumUrl = "${ReleasesUrl}/latest/download/${binary}.sha256"

Write-Host "Platform: ${os}/${arch}"
Write-Host "Install dir: ${InstallDir}"
Write-Host "Downloading: ${downloadUrl}"

if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

$binaryPath = Join-Path $InstallDir "dsnode.exe"
$checksumPath = Join-Path $InstallDir "dsnode.exe.sha256"

# Download to temp files first: a half-written download must never
# replace a working binary.
$tmpBinary = Join-Path $InstallDir "dsnode.exe.new"
$tmpChecksum = Join-Path $InstallDir "dsnode.exe.new.sha256"

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $downloadUrl -OutFile $tmpBinary
Invoke-WebRequest -Uri $checksumUrl -OutFile $tmpChecksum

$expected = (Get-Content $tmpChecksum).Split()[0].ToUpper()
$actual = (Get-FileHash -Path $tmpBinary -Algorithm SHA256).Hash.ToUpper()

if ($expected -ne $actual) {
    Write-Host "Checksum verification failed!" -ForegroundColor Red
    Write-Host "Expected: $expected"
    Write-Host "Actual:   $actual"
    Remove-Item $tmpBinary, $tmpChecksum -ErrorAction SilentlyContinue
    exit 1
}

Remove-Item $tmpChecksum
Move-Item -Path $tmpBinary -Destination $binaryPath -Force
Write-Host "Binary installed and verified." -ForegroundColor Green

Write-Host ""
Write-Host "Registering node with dSentry..."
$regResult = & $binaryPath -register -api-endpoint $ApiEndpoint -push-key $PushKey 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Registration failed:" -ForegroundColor Red
    Write-Host $regResult
    exit 1
}
Write-Host $regResult

Write-Host ""
Write-Host "=== dsnode installed successfully ===" -ForegroundColor Green
Write-Host ""
Write-Host "To run manually:"
Write-Host "  & '$binaryPath'"
Write-Host ""
Write-Host "If dsnode runs in the background, restart it to pick up the new binary:"
Write-Host "  nssm restart dsnode   # if installed via NSSM"
Write-Host "  Stop-ScheduledTask -TaskName dsnode; Start-ScheduledTask -TaskName dsnode"
Write-Host ""
Write-Host "To run dsnode in the background for the first time, use a service"
Write-Host "wrapper or scheduled task. dsnode is a console app and does not"
Write-Host "implement the Windows Service Control Manager API, so plain"
Write-Host "New-Service will fail to start it (error 1053)."
Write-Host ""
Write-Host "Option 1: NSSM (https://nssm.cc/download), in an elevated shell:"
Write-Host "  nssm install dsnode `"$binaryPath`""
Write-Host "  nssm set dsnode AppDirectory `"$InstallDir`""
Write-Host "  nssm set dsnode Start SERVICE_AUTO_START"
Write-Host "  nssm start dsnode"
Write-Host ""
Write-Host "Option 2: Scheduled Task at startup (built in, elevated shell):"
Write-Host "  `$action = New-ScheduledTaskAction -Execute '$binaryPath'"
Write-Host "  `$trigger = New-ScheduledTaskTrigger -AtStartup"
Write-Host "  Register-ScheduledTask -TaskName dsnode -Action `$action -Trigger `$trigger -User SYSTEM -RunLevel Highest"
Write-Host "  Start-ScheduledTask -TaskName dsnode"
