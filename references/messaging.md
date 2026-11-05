# Slack과 Telegram 연결

현재 번들 실행 코드는 Slack을 지원한다. Telegram은 아래 절차로 봇을 준비할 수 있으며, 실제 점검 보고·명령 수신·최종 사이트 저장에 연결하려면 Telegram 전송기를 구현하고 검증해야 한다. 제공된 Slack 래퍼를 Telegram용으로 호출하지 않는다.

## Slack

1. Slack 앱 관리 페이지에서 사용할 앱과 워크스페이스를 선택하거나 새 앱을 만든다.
2. OAuth & Permissions의 Bot Token Scopes에 chat:write를 추가한다. 공개 채널 조회에는 channels:read, 채널에서 점검 명령을 받으려면 channels:history도 추가한다.
3. Install to Workspace 또는 Reinstall to Workspace를 누르고 권한을 승인한다. Bot User OAuth Token은 사용자가 로컬에서 보관한다.
4. 결과를 보낼 채널에 봇을 초대한다. 워크스페이스와 채널 ID를 config.local.json의 slack 항목에 기록한다. 이름이나 URL을 ID 대신 넣지 않는다.
5. slack.token_env를 정하고 scripts/setup_slack_bot_token.ps1을 로컬 터미널에서 실행해 토큰을 입력한다. 토큰은 설정한 Windows 사용자 환경 변수에 저장된다.
6. run_slack_api_delivery.ps1 -Action Connection으로 인증·워크스페이스를 확인한다. 명령 수신이 필요하면 slack_command_listener.py --check로 읽기 권한도 확인한다.
7. Preview로 제출 판정을 검증한다. 승인된 테스트 메시지와 실제 게시 확인 후 요청된 예약·수신기를 활성화한다.

비공개 채널을 쓰는 경우 해당 대화 유형의 읽기 scope와 봇 참여를 추가로 검증한다.

공식 근거는 [앱 생성과 설치](https://docs.slack.dev/app-management/quickstart-app-settings/)와 [채널 메시지 읽기](https://docs.slack.dev/messaging/retrieving-messages/)에 있다.

## Telegram

1. Telegram의 공식 @BotFather에서 /newbot으로 봇을 만들고 받은 토큰을 로컬 사용자 환경 변수에 저장한다. 새 예시 변수명은 HAMUMMAL_TELEGRAM_TOKEN으로 사용할 수 있다.
2. 개인 대화로 받을 경우 사용자가 새 봇과 대화를 열고 /start를 보낸다. 그룹으로 받을 경우 봇을 그룹에 추가하고 봇을 대상으로 한 명령 메시지를 보낸다.
3. getMe로 토큰을 검증하고 getUpdates에서 자신이 보낸 메시지의 message.chat.id를 확인한다. 목적지 chat_id는 개인 설정에 문자열로 기록한다. 실제 토큰이 들어간 요청 URL을 채팅·로그·Git에 남기지 않는다.
4. sendMessage에 chat_id와 text를 보내 테스트한다. 성공 응답의 ok와 result.chat.id, result.message_id를 확인한다.
5. 점검 호출용 getUpdates 수신기를 구현할 때는 허용된 chat_id와 사용자 범위를 정한다. update_id를 저장해 재시작 후 중복 실행을 막고, 그룹의 privacy mode에 맞춰 /check 등 봇 명령을 사용한다.
6. 기존 봇이면 getWebhookInfo로 webhook 사용 여부를 먼저 확인한다. webhook과 getUpdates는 동시에 사용할 수 없다. 기존 연동 변경은 사용자 요청 범위에서 진행한다.

Telegram 어댑터 구현 때는 현재 판정 코드와 메시지 형식을 재사용한다. 전송 기록을 플랫폼·profile·날짜·cutoff·chat_id별로 구분하고, 게시 전 attempting과 게시 당시 명단 snapshot을 저장한다. 불확실한 전송 응답은 확인 후 처리한다. 최종 사이트 저장은 Telegram 게시 성공을 확인한 뒤 실행하도록 별도 진입점을 구성한다. Slack 전송을 강제로 실행하거나 Slack 게시 링크 검증을 생략하는 방식으로 우회하지 않는다.

공식 근거는 [BotFather 시작 안내](https://core.telegram.org/bots/tutorial), [Bot API](https://core.telegram.org/bots/api), [그룹 privacy mode](https://core.telegram.org/bots/features#privacy-mode)에 있다.

## 개인 정보와 배포 파일

스킬에는 일반 API 호출 코드, 환경 변수 이름과 가상 설정 예시를 보관한다. 실제 토큰, 목적지 ID, 실제 명단, 사이트 로그인, 개인 PC 경로는 사용자의 조별 설정과 운영 저장소에서 관리한다. config.local.json과 DPAPI 파일을 Git에 추가하지 않는다.

현재 PC에서 동작 중인 기존 봇의 자격 증명은 개인 저장소에 유지된다. 배포 ZIP에서 제거했다는 사실이 PC의 토큰을 삭제했다는 뜻은 아니다.
