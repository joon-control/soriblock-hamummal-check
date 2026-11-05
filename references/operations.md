# 실행과 운영

생성한 조별 프로젝트에서 실행한다. 날짜는 실제 한국 날짜로 지정한다.

```powershell
# 설정 형식 검증
python ./scripts/runtime_config.py
# Slack 인증·워크스페이스 확인
./scripts/run_slack_api_delivery.ps1 -Action Connection
# 외부 게시 없이 해당 cutoff의 제출 검증
./scripts/run_slack_api_delivery.ps1 -Action Preview -Date 'YYYY-MM-DD' -AsOf '13:45:00'
# 승인된 실제 전송. 해당 초까지 집계
./scripts/run_slack_api_delivery.ps1 -Action Send -AsOf '13:45:00'
# 설정의 분 전체 checkpoint. 13:50:59까지 집계
./scripts/run_slack_api_delivery.ps1 -Action Send -AsOf '13:50'
# 당일 최종 Slack 게시 후 사이트 저장과 재조회
./scripts/run_final_check.ps1
```

Preview도 DB/WAL 최신성과 음성 근거가 필요하다. 미래 cutoff는 실행 가능한 시각까지 기다린 뒤 호출한다. 늦게 실행해도 지정된 기준 시각으로 집계한다.

## Slack 명령

`python ./scripts/slack_command_listener.py --check`는 권한만 확인한다. 요청된 명령 수신을 활성화하려면 `./scripts/install_slack_listener.ps1`을 실행한다. 로그인 시 숨김 pythonw를 시작하는 `Hamummal-<profile_id>-SlackCommands` 작업이 생기고 즉시 수신을 시작한다.

새 최상위 ‘시작’, ‘지금 체크해줘’, ‘체크해줘’를 인식한다. 10분 이상 지난 명령은 실행하지 않는다. 제출 시작 전에는 안내하고 최종 경계 이후에는 final wrapper로 처리한다. 결과는 요청의 스레드에 답장한다.

로그와 상태는 `%LOCALAPPDATA%/HamummalCheck/<profile_id>/slack_listener`에 있다. PC 전원, 사용자 로그인, 카카오톡 실행·소통방 동기화가 필요하다. Codex 예약을 쓰면 해당 앱의 로컬 실행 조건도 확인한다.

## 재시도

전송 기록은 `%LOCALAPPDATA%/HamummalCheck/<profile_id>/slack_delivery_receipts.json`에 있다. 동일 날짜·cutoff·채널은 성공 기록과 게시 당시 snapshot을 재사용한다. attempting이면 채널의 실제 게시를 확인한 뒤 처리한다. 상태 삭제나 다른 resend ID로 우회하지 않는다.

사이트는 당일만 처리하며 기수·조·실명·인원·과제 코드를 검증한다. 완료자의 미체크 칸만 저장한다. 일부 저장 후 실패하면 같은 final wrapper로 미체크를 보완하고 재조회한다.

## 중지

진행 중 요청과 마지막 결과를 확인한 뒤 해당 profile의 작업을 중지한다.

```powershell
$teamTask = 'Hamummal-<profile_id>-SlackCommands'
Disable-ScheduledTask -TaskName $teamTask
Stop-ScheduledTask -TaskName $teamTask
```

Codex 예약은 별도 예약 도구로 중지한다. 재개할 때는 설정·권한·Preview 확인 후 수신기와 예약을 활성화한다.
