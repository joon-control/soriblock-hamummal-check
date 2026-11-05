$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$profileConfig = Get-Content -LiteralPath (Join-Path $projectRoot 'config.local.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$python = $profileConfig.python_executable
if (-not $python) { $python = $env:HAMUMMAL_PYTHON }
if (-not $python) { $python = (Get-Command python.exe -ErrorAction Stop).Source }
$env:PYTHONIOENCODING = 'utf-8'
& $python (Join-Path $PSScriptRoot 'runtime_config.py') | Out-Null
if ($LASTEXITCODE -ne 0) { throw '조별 설정 검증에 실패했습니다.' }
$profileDir = Join-Path (Join-Path $env:LOCALAPPDATA 'HamummalCheck') $profileConfig.profile_id
$credentialFile = Join-Path $profileDir 'site_login.dpapi.json'
