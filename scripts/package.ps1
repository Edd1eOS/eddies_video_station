param([switch]$Offline)
$ErrorActionPreference = 'Stop'
$stationRoot = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $stationRoot 'dist'
New-Item -ItemType Directory -Force -Path $dist | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$kind = if ($Offline) { 'offline' } else { 'starter' }
$archive = Join-Path $dist "eddies-video-station-$kind-$stamp.zip"
$paths = @('Start Video Station.cmd', 'scripts', 'src', 'web', 'configs', 'tests', 'docs', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md')
if ($Offline) {
    if (-not (Test-Path (Join-Path $stationRoot '.runtime\python\python.exe'))) { throw 'Launch the workstation once before packaging.' }
    if (-not (Test-Path (Join-Path $stationRoot '.runtime\engine\ComfyUI_windows_portable\python_embeded\python.exe'))) { throw 'Prepare a model before packaging.' }
    $paths += @('.runtime/python', '.runtime/engine')
    $manifest = Get-Content (Join-Path $stationRoot 'configs\models.json') -Raw | ConvertFrom-Json
    $modelRoot = Join-Path $stationRoot 'data\models'
    $settings = Join-Path $stationRoot '.local\settings.json'
    if (Test-Path $settings) {
        $savedRoot = (Get-Content $settings -Raw | ConvertFrom-Json).data_root
        if ($savedRoot -and ([IO.Path]::GetFullPath($savedRoot) -ne (Join-Path $stationRoot 'data'))) { throw 'Offline packaging currently requires models in the default data folder. Existing files have not been moved.' }
    }
    $ready = @{}
    foreach ($entry in $manifest.files.PSObject.Properties) {
        $file = Join-Path $modelRoot $entry.Value.path
        if (Test-Path $file) {
            if ((Get-Item $file).Length -eq $entry.Value.size -and (Get-FileHash $file -Algorithm SHA256).Hash.ToLowerInvariant() -eq $entry.Value.sha256) {
                $ready[$entry.Name] = $true
                $paths += ('data/models/' + $entry.Value.path)
                $marker = [IO.Path]::ChangeExtension($file, '.verified')
                if (Test-Path $marker) { $paths += ('data/models/' + [IO.Path]::ChangeExtension($entry.Value.path, '.verified')) }
            }
        }
    }
    $complete = @($manifest.profiles | Where-Object { @($_.files | Where-Object { -not $ready[$_] }).Count -eq 0 })
    if ($complete.Count -eq 0) { throw 'No complete verified model set. Prepare a model first.' }
}
Push-Location $stationRoot
try {
    & tar.exe -a -cf $archive --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' --exclude='*.part' @paths
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed. The original installation is unchanged.' }
    Write-Host "Package ready: $archive"
    Write-Host 'No project database, user references, generated works, API tokens or machine settings included.'
} finally { Pop-Location }
