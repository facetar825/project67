$ErrorActionPreference = 'Stop'
$dataRoot = if ($env:QUESTDESK_HOME) { $env:QUESTDESK_HOME } else { Join-Path $env:LOCALAPPDATA 'QuestDesk' }
& (Join-Path $dataRoot 'runtime\pgsql\bin\pg_ctl.exe') -D (Join-Path $dataRoot 'pgdata') -m fast -w stop
if ($LASTEXITCODE -ne 0) { throw 'Could not stop PostgreSQL. It may already be stopped.' }
