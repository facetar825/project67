$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$vendorRoot = Join-Path $projectRoot 'vendor'
New-Item -ItemType Directory -Force -Path $vendorRoot | Out-Null
$archive = Join-Path $vendorRoot 'postgresql.zip'
if (-not (Test-Path -LiteralPath $archive)) {
    Invoke-WebRequest -Uri 'https://get.enterprisedb.com/postgresql/postgresql-17.6-1-windows-x64-binaries.zip' -OutFile $archive
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($archive)
try {
    foreach ($entry in $zip.Entries) {
        if ($entry.FullName -match '^pgsql/(bin|lib|share)/' -and $entry.Name) {
            $target = [IO.Path]::GetFullPath((Join-Path $vendorRoot $entry.FullName))
            if (-not $target.StartsWith($vendorRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe archive path' }
            New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $true)
        }
    }
} finally { $zip.Dispose() }
Write-Host 'PostgreSQL is ready. Start QuestDesk.exe or python app.py.'
