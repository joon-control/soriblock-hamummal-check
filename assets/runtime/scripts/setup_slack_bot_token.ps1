. (Join-Path $PSScriptRoot 'runtime.ps1')
$secureToken = Read-Host -AsSecureString 'Slack 봇 토큰 입력'
$tokenPtr = [IntPtr]::Zero
try {
    $tokenPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
    $tokenValue = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPtr)
    if (-not $tokenValue.StartsWith('xoxb-')) { throw 'Slack 봇 토큰 형식을 확인해주세요.' }
    [Environment]::SetEnvironmentVariable($profileConfig.slack.token_env, $tokenValue, 'User')
    Write-Host '설정한 Windows 사용자 환경 변수에 저장했습니다.'
} finally {
    $tokenValue = $null
    if ($tokenPtr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPtr) }
}
