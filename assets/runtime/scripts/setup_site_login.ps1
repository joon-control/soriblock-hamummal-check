. (Join-Path $PSScriptRoot 'runtime.ps1')
$phone = (Read-Host '조장 로그인 휴대폰 번호를 하이픈 없이 입력').Trim()
if ($phone -notmatch '^01[016789][0-9]{7,8}$') { throw '휴대폰 번호 형식을 확인해주세요.' }
New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
$securePhone = ConvertTo-SecureString $phone -AsPlainText -Force
@{ phone = ConvertFrom-SecureString $securePhone } | ConvertTo-Json | Set-Content -LiteralPath $credentialFile -Encoding UTF8
Write-Host '현재 Windows 사용자 전용으로 저장했습니다.'
