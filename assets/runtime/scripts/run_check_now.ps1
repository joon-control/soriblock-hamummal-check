param([switch]$Preview)
. (Join-Path $PSScriptRoot 'runtime.ps1')
$requestArgs = @()
if ($Preview) { $requestArgs += '--preview' }
& $python (Join-Path $PSScriptRoot 'request_quick_check.py') @requestArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
