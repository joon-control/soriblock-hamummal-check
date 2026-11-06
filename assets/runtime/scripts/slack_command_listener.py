"""Receive exact commands in one Slack channel without browser automation.

Only new, top-level human messages are considered. The durable cursor and
command ledger prevent replay after a restart. A separate process lock protects
the existing sender's receipts when scheduled and manual checks overlap.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from local_state import process_lock, write_json
from slack_api_delivery import CHANNEL, KST, WORKSPACE
from quick_check import QuickChecker, LocalQuickRequests


ROOT = Path(__file__).resolve().parent.parent
from runtime_config import CONFIG, START_TIME, FINAL_TIME, FINAL_LABEL, STATE_DIR as PROFILE_STATE
STATE_DIR = PROFILE_STATE / "slack_listener"
COMMANDS = {"시작", "지금체크해줘", "체크해줘", "체크", "check"}
MAX_AGE_SECONDS = 600


class SlackError(RuntimeError):
    def __init__(self, code: str, retry_after: float = 60):
        super().__init__(code)
        self.code = code
        self.retry_after = max(5, retry_after)


def load_token() -> str:
    token = ""
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                token = winreg.QueryValueEx(key, CONFIG["slack"]["token_env"])[0]
        except OSError:
            pass
    token = token or os.environ.get("SLACK_BOT_TOKEN", "")
    if not token.startswith("xoxb-"):
        raise SlackError("bot_token_missing")
    return token


class SlackClient:
    def request(self, method: str, payload: dict, *, read: bool = False) -> dict:
        url = "https://slack.com/api/" + method
        headers = {"Authorization": "Bearer " + load_token()}
        if read:
            url += "?" + urllib.parse.urlencode(payload)
            data = None
        else:
            headers["Content-Type"] = "application/json; charset=utf-8"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method="GET" if read else "POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise SlackError("ratelimited", float(exc.headers.get("Retry-After", "60"))) from exc
            raise SlackError(f"http_{exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise SlackError("network_response_uncertain") from exc
        if not result.get("ok"):
            raise SlackError(str(result.get("error", "invalid_response")))
        return result

    def history(self, oldest: str, latest: str) -> list[dict]:
        messages = []
        cursor = ""
        for _ in range(20):
            params = {"channel": CHANNEL, "oldest": oldest, "latest": latest,
                      "inclusive": "false", "limit": 100}
            if cursor:
                params["cursor"] = cursor
            result = self.request("conversations.history", params, read=True)
            messages.extend(result.get("messages") or [])
            cursor = (result.get("response_metadata") or {}).get("next_cursor", "")
            if not cursor:
                if result.get("has_more"):
                    raise SlackError("history_pagination_incomplete")
                return sorted(messages, key=lambda message: float(message["ts"]))
        raise SlackError("history_backlog_too_large")


def command_text(message: dict, bot_user_id: str) -> str:
    text = str(message.get("text", "")).strip()
    mention = f"<@{bot_user_id}>"
    if text.startswith(mention):
        text = text[len(mention):].strip()
    text = re.sub(r"[.!?。！？]+$", "", text)
    return re.sub(r"\s+", "", text).casefold()


def is_command(message: dict, bot_user_id: str) -> bool:
    if (not message.get("user") or message.get("bot_id") or message.get("subtype")
            or message.get("user") == bot_user_id
            or message.get("team", WORKSPACE) != WORKSPACE
            or message.get("thread_ts", message.get("ts")) != message.get("ts")):
        return False
    return command_text(message, bot_user_id) in COMMANDS


def safe_job_error(output: str) -> str:
    if "ModuleNotFoundError" in output:
        return "점검에 필요한 Python 모듈을 불러오지 못했습니다. 수신기의 실행 환경을 확인해야 합니다."
    if "복호화 키" in output:
        return ("카카오톡 소통방의 복호화 키를 찾지 못했습니다. PC 카카오톡에서 "
                f"‘{CONFIG['kakao']['room_title']}’을 한 번 열어둔 뒤 다시 요청해주세요.")
    if "최신성 부족" in output:
        return "소통방 DB/WAL이 요청 시각까지 갱신되지 않았습니다. 카카오톡 동기화 후 다시 요청해주세요."
    if "명단" in output or "작성자" in output:
        return "조원 명단 또는 작성자 매칭 검증에 실패했습니다. 결과를 추측해 전송하거나 저장하지 않았습니다."
    if "사이트" in output:
        return "최종 점검의 사이트 저장 또는 재조회가 실패했습니다. Slack 게시 여부와 사이트 오류를 작업 로그에서 확인해야 합니다."
    if "중복 전송 방지" in output or "응답을 확인할 수 없음" in output:
        return "Slack 게시 응답이 불확실해 자동 재전송을 멈췄습니다. 채널의 게시 여부를 먼저 확인해주세요."
    return "점검 실행에 실패했습니다. 세부 원인은 PC의 slack_listener 로그에 기록했습니다."


def run_job(mode: str, day: str, as_of: str, thread_ts: str, powershell: str) -> dict:
    script = ROOT / "scripts" / ("run_final_check.ps1" if mode == "final" else "run_slack_api_delivery.ps1")
    args = [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-Date", day, "-ThreadTs", thread_ts]
    if mode != "final":
        args.extend(["-Action", "Send", "-AsOf", as_of])
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    process = subprocess.Popen(args, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        stdout, stderr = process.communicate(timeout=300)
    except subprocess.TimeoutExpired as exc:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            process.kill()
        process.communicate()
        raise RuntimeError("점검 시간이 초과돼 중단했습니다. 게시 여부를 먼저 확인한 뒤 다시 요청해주세요.") from exc
    if process.returncode:
        logging.error("job_failed mode=%s exit=%s reason=%s", mode, process.returncode,
                      re.sub(r"\x1b\[[0-9;]*m", "", stderr or stdout)[-2500:])
        raise RuntimeError(safe_job_error(stderr + stdout))
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("점검 응답 형식을 확인하지 못했습니다. 게시 여부를 먼저 확인해주세요.") from exc


class Listener:
    def __init__(self, client: SlackClient, directory: Path, powershell: str,
                 *, runner=None, now=None, checker=None):
        self.client = client
        self.directory = directory
        self.state_file = directory / "state.json"
        self.powershell = powershell
        self.checker = checker or QuickChecker()
        self.runner = runner or self.run_job
        self.now = now or (lambda: dt.datetime.now(KST))
        if self.state_file.exists():
            self.state = json.loads(self.state_file.read_text(encoding="utf-8"))
            if self.state.get("channel") != CHANNEL or self.state.get("workspace") != WORKSPACE:
                raise RuntimeError("명령 수신 상태 파일의 채널 또는 워크스페이스가 다릅니다.")
        else:
            self.state = {"channel": CHANNEL, "workspace": WORKSPACE,
                          "cursor": f"{self.now().timestamp():.6f}", "commands": {}}
            self.save()
        self.bot_user_id = ""
        self.recovered = False

    def run_job(self, mode, day, as_of, thread_ts, powershell):
        if mode == "quick":
            requested = dt.datetime.fromtimestamp(float(thread_ts), KST)
            return self.checker.run(requested, token=load_token(), thread_ts=thread_ts)
        return run_job(mode, day, as_of, thread_ts, powershell)

    def save(self):
        commands = self.state["commands"]
        for key in sorted(commands, key=float)[:-300]:
            del commands[key]
        write_json(self.state_file, self.state)

    def connect(self):
        identity = self.client.request("auth.test", {})
        if identity.get("team_id") != WORKSPACE:
            raise RuntimeError("Slack 워크스페이스 불일치")
        self.bot_user_id = identity["user_id"]

    def update(self, thread_ts: str, text: str):
        entry = self.state["commands"][thread_ts]
        if entry.get("ack_ts"):
            self.client.request("chat.update", {"channel": CHANNEL, "ts": entry["ack_ts"], "text": text})

    def recover(self):
        if self.recovered:
            return
        for ts, entry in list(self.state["commands"].items()):
            if entry["status"] == "processing":
                entry["status"] = "interrupted"
                self.save()
                self.update(ts, "점검 수신기가 재시작되어 이전 요청의 완료 여부가 불확실합니다. "
                            "Slack 게시 여부를 확인한 뒤 새 메시지로 다시 요청해주세요.")
        self.recovered = True

    def process(self, message: dict):
        ts = message["ts"]
        if float(ts) <= float(self.state["cursor"]):
            return
        self.state["cursor"] = ts
        if not is_command(message, self.bot_user_id) or ts in self.state["commands"]:
            self.save()
            return
        entry = {"status": "processing", "user": message["user"]}
        self.state["commands"][ts] = entry
        self.save()  # No automatic replay after a crash or an uncertain POST.
        now = self.now()
        requested = dt.datetime.fromtimestamp(float(ts), KST)
        age = (now - requested).total_seconds()
        try:
            if requested.date() != now.date() or age > MAX_AGE_SECONDS or age < -5:
                text = "오래된 요청은 자동 실행하지 않았습니다. 새 메시지로 ‘지금 체크해줘’를 보내주세요."
                mode = None
            elif now.time() < START_TIME:
                text = f"오늘 점검은 한국 시간 {START_TIME:%H:%M:%S} 이후 요청할 수 있습니다."
                mode = None
            else:
                mode = ("quick" if command_text(message, self.bot_user_id) in {"체크", "check"}
                        else "final" if now.time() >= FINAL_TIME else "current")
                text = "하멈말 최종 점검을 시작합니다. Slack 게시 후 시스템 저장·재조회까지 확인합니다." if mode == "final" else "소통방 제출을 확인하고 있습니다. 결과를 이 스레드에 보내겠습니다."
            ack = self.client.request("chat.postMessage", {"channel": CHANNEL, "thread_ts": ts,
                    "text": text, "mrkdwn": False, "unfurl_links": False, "unfurl_media": False})
            if ack.get("channel") != CHANNEL or not ack.get("ts"):
                raise RuntimeError("Slack 접수 응답이 불확실해 점검을 실행하지 않았습니다.")
            entry["ack_ts"] = ack["ts"]
            self.save()
            if mode is None:
                entry["status"] = "not_run"
                self.save()
                return
            as_of = FINAL_LABEL if mode == "final" else requested.strftime("%H:%M:%S")
            if mode == "current" and requested.time() < START_TIME:
                raise RuntimeError("요청 시각이 설정된 제출 시작 이전입니다. 새 메시지로 다시 요청해주세요.")
            result = self.runner(mode, now.date().isoformat(), as_of, ts, self.powershell)
            slack = result["slack"] if mode == "final" else result
            if not (slack.get("sent") or slack.get("already_sent")) or not slack.get("permalink"):
                raise RuntimeError("Slack 게시 성공을 확인하지 못했습니다.")
            as_of = slack.get("as_of", as_of)
            summary = f"{now:%Y-%m-%d} {as_of} 기준 확인 완료: 완료 {slack['completed_count']}명, 미완료 {slack['missing_count']}명."
            if mode == "quick":
                duration = (self.now() - requested).total_seconds()
                summary += f" 요청부터 결과 확인까지 {duration:.2f}초."
                lag = float(slack.get("source_lag_seconds", 0))
                if lag >= 1:
                    summary += f" PC 자료는 요청보다 {lag:.0f}초 앞선 시각 기준입니다."
            if mode == "final":
                site = result["site"]
                if not site.get("verified_after_save"):
                    raise RuntimeError("사이트 저장 후 재조회가 확인되지 않았습니다.")
                summary += f" 시스템 체크 {site['completed_count']}명 저장·재조회 완료."
            summary += "\n결과: " + slack["permalink"]
            entry.update({"status": "completed", "mode": mode, "as_of": as_of,
                          "result_link": slack["permalink"]})
            self.save()
            try:
                self.update(ts, summary)
            except (RuntimeError, OSError):
                # A status edit failure must not misreport a successful post or
                # re-run a completed check. The result link remains durable.
                logging.error("completion_reply_unconfirmed ts=%s", ts)
            logging.info("command_completed ts=%s mode=%s", ts, mode)
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            entry["status"] = "failed"
            self.save()
            logging.error("command_failed ts=%s reason=%s", ts, str(exc))
            try:
                self.update(ts, "점검을 완료하지 못했습니다.\n" + str(exc))
            except (RuntimeError, OSError):
                logging.error("failure_reply_unconfirmed ts=%s", ts)

    def poll(self):
        if not self.bot_user_id:
            self.connect()
        messages = self.client.history(self.state["cursor"], f"{self.now().timestamp():.6f}")
        self.recover()
        for message in messages:
            self.process(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Check API permissions without posting or running a check")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    args = parser.parse_args()
    args.state_dir.mkdir(parents=True, exist_ok=True)
    config_file = args.state_dir / "config.json"
    config = json.loads(config_file.read_text(encoding="utf-8-sig")) if config_file.exists() else {}
    powershell = config.get("powershell", "pwsh.exe")
    client = SlackClient()
    if args.check:
        identity = client.request("auth.test", {})
        if identity.get("team_id") != WORKSPACE:
            raise RuntimeError("Slack 워크스페이스 불일치")
        client.request("conversations.history", {"channel": CHANNEL, "limit": 1}, read=True)
        print(json.dumps({"ready": True, "channel": CHANNEL, "bot_user_id": identity["user_id"]}))
        return
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[RotatingFileHandler(args.state_dir / "listener.log", maxBytes=1_000_000,
                                                      backupCount=3, encoding="utf-8")])
    with process_lock(args.state_dir / "listener.lock", timeout=0):
        checker = QuickChecker()
        write_json(args.state_dir / "status.json", {"state": "warming_key", "pid": os.getpid(),
                   "checked_at": dt.datetime.now(KST).isoformat()})
        try:
            checker.key()
        except (RuntimeError, OSError, ValueError) as exc:
            logging.warning("key_warmup_unavailable reason=%s", str(exc))
        listener = Listener(client, args.state_dir, powershell, checker=checker)
        local_requests = LocalQuickRequests(args.state_dir / "quick_requests", checker, load_token)
        last_error = None
        while True:
            delay = max(5, float(config.get("poll_seconds", 5)))
            try:
                local_requests.poll()
                listener.poll()
                status = {"state": "listening", "channel": CHANNEL,
                          "key_ready": checker._key is not None}
                last_error = None
            except (RuntimeError, OSError, ValueError, KeyError) as exc:
                code = str(exc)
                state = "waiting_for_scope" if code == "missing_scope" else "waiting_for_connection"
                status = {"state": state, "channel": CHANNEL, "error": code}
                if code != last_error:
                    logging.error("listener_unavailable reason=%s", code)
                    last_error = code
                listener.bot_user_id = ""  # Re-read updated user environment token on reconnect.
                delay = exc.retry_after if isinstance(exc, SlackError) else 60
            status.update({"pid": os.getpid(), "checked_at": dt.datetime.now(KST).isoformat()})
            write_json(args.state_dir / "status.json", status)
            if args.once:
                print(json.dumps(status, ensure_ascii=False))
                return
            time.sleep(delay)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"ready": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
