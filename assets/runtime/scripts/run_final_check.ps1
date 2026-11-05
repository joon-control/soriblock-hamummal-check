param(
    [string]$Date = ([TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'Korea Standard Time').ToString('yyyy-MM-dd')),
    [string]$ThreadTs
)
. (Join-Path $PSScriptRoot 'runtime.ps1')
$today = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'Korea Standard Time').ToString('yyyy-MM-dd')
if ($Date -ne $today) { throw '최종 점검은 실행 당일 한국 날짜에만 가능합니다.' }
$finalLabel = ([TimeSpan]::Parse($profileConfig.final_time)).ToString('hh\:mm')
if (([TimeSpan]::Parse($profileConfig.final_time)).Seconds -ne 0) { $finalLabel = $profileConfig.final_time }
$slackText = & (Join-Path $PSScriptRoot 'run_slack_api_delivery.ps1') -Action Send -Date $Date -AsOf $finalLabel -ThreadTs $ThreadTs
if ($LASTEXITCODE -ne 0) { throw 'Slack 전송 단계에 실패했습니다.' }
$slack = $slackText | ConvertFrom-Json
if (-not ($slack.sent -or $slack.already_sent) -or
    $slack.channel -ne $profileConfig.slack.channel_id -or
    -not $slack.ts -or -not $slack.permalink -or
    $slack.date -ne $Date -or $slack.as_of -ne $finalLabel -or
    ($slack.completed.Count + $slack.missing.Count) -ne $profileConfig.expected_member_count) {
    throw 'Slack 게시 응답과 명단 검증에 실패했습니다.'
}
if (-not (Test-Path -LiteralPath $credentialFile)) { throw 'Slack 게시 완료. 사이트 로그인 정보가 필요합니다.' }
$phonePtr = [IntPtr]::Zero
try {
    $saved = Get-Content -LiteralPath $credentialFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $phonePtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR((ConvertTo-SecureString $saved.phone))
    $env:SORITUNE_LEADER_PHONE = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($phonePtr)
    $payload = @{ date = $Date; completed = @($slack.completed); missing = @($slack.missing) } | ConvertTo-Json -Compress -Depth 4
    $siteText = $payload | & $python (Join-Path $PSScriptRoot 'site_checklist_api.py')
    if ($LASTEXITCODE -ne 0) { throw 'Slack 게시 완료. 사이트 저장 또는 재조회에 실패했습니다.' }
    $site = $siteText | ConvertFrom-Json
    if (-not $site.saved -or -not $site.verified_after_save -or $site.date -ne $Date) { throw '사이트 저장 후 검증 실패' }
    @{ slack = $slack; site = $site } | ConvertTo-Json -Compress -Depth 6
} finally {
    Remove-Item Env:SORITUNE_LEADER_PHONE -ErrorAction SilentlyContinue
    if ($phonePtr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($phonePtr) }
}
