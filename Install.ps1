[CmdletBinding()]
param(
    [string]$Workspace = (Join-Path $HOME 'OpenSourceRadar')
)
$ErrorActionPreference = 'Stop'
$Source = $PSScriptRoot
$Target = Join-Path $HOME '.agents\skills\open-source-radar'

# User must invoke this installer explicitly. No scheduling, remote writes or package installation.
if (Test-Path -LiteralPath $Target) {
    throw "Skill already exists at $Target. Review differences before an explicitly authorized update; no overwrite was performed."
}
if ((Test-Path -LiteralPath $Workspace) -and
    -not (Test-Path -LiteralPath (Join-Path $Workspace 'state\radar.sqlite3'))) {
    $Items = @(Get-ChildItem -LiteralPath $Workspace -Force)
    if ($Items.Count -gt 0) {
        throw 'Workspace is nonempty and unrecognized. Choose a dedicated empty folder; existing files were not changed.'
    }
}
$Python = Get-Command python -ErrorAction Stop
& $Python.Source -B -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 or newer is required. No dependencies were installed.' }
& $Python.Source -B -m unittest discover -s (Join-Path $Source 'tests') -v
if ($LASTEXITCODE -ne 0) { throw 'Offline tests failed. Installation was stopped.' }

& $Python.Source -B (Join-Path $Source 'scripts\package_manifest.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Package integrity check failed. Installation was stopped.' }
$Manifest = Get-Content -LiteralPath (Join-Path $Source 'PACKAGE_MANIFEST.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$PackageFiles = @('PACKAGE_MANIFEST.json') + @($Manifest.files | ForEach-Object { $_.path })
$Parent = Split-Path -Parent $Target
New-Item -ItemType Directory -Path $Parent -Force | Out-Null
New-Item -ItemType Directory -Path $Target | Out-Null
foreach ($RelativePath in $PackageFiles) {
    $Destination = Join-Path $Target $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $Source $RelativePath) -Destination $Destination
}
& $Python.Source -B (Join-Path $Target 'scripts\radar.py') --workspace $Workspace init
if ($LASTEXITCODE -ne 0) {
    throw "Skill was copied, but workspace initialization failed. Inspect $Workspace; no cleanup or overwrite will be attempted."
}
Write-Output "Skill installed at: $Target"
Write-Output "Workspace initialized at: $Workspace"
Write-Output 'Daily schedule: NOT ENABLED. Follow references/SCHEDULING.md after a successful manual network run.'
