# 새 조 설정

Windows용 Python 3.12 이상과 PowerShell 7을 사용한다. 스킬의 `scripts/create_project.py --target <새 경로>`가 독립 프로젝트를 생성하고 현재 Python 경로를 config.local.json에 기록한다. profile_id는 PC 전체에서 고유하게 정한다.

config.local.json은 개인 설정이며 config.example.json은 가상 예시다. source_verified와 mapping_verified가 false이면 실행이 차단된다. 형식 검증은 실제 출처 조사와 매칭 검증을 대신하지 않는다.

| 필드 | 확인할 내용 |
| --- | --- |
| cohort, group, mission | 사이트의 기수·조·하멈말 이름 |
| expected_member_count | 사용자가 맡은 조의 기준 인원 |
| window_start, final_time | 당일 시작과 최종 경계. 마지막 포함 초는 final_time의 1초 전 |
| whole_minute_checkpoints | HH:MM 목록. 해당 분 59초까지 포함하고 다음 분부터 실행 |
| kakao.user_dir | 선택한 KakaoTalk 사용자 폴더 |
| kakao.room_id, room_title | 제출 증거를 읽을 소통방의 ID·실제 제목 |
| slack.workspace_id, channel_id | Slack 워크스페이스와 채널 ID |
| slack.token_env | 봇 토큰을 저장할 Windows 사용자 환경 변수 이름 |
| site.base_url | 소리튠 조장 사이트 HTTPS 주소 |
| members | real_name, site_name, group_room, communication_room, author_id, absent_confirmed |

site_name은 내부 결과 키이며 real_name은 사이트 행과 매칭한다. group_room은 Slack 표시 이름이다. communication_room과 author_id는 실제 소통방 작성자를 대조한다. 실명이 중복되어 사이트 행이 유일하지 않으면 현재 구현은 차단하므로 사이트 회원 ID 매칭으로 수정 후 검증한다.

## 출처와 이름 확인

사용자가 지정한 Notion 등 명단에서 실명과 두 방의 닉네임을 조회한다. 선택한 소통방의 로컬 메타데이터·작성자 정보를 읽기 전용으로 대조한다. user_dir 아래 chat_data/chatLogs_<room_id>.edb 하나가 제출 근거다. 이전 방의 ID와 매핑을 그대로 복사하지 않는다. 키가 없으면 사용자가 PC에서 소통방을 열어야 한다.

사이트 API는 include_expelled=1로 전체 명단을 확인한다. 실제 담당 명단과 다르면 사용자가 확인한 범위를 기준으로 조회 방식을 조정한다.

## 로그인과 실행 환경

앱 생성부터 연결하는 방법과 Telegram 대체 연결 절차는 [메시지 서비스 연결 안내](messaging.md)를 참고한다.

형식 검증 후 사용자가 로컬 PowerShell에서 setup_slack_bot_token.ps1을 실행하면 가려진 입력으로 토큰을 받아 설정한 사용자 환경 변수에 저장한다. 수신기도 같은 변수를 읽는다. 토큰을 채팅·코드·JSON에 넣지 않는다.

Slack 봇의 chat:write, channels:read, channels:history 권한과 대상 채널 참여를 확인한다. 기존 앱의 chat:write.public은 필요 범위를 확인한다. 비공개 채널의 읽기 scope와 API 접근은 별도 검증한다. 수신기의 --check가 auth.test와 conversations.history를 검사한다.

setup_site_login.ps1로 조장 로그인 번호를 등록한다. 사용자 DPAPI로 암호화한 파일은 `%LOCALAPPDATA%/HamummalCheck/<profile_id>/site_login.dpapi.json`에 저장된다. 새 PC·Windows 사용자에서는 재등록한다. 현재 로그인 방식은 사이트 login_phone API다.

Python·pythonw 경로는 개인 설정과 실제 인터프리터에서 결정한다. 다른 PC에서는 python_executable을 수정한다. 의존성은 프로젝트의 requirements.txt로 설치한다.

## 보관과 GitHub

스킬 폴더 전체를 ZIP이나 Git 저장소로 보관한다. 실제 조별 프로젝트는 별도 위치에 생성한다. 업로드할 파일 목록을 확인하고 vendor/kakao_cli/LICENSE를 유지한다. Git ignore는 이미 추적된 개인 파일까지 제거하지 않는다.

같은 프로젝트를 재개할 때는 전송 기록과 수신기 상태를 유지한다. 새 조는 새 프로젝트와 profile_id를 사용한다. profile_id를 바꾸면 인증 정보와 상태 저장소도 새로 준비한다.
