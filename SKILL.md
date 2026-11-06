---
name: hamummal-check
description: Set up and run Soritune 하멈말 voice-submission checks for a new cohort or team using a verified KakaoTalk communication-room roster, Slack reporting, and the leader checklist API. Use when changing teams, members, rooms, channels, or check times, or when running, pausing, or resuming this workflow.
---

# 하멈말 체크

새 기수·조마다 독립 프로젝트를 만들고 카카오톡 소통방의 음성 제출을 판정해 Slack 보고와 조장 체크리스트 반영을 수행한다. 실행 코드와 가상 설정 예시가 포함되어 있다.

## 빠른 점검 명령

이미 설정된 조별 프로젝트에서 `체크` 또는 `check`를 요청하면 첫 실행 도구에서 `scripts/run_check_now.ps1`을 호출한다. 별도의 시계 조회, 코드 탐색, 집계 방식 선택을 먼저 수행하지 않는다. 현재 날짜·자료 기준 시각 선택과 이름·음성 검증은 코드가 처리한다. 오류가 있을 때 진단한다.

이 경로는 상주 수신기의 RAM 키를 검증해 재사용하고 현재 현황을 Slack에 보낸다. 결과의 실제 as_of와 source_lag_seconds를 표시한다. PC 기록이 요청 시각보다 오래되었으면 그 시각 차이를 알린다. 명시한 시각, 최종본과 시스템 체크 요청은 해당 별도 경로를 따른다. [운영 절차](references/operations.md)에 실행 조건과 시간 측정 범위가 있다.

## 새 조 설정

1. 기존 설정과 실행 상태를 먼저 확인한다. 새 조는 고유 profile_id와 별도 프로젝트를 사용한다. `python scripts/create_project.py --target <새 프로젝트 경로>`로 번들 실행 코드를 복사한다.
2. [설정 안내](references/setup.md)를 읽고 기수·조, 명단 출처, 소통방, Slack 목적지, 제출·보고 시간과 시스템 반영 범위를 확인한다. 연결된 명단이나 기존 설정에서 확인할 수 있는 값은 먼저 조회한다. 예시의 시간은 기존 운영에서 가져온 기본값이므로 새 일정과 대조한다.
3. 실명, 사이트 이름, 조방 이름, 소통방 이름과 소통방 작성자 ID를 각각 매칭한다. 방마다 닉네임과 ID가 다를 수 있다. 소통방 부재를 사용자가 확인한 경우에만 author_id를 null, absent_confirmed를 true로 지정한다. 이전 조의 예외를 새 조에 적용하지 않는다.
4. 선택한 DB 경로·방 ID·실제 제목과 전체 명단을 검증한 뒤 config.local.json의 source_verified와 mapping_verified를 true로 기록한다. 숫자 ID는 문자열로 저장한다. `python <프로젝트>/scripts/runtime_config.py`로 형식과 중복을 검사한다.
5. requirements.txt의 의존성을 준비한다. 정상 PowerShell 진입점으로 Connection과 Preview를 실행해 실제 제출·이름 매칭을 확인한 뒤 요청된 예약이나 수신기를 활성화한다.

## 점검 실행

[운영 절차](references/operations.md)의 진입점을 사용한다. 한국 시간의 날짜와 cutoff를 확인한다. HH:MM checkpoint는 해당 분 전체이고 HH:MM:SS는 지정 초까지다.

- 제출 근거는 설정한 소통방 DB와 커밋된 WAL의 해당 날짜 음성 메시지다. DB/WAL 최신성, 무결성, 작성자 ID와 음성 근거를 검증한다.
- 카카오톡 UI를 자동 조작하지 않는다. 메모리에 키가 없으면 사용자가 해당 소통방을 열도록 안내한다. 읽기 권한이 필요하면 정당한 권한 상승을 사용한다. 키와 평문 DB는 메모리에서 처리한다.
- 중간 보고는 완료자 번호와 미완료자 @ 이름을 표시한다. 최종본은 완료자만 각 사람의 첫 음성 제출 순서로 표시한다. 중복 제출은 한 명으로 센다. Slack 표시는 조방 이름을 사용한다.
- 준비·설정 요청에는 Preview를 우선한다. 실제 전송·저장은 사용자가 요청했거나 세션에서 승인한 운영 범위 안에서 수행한다.
- 최종본은 Slack 성공 응답의 channel·ts·링크 또는 기존 성공 기록을 확인한 후 사이트를 처리한다. 완료자의 미체크 하멈말만 저장하고 재조회한다. 실패 보고에는 Slack과 사이트 단계를 구분한다.
- attempting이나 불확실한 게시 응답은 실제 채널을 확인한 뒤 처리한다. 성공 기록의 명단 snapshot을 재사용하고 임의 재전송으로 우회하지 않는다.

## 예약·Slack 명령·종료

Slack 새 연결 또는 Telegram 대체 연결 요청에는 [메시지 서비스 연결 안내](references/messaging.md)를 읽는다. 현재 실행 코드는 Slack용이다. Telegram 선택 시 안내에 따라 전송기와 게시 성공 검증을 구현·검증한 뒤 운영에 연결한다.

설정의 시각과 종료일을 담아 Codex 예약 도구로 등록한다. 프로젝트 절대 경로와 당일 날짜 규칙을 명시한다. 예약 전달은 늦을 수 있으므로 cutoff와 실제 시작 시각을 구분한다. 초 단위 실행이 필요하면 사용 가능한 로컬 스케줄러와 실행 조건을 확인하고 요청된 방법으로 구성한다.

Slack 명령 수신은 사용자가 요청한 경우 `install_slack_listener.ps1`로 설치한다. 숨김 Windows 작업을 만들고 즉시 시작한다. 상태와 task는 profile별로 분리된다.

종료일의 최종본과 시스템 반영을 확인한 뒤 Codex 예약과 해당 profile 수신기를 중지한다. 보관·삭제 범위는 사용자 지시를 따른다. 스킬은 조별 프로젝트 밖에 설치한다.

## 보관과 변경

GitHub·ZIP에는 스킬과 가상 예시를 포함한다. 개인 설정·실제 명단·로그인·DB·키·전송 기록은 개인 저장소에서 관리한다. 공개 게시나 원격 저장소 생성은 요청된 범위에서 수행한다.

변경 후 합성 명단으로 다른 조·인원·시간 설정, 전송 중복과 불확실 응답, 사이트 완료자만 변경하는 동작을 검증한다. DB 형식이나 API가 바뀌면 근거를 확인해 갱신하고 실제 연결 검증 범위를 보고한다.
