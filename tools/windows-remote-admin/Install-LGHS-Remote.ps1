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

Require-Command "ssh.exe" "Install the Windows OpenSSH Client optional feature."
Require-Command "ssh-keygen.exe" "Install the Windows OpenSSH Client optional feature."

if (-not (Get-Command "cloudflared.exe" -ErrorAction SilentlyContinue)) {
    if (Get-Command "winget.exe" -ErrorAction SilentlyContinue) {
        Write-Host "cloudflared is not installed. Installing Cloudflare.cloudflared with winget..."
        & winget.exe install --id Cloudflare.cloudflared --exact --accept-package-agreements --accept-source-agreements
    }
}
Require-Command "cloudflared.exe" "Install cloudflared from Cloudflare before continuing."

$sshDir = Split-Path -Parent $KeyPath
New-Item -ItemType Directory -Force -Path $sshDir | Out-Null
if (-not (Test-Path $KeyPath)) {
    & ssh-keygen.exe -t ed25519 -a 64 -f $KeyPath -N '""' -C "LGHS remote admin $AdminName"
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
    ProxyCommand cloudflared.exe access ssh --hostname %h
$end
"@
Set-Content -Path $configPath -Value (($config.TrimEnd() + "`r`n`r`n" + $block).TrimStart()) -Encoding ascii

$bin = Join-Path $HOME "bin"
New-Item -ItemType Directory -Force -Path $bin | Out-Null
$launcher = Join-Path $bin "lghs.cmd"
@"
@echo off
ssh.exe -t $Alias %*
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
