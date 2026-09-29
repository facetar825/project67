param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    & $Python -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependencies failed' }
    & $Python -m PyInstaller --noconfirm --clean --windowed --onedir --name QuestDesk --add-data 'database;database' app.py
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
    New-Item -ItemType Directory -Force 'dist\QuestDesk\vendor' | Out-Null
    Copy-Item -LiteralPath 'vendor\pgsql' -Destination 'dist\QuestDesk\vendor\pgsql' -Recurse -Force
    Copy-Item -LiteralPath 'README.md' -Destination 'dist\QuestDesk\README.md' -Force
} finally { Pop-Location }
