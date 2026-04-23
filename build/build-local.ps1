$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Remove-Item build-cache, dist, out -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path . -Filter __pycache__ -Recurse -Directory | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

python -m PyInstaller --clean --workpath build-cache/server --distpath dist build/tg-server.spec
python -m PyInstaller --clean --workpath build-cache/cli --distpath dist build/tg-cli.spec

if (!(Test-Path 'dist/tg-server.exe')) { throw 'dist/tg-server.exe not found' }
if (!(Test-Path 'dist/tg-cli.exe')) { throw 'dist/tg-cli.exe not found' }

New-Item -ItemType Directory -Force -Path out/windows | Out-Null
Copy-Item dist/tg-server.exe out/windows/
Copy-Item dist/tg-cli.exe out/windows/
Copy-Item README.md out/windows/
if (Test-Path 'docs.md') { Copy-Item docs.md out/windows/ }
Compress-Archive -Path out/windows/* -DestinationPath out/tg-windows-x64.zip -Force
Write-Host 'Built: out/tg-windows-x64.zip'
