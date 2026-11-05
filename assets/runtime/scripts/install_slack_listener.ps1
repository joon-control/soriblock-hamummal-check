. (Join-Path $PSScriptRoot 'runtime.ps1')
$listenerScript = Join-Path $PSScriptRoot 'slack_command_listener.py'
$taskName = 'Hamummal-' + $profileConfig.profile_id + '-SlackCommands'
$pythonPath = (& $python -c 'import sys; print(sys.executable)').Trim()
$pythonw = Join-Path (Split-Path $pythonPath -Parent) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'pythonw.exe가 필요합니다.' }
$stateDir = Join-Path $profileDir 'slack_listener'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
@{ powershell = (Get-Command pwsh.exe -ErrorAction Stop).Source; poll_seconds = 5 } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stateDir 'config.json') -Encoding UTF8
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.Actions.Arguments -ne ('-u "' + $listenerScript + '"')) { throw '같은 이름의 다른 작업이 있습니다.' }
    if ($existing.State -eq 'Running') { throw '수신기가 실행 중입니다. 진행 중인 요청을 확인하고 중지한 뒤 설치해주세요.' }
}
$account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $pythonw -Argument ('-u "' + $listenerScript + '"') -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
@{ installed = $true; task_name = $taskName } | ConvertTo-Json -Compress
