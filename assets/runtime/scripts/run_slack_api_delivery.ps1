param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Connection', 'Preview', 'Test', 'Send')]
    [string]$Action,
    [string]$AsOf,
    [string]$Date = ([TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'Korea Standard Time').ToString('yyyy-MM-dd')),
    [string]$ThreadTs
)
. (Join-Path $PSScriptRoot 'runtime.ps1')
$scriptFile = Join-Path $PSScriptRoot 'slack_api_delivery.py'
$actionArgs = @(switch ($Action) {
    'Connection' { @('--connection') }
    'Preview' { @('--preview') }
    'Test' { @('--test-send') }
    'Send' { @('--send') }
})
if ($Action -in @('Preview', 'Send')) {
    if (-not $AsOf) { throw '점검 기준 시각이 필요합니다.' }
    $actionArgs += @('--as-of', $AsOf)
}
$actionArgs += @('--date', $Date)
if ($ThreadTs) { $actionArgs += @('--thread-ts', $ThreadTs) }
try {
    if ($Action -ne 'Preview') {
        $env:SLACK_BOT_TOKEN = [Environment]::GetEnvironmentVariable($profileConfig.slack.token_env, 'User')
        if (-not $env:SLACK_BOT_TOKEN) { throw '설정한 Windows 사용자 환경 변수에 Slack 토큰이 없습니다.' }
    }
    & $python $scriptFile @actionArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Remove-Item Env:SLACK_BOT_TOKEN -ErrorAction SilentlyContinue
}
