# 실행과 운영

생성한 조별 프로젝트에서 실행한다. 날짜는 실제 한국 날짜로 지정한다.

## 빠른 명령

수신기가 설치되고 실행 중이면 채팅에서는 `체크` 또는 `check` 요청에 다음 명령을 바로 사용한다. 생성한 프로젝트의 AGENTS.md에도 이 규칙이 들어 있다.

```powershell
./scripts/run_check_now.ps1
./scripts/run_check_now.ps1 -Preview
```

상주 수신기는 시작 시 키를 한 번 찾고 RAM에 유지한다. 요청마다 카카오톡 프로세스 ID와 선택한 DB 첫 페이지로 키를 검증한다. 프로세스가 바뀌거나 키 검증에 실패하면 다시 탐색한다. 수신기를 중지하면 메모리의 키가 해제된다. 날짜 변경만으로 캐시를 비우지 않는다.

로컬 클라이언트는 profile별 slack_listener/quick_requests에 고정된 점검 요청을 등록하고 응답을 기다린다. 완료·중단 요청은 자동 재실행하지 않는다. Slack은 기존 5초 간격으로 수신하므로 감지 대기와 API 응답 시간이 추가된다. 최초 키 준비와 재탐색은 수십 초 걸릴 수 있다.

빠른 현황은 요청 시각과 DB/WAL 마지막 변경 시각 중 이른 시각까지 집계한다. 마지막 변경이 요청보다 앞서면 as_of와 source_lag_seconds에 표시된다. 오래된 PC 자료를 현재 시각의 결과로 표시하지 않는다. source_lag가 크면 동기화 상태를 확인한다.

결과의 worker_seconds는 작업 처리 시간이고 request_to_completed_seconds는 요청 등록부터 완료까지다. 로컬 클라이언트의 측정에는 그 전에 발생한 ChatGPT 응답·도구 호출 대기가 포함되지 않는다. Slack 명령 답장은 Slack 메시지 작성 시각부터 결과 확인까지를 표시한다.

기존 프로젝트에 업데이트하려면 진행 중인 명령을 확인하고 수신기를 중지한 뒤 해당 프로세스의 실제 종료를 확인한다. 코드 갱신 후 다시 시작해 status.json의 listening과 key_ready를 확인한다. 초기 키 준비 중에는 warming_key가 표시된다.

## 일반 점검과 최종본

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

`체크`, `check`는 대소문자를 구분하지 않는 빠른 현황 보고 명령이다. 이 두 명령은 최종 경계 이후에도 그날의 최신 현황을 보고한다. 기존 최종본·시스템 저장 경로와 별도로 실행된다.

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

## 코드 변경 검증

Windows에서 의존성을 준비한 뒤 `python tests/test_runtime.py`를 실행한다. 이 테스트는 가상 프로젝트를 만들어 다른 조·인원·시간, 키 재사용·무효화, 전송 중복, 완료자만 사이트 변경, 요청 중단을 검사한다. 네트워크 호출은 대체하여 실제 게시와 저장을 수행하지 않는다.
