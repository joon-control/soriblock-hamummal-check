# 하멈말 체크 스킬

새 기수와 조의 카카오톡 음성 제출을 확인하고 Slack 보고와 소리튠 조장 체크리스트 반영을 설정하는 Codex 스킬입니다.

## 포함된 기능

- 기수, 조원, 소통방, Slack 채널과 점검 시간을 조별 설정 파일로 관리합니다.
- 선택한 소통방의 로컬 DB와 커밋된 WAL에서 음성 제출을 검증합니다.
- Slack API로 중간 보고와 첫 제출 순서의 최종본을 게시합니다.
- 최종본 게시를 확인한 후 완료자의 하멈말 체크를 저장하고 재조회합니다.
- 요청하면 Slack의 점검 명령을 받는 숨김 Windows 수신기를 설치합니다.
- `체크` 또는 `check` 요청은 고정 진입점으로 바로 실행하고, 상주 프로세스가 검증한 복호화 키를 RAM에서 재사용합니다.

Telegram 봇 연결 절차는 안내서에 있습니다. 현재 실행 코드는 Slack용이며 Telegram 전송과 명령 수신은 추가 구현이 필요합니다.

## 사용

이 저장소의 파일을 `~/.codex/skills/hamummal-check/`에 설치하고 Codex에서 다음과 같이 요청합니다.

> $hamummal-check 새 기수와 조의 하멈말 점검을 설정하고 미리보기부터 검증해줘.

스킬은 별도의 조별 프로젝트를 생성합니다. 새 명단, 실제 소통방의 작성자 ID, Slack 목적지와 시간을 확인하고 연결 및 제출 미리보기를 검증합니다. Python과 PowerShell 실행 환경 및 개인 인증 정보도 준비합니다.

설정과 상주 수신기 준비가 끝나면 `체크` 또는 `check`라고 요청합니다. 처리 시간과 실제 자료 기준 시각을 결과에서 확인할 수 있습니다. 첫 키 준비와 카카오톡 재시작 뒤 재탐색에는 시간이 추가됩니다.

- [스킬 지시문](SKILL.md)
- [새 조 설정 안내](references/setup.md)
- [Slack·Telegram 연결 방법](references/messaging.md)
- [실행과 중지 절차](references/operations.md)
- [가상 설정 예시](assets/runtime/config.example.json)

## 실행 조건

Windows, Python 3.12 이상, PowerShell 7을 사용합니다. 의존성은 조별 프로젝트의 requirements.txt로 설치합니다. 카카오톡이 실행되고 소통방이 동기화되어 있어야 합니다. 복호화 키가 메모리에 없으면 PC에서 소통방을 열어야 합니다. 사이트 API나 DB 형식이 변경되면 재검증합니다.

## 개인 설정

저장소에는 일반 실행 코드와 가상 명단을 포함합니다. 실제 토큰은 사용자의 Windows 환경 변수, 사이트 로그인은 사용자 DPAPI 저장소에서 관리합니다. 실제 조별 config.local.json, 명단, DB, 키, 상태 기록과 로그는 개인 프로젝트와 사용자 저장소에 둡니다.

복호화 모듈의 원본 라이선스는 [vendor 라이선스](assets/runtime/vendor/kakao_cli/LICENSE)에 있습니다.

## 검증

Windows에서 `python tests/test_runtime.py`로 가상 조와 대체 API를 사용하는 회귀 검증을 실행할 수 있습니다.
