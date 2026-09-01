$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host ''
Write-Host '============================================================' -ForegroundColor DarkCyan
Write-Host '          LGHS FLEET WEB UI - SAFE LOCAL PREVIEW' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor DarkCyan
Write-Host ''
Write-Host 'This preview uses built-in mock fleet data only.' -ForegroundColor Yellow
Write-Host 'It does not connect to LGCSCONT or make fleet changes.' -ForegroundColor Yellow
Write-Host ''

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Node.js is required but was not found in PATH.'
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw 'npm is required but was not found in PATH.'
}

Write-Host ("Node: " + (node --version)) -ForegroundColor DarkGray
Write-Host ("npm:  " + (npm --version)) -ForegroundColor DarkGray
Write-Host ''

if (-not (Test-Path (Join-Path $PSScriptRoot 'node_modules'))) {
    Write-Host 'Installing UI dependencies...' -ForegroundColor Cyan
    npm install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "npm install failed with exit code $LASTEXITCODE" }
}

$previewUrl = 'http://127.0.0.1:5173/'
Write-Host ''
Write-Host "Opening $previewUrl" -ForegroundColor Green
Write-Host 'Press Ctrl+C in this window to stop the preview.' -ForegroundColor DarkGray
Write-Host ''

Start-Process $previewUrl
$env:VITE_LGHS_MOCK = '1'
npm run dev
if ($LASTEXITCODE -ne 0) { throw "Fleet preview exited with code $LASTEXITCODE" }
