param(
    [string]$HostName = "ssh-lgcscont.scenicrouteservers.com",
    [string]$Alias = "LGHS-Control",
    [string]$AdminName = "main-pc",
    [string]$KeyPath = "$HOME\.ssh\lghs_remote_admin"
)

$ErrorActionPreference = "Stop"

function Require-Command([string]$Name, [string]$Help) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is required. $Help"
    }
}

function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = (($machine, $user) -join ';')
}

function Find-Cloudflared {
    $cmd = Get-Command "cloudflared.exe" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidates = @(
        "$env:ProgramFiles\cloudflared\cloudflared.exe",
        "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\cloudflared.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }

    if ($candidates.Count -gt 0) { return $candidates[0] }

    $roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, "$env:LOCALAPPDATA\Microsoft\WinGet\Packages") |
        Where-Object { $_ -and (Test-Path $_) }
    foreach ($root in $roots) {
        $found = Get-ChildItem -Path $root -Filter cloudflared.exe -File -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return $null
}

function Find-SshBinary([string]$Name) {
    $gitCandidate = Join-Path $env:ProgramFiles "Git\usr\bin\$Name"
    if (Test-Path $gitCandidate) { return $gitCandidate }
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$ssh = Find-SshBinary "ssh.exe"
$sshKeygen = Find-SshBinary "ssh-keygen.exe"
if (-not $ssh -or -not $sshKeygen) {
    throw "SSH client tools are required. Install Git for Windows or the Windows OpenSSH Client."
}
Write-Host "Using SSH: $ssh" -ForegroundColor DarkGray

$cloudflared = Find-Cloudflared
if (-not $cloudflared) {
    if (Get-Command "winget.exe" -ErrorAction SilentlyContinue) {
        Write-Host "cloudflared is not installed or is not visible in this PowerShell session. Installing Cloudflare.cloudflared with winget..."
        & winget.exe install --id Cloudflare.cloudflared --exact --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -notin @(0, -1978335189)) {
            Write-Warning "winget returned exit code $LASTEXITCODE; checking for an installed cloudflared anyway."
        }
        Refresh-ProcessPath
        $cloudflared = Find-Cloudflared
    }
}
if (-not $cloudflared) {
    throw "cloudflared.exe is installed but could not be located. Open a new PowerShell window and rerun this installer, or verify 'where.exe cloudflared' returns a path."
}
Write-Host "Using cloudflared: $cloudflared" -ForegroundColor DarkGray

$sshDir = Split-Path -Parent $KeyPath
New-Item -ItemType Directory -Force -Path $sshDir | Out-Null
if (-not (Test-Path $KeyPath)) {
    & $sshKeygen -t ed25519 -a 64 -f $KeyPath -N '""' -C "LGHS remote admin $AdminName"
    if ($LASTEXITCODE -ne 0) { throw "ssh-keygen failed" }
}

$pub = Get-Content "$KeyPath.pub" -Raw
Write-Host ""
Write-Host "=== PUBLIC KEY TO ENROLL ON LGCSCONT ===" -ForegroundColor Cyan
Write-Host $pub.Trim()
Write-Host ""
Write-Host "On LGCSCONT run:" -ForegroundColor Yellow
Write-Host "  sudo lghs-remote-admin enroll $AdminName"
Write-Host "Paste the public key above and press Ctrl+D."
Write-Host "Also run: sudo lghs-remote-admin fingerprint"
Write-Host "Keep that fingerprint visible for the first connection."

$configPath = Join-Path $sshDir "config"
if (-not (Test-Path $configPath)) { New-Item -ItemType File -Path $configPath | Out-Null }
$config = Get-Content $configPath -Raw
$begin = "# BEGIN LGHS REMOTE ADMIN"
$end = "# END LGHS REMOTE ADMIN"
$escapedBegin = [regex]::Escape($begin)
$escapedEnd = [regex]::Escape($end)
$config = [regex]::Replace($config, "(?s)$escapedBegin.*?$escapedEnd\s*", "")
$keyForConfig = $KeyPath -replace '\\','/'
$cloudflaredForConfig = $cloudflared -replace '\\','/'
$block = @"
$begin
Host $Alias
    HostName $HostName
    User lghs_remote
    IdentityFile $keyForConfig
    IdentitiesOnly yes
    StrictHostKeyChecking ask
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    ForwardAgent no
    ForwardX11 no
    ClearAllForwardings yes
    ServerAliveInterval 20
    ServerAliveCountMax 3
    ProxyCommand "$cloudflaredForConfig" access ssh --hostname %h
$end
"@
Set-Content -Path $configPath -Value (($config.TrimEnd() + "`r`n`r`n" + $block).TrimStart()) -Encoding ascii

$bin = Join-Path $HOME "bin"
New-Item -ItemType Directory -Force -Path $bin | Out-Null
$launcher = Join-Path $bin "lghs.cmd"
@"
@echo off
"$ssh" -t $Alias %*
"@ | Set-Content -Path $launcher -Encoding ascii

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$pathParts = @($userPath -split ';' | Where-Object { $_ })
if ($pathParts -notcontains $bin) {
    [Environment]::SetEnvironmentVariable("Path", (($pathParts + $bin) -join ';'), "User")
}

Write-Host ""
Write-Host "Windows side is ready." -ForegroundColor Green
Write-Host "After the key is enrolled on LGCSCONT, open a NEW PowerShell window and run:"
Write-Host "  lghs"
Write-Host ""
Write-Host "On first connection, OpenSSH will show the controller host-key fingerprint."
Write-Host "Compare it with 'sudo lghs-remote-admin fingerprint' on LGCSCONT before typing yes."
Write-Host ""
Write-Host "Other examples:"
Write-Host "  lghs status"
Write-Host "  lghs update CS-999"
Write-Host "  lghs os-update CS-999"
Write-Host "  lghs update-controller"
Write-Host "  lghs ssh CS-999"
