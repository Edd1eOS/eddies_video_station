param([switch]$NoBrowser, [switch]$Mcp)
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$stationRoot = Split-Path -Parent $PSScriptRoot
$pythonRoot = Join-Path $stationRoot '.runtime\python'
$pythonExe = Join-Path $pythonRoot 'python.exe'
try {
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        New-Item -ItemType Directory -Force -Path $pythonRoot | Out-Null
        $archive = Join-Path $stationRoot '.runtime\python.zip'
        [Console]::Error.WriteLine('Preparing private Python runtime (first launch only)...')
        & curl.exe -fL --retry 3 -o $archive 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip'
        if ($LASTEXITCODE -ne 0) { throw 'Python download failed. Double click again to retry.' }
        if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne '4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3') { throw 'Python archive checksum failed. Please retry.' }
        Expand-Archive -LiteralPath $archive -DestinationPath $pythonRoot -Force
    }
    if ($Mcp) { & $pythonExe -I (Join-Path $stationRoot 'src\mcp_server.py'); exit $LASTEXITCODE }
    $ready = $false
    try { $ready = (Invoke-RestMethod 'http://127.0.0.1:8765/api/health' -TimeoutSec 2).app -eq 'eddies-video-station' } catch {}
    if (-not $ready) {
        $logDir = Join-Path $stationRoot '.local'
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        Start-Process -FilePath $pythonExe -ArgumentList @('-I', ('"' + (Join-Path $stationRoot 'src\server.py') + '"')) -WorkingDirectory $stationRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'server.log') -RedirectStandardError (Join-Path $logDir 'server.error.log') | Out-Null
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Milliseconds 500
            try { $ready = (Invoke-RestMethod 'http://127.0.0.1:8765/api/health' -TimeoutSec 1).app -eq 'eddies-video-station' } catch {}
            if ($ready) { break }
        }
    }
    if (-not $ready) { throw 'Could not start. See .local\server.error.log (port 8765 may be occupied).' }
    if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8765' }
    Write-Host 'Video Station: http://127.0.0.1:8765'
} catch { Write-Error $_; exit 1 }
