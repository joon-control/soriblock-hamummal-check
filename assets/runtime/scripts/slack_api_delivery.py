"""Deliver a validated first-day report to Slack through its Web API.

The token comes from the wrapper's short-lived environment variable. A local
receipt prevents a second POST after success or an ambiguous network failure.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from local_state import process_lock


from runtime_config import CONFIG, MEMBER_COUNT, FINAL_TIME, TITLE, STATE_DIR, KST
CHANNEL = CONFIG["slack"]["channel_id"]
WORKSPACE = CONFIG["slack"]["workspace_id"]
RECEIPTS = STATE_DIR / "slack_delivery_receipts.json"


def api(method: str, payload: dict, token: str) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            answer = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Slack {method} 응답을 확인할 수 없음: {type(exc).__name__}") from exc
    if not answer.get("ok"):
        raise RuntimeError(f"Slack {method} 실패: {answer.get('error', 'unknown_error')}")
    return answer


def load_receipts() -> dict:
    if not RECEIPTS.exists():
        return {}
    with RECEIPTS.open(encoding="utf-8") as file:
        result = json.load(file)
    if not isinstance(result, dict):
        raise RuntimeError("Slack 전송 기록 형식 오류")
    return result


def save_receipts(receipts: dict) -> None:
    RECEIPTS.parent.mkdir(parents=True, exist_ok=True)
    temporary = RECEIPTS.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(receipts, file, ensure_ascii=False, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(RECEIPTS)


def message_permalink(channel: str, ts: str, token: str, workspace_url: str) -> str:
    try:
        return api("chat.getPermalink", {"channel": channel, "message_ts": ts}, token)["permalink"]
    except (RuntimeError, KeyError):
        # auth.test reports the current address even after a workspace rename.
        parsed = urllib.parse.urlsplit(workspace_url)
        if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".slack.com"):
            raise RuntimeError("Slack 게시 링크에 사용할 현재 워크스페이스 URL을 확인할 수 없음")
        return f"https://{parsed.netloc}/archives/{channel}/p{ts.replace('.', '')}"


def validated_report(as_of: str, day: dt.date, *, reporter=None) -> dict:
    from check_communication_room import report

    label_time = dt.datetime.fromisoformat(f"{day.isoformat()}T{as_of}").replace(tzinfo=KST)
    # A checkpoint named 13:40/13:50 covers its whole displayed minute.
    cutoff = (label_time.replace(second=59)
              if as_of in CONFIG["whole_minute_checkpoints"]
              else label_time)
    if dt.datetime.now(KST) < cutoff:
        raise RuntimeError("점검 시각이 아직 되지 않았거나 범위를 벗어남")
    result = (reporter or report)(cutoff, label_time=label_time)
    if result["room"] != CONFIG["kakao"]["room_title"]:
        raise RuntimeError("카카오톡 소통방 출처 불일치")
    completed, missing = result["completed"], result["missing"]
    if len(completed) + len(missing) != MEMBER_COUNT or set(completed) & set(missing):
        raise RuntimeError("완료/미완료 명단 검증 실패")
    if len(result["audio_evidence"]) < len(completed):
        raise RuntimeError("완료자 음성 증거 부족")
    last_write = max(
        dt.datetime.fromisoformat(value)
        for value in (result["source_last_write"], result["wal_last_write"])
        if value
    )
    if last_write < cutoff:
        raise RuntimeError(f"소통방 DB/WAL 최신성 부족: 마지막 기록 {last_write.isoformat()}")
    time_label = label_time.strftime("%H:%M:%S" if label_time.second else "%H:%M")
    expected_title = (f"🔥 {TITLE} 최종본 {cutoff:%Y-%m-%d}"
                      if cutoff.time() == FINAL_TIME
                      else f"🔥 {TITLE} 체크 {time_label} 기준")
    if not result["slack_message"].startswith(expected_title + "\n"):
        raise RuntimeError("Slack 메시지 제목 검증 실패")
    if cutoff.time() == FINAL_TIME and "미완료" in result["slack_message"]:
        raise RuntimeError("최종 메시지에 미완료 목록이 포함됨")
    return result


def _main(argv=None, *, report_loader=None, token=None) -> None:
    report_loader = report_loader or validated_report
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--connection", action="store_true")
    action.add_argument("--preview", action="store_true")
    action.add_argument("--test-send", action="store_true")
    action.add_argument("--send", action="store_true")
    parser.add_argument("--as-of")
    parser.add_argument("--date", default=dt.datetime.now(KST).date().isoformat())
    parser.add_argument("--resend-id")
    parser.add_argument("--thread-ts")
    args = parser.parse_args(argv)
    if args.thread_ts and not re.fullmatch(r"\d+\.\d+", args.thread_ts):
        parser.error("--thread-ts must be a Slack message timestamp")

    if (args.preview or args.send) and not args.as_of:
        parser.error("--preview/--send requires --as-of")
    try:
        day = dt.date.fromisoformat(args.date)
        if args.as_of:
            dt.time.fromisoformat(args.as_of)
    except ValueError:
        parser.error("--date must be YYYY-MM-DD and --as-of must be HH:MM[:SS]")
    if args.resend_id and (not args.send or not args.resend_id.replace("-", "").replace("_", "").isalnum()):
        parser.error("--resend-id requires --send and letters, numbers, '-' or '_'")

    if (args.preview or args.send) and args.as_of in CONFIG["whole_minute_checkpoints"]:
        end_of_minute = dt.datetime.combine(day, dt.time.fromisoformat(args.as_of), KST).replace(second=59)
        seconds_to_wait = (end_of_minute + dt.timedelta(seconds=1) - dt.datetime.now(KST)).total_seconds()
        if seconds_to_wait > 61:
            raise RuntimeError("점검 시각이 아직 되지 않음")
        if seconds_to_wait > 0:
            time.sleep(seconds_to_wait)

    if args.preview:
        result = report_loader(args.as_of, day)
        print(json.dumps({"completed": result["completed"], "missing": result["missing"],
                          "slack_message": result["slack_message"]}, ensure_ascii=False, indent=2))
        return

    token = token if token is not None else os.environ.get("SLACK_BOT_TOKEN", "")
    if not token.startswith("xoxb-"):
        raise RuntimeError("Slack 봇 토큰이 설정되지 않았거나 xoxb- 형식이 아님")
    identity = api("auth.test", {}, token)
    if identity.get("team_id") != WORKSPACE:
        raise RuntimeError(f"Slack 워크스페이스 불일치: {identity.get('team_id')}")
    if args.connection:
        print(json.dumps({"connected": True, "team_id": identity["team_id"],
                          "bot_id": identity.get("bot_id"), "channel": CHANNEL}, ensure_ascii=False))
        return

    key = (f"{day.isoformat()}/{args.as_of}/{CHANNEL}"
           + (f"/resend/{args.resend_id}" if args.resend_id else "") if args.send
           else f"{day.isoformat()}/api-test/{CHANNEL}")
    receipts = load_receipts()
    if key in receipts:
        receipt = receipts[key]
        if receipt.get("state") == "sent" and args.send:
            # Reuse the exact roster that was actually posted. Re-reading a
            # mutable DB must not silently change the site checks on a retry.
            result = receipt.get("snapshot") or report_loader(args.as_of, day)
            workspace_url = identity.get("url", "")
            current_host = urllib.parse.urlsplit(workspace_url).hostname
            saved_host = urllib.parse.urlsplit(receipt.get("permalink", "")).hostname
            if not receipt.get("permalink") or (current_host and saved_host != current_host):
                receipt["permalink"] = message_permalink(receipt.get("channel", CHANNEL), receipt["ts"], token, workspace_url)
                save_receipts(receipts)
            print(json.dumps({"sent": False, "already_sent": True,
                              "channel": receipt.get("channel", CHANNEL),
                              "ts": receipt.get("ts"),
                              "permalink": receipt.get("permalink"),
                              "date": day.isoformat(), "as_of": args.as_of,
                              "completed_count": len(result["completed"]),
                              "missing_count": len(result["missing"]),
                              "completed": result["completed"],
                              "missing": result["missing"]}, ensure_ascii=False))
            return
        raise RuntimeError(f"중복 전송 방지: {key} 상태={receipt.get('state')} "
                           f"링크={receipt.get('permalink', '없음')}")
    if args.send:
        result = report_loader(args.as_of, day)
        message = result["slack_message"]
    else:
        message = f"[테스트] {TITLE} 체크 · Slack API 전송 확인\n자동 전송 연결을 확인하는 메시지입니다."
    receipts[key] = {"state": "attempting", "created_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    if args.send:
        receipts[key]["snapshot"] = {"completed": result["completed"], "missing": result["missing"]}
    if args.thread_ts:
        receipts[key]["thread_ts"] = args.thread_ts
    save_receipts(receipts)

    payload = {
        "channel": CHANNEL,
        "text": message,
        "mrkdwn": False,
        "link_names": False,
        "unfurl_links": False,
        "unfurl_media": False,
    }
    if args.thread_ts:
        payload["thread_ts"] = args.thread_ts
    posted = api("chat.postMessage", payload, token)
    channel, ts = posted.get("channel"), posted.get("ts")
    if channel != CHANNEL or not ts:
        raise RuntimeError("Slack 전송 응답에 채널 또는 ts가 없어 게시 여부 확인 필요")
    receipts[key].update({"state": "sent", "channel": channel, "ts": ts})
    save_receipts(receipts)
    link = message_permalink(channel, ts, token, identity.get("url", ""))
    receipts[key]["permalink"] = link
    save_receipts(receipts)
    summary = {"sent": True, "channel": channel, "ts": ts, "permalink": link}
    if args.send:
        summary.update({"date": day.isoformat(), "as_of": args.as_of,
                        "completed_count": len(result["completed"]),
                        "missing_count": len(result["missing"]),
                        "completed": result["completed"],
                        "missing": result["missing"]})
    print(json.dumps(summary, ensure_ascii=False))


def main(argv=None, *, report_loader=None, token=None) -> None:
    options = argv if argv is not None else sys.argv[1:]
    if "--preview" in options or "--connection" in options:
        _main(argv, report_loader=report_loader, token=token)
    else:
        # Manual Slack commands and scheduled checks share one receipt file.
        with process_lock(RECEIPTS.with_suffix(".lock")):
            _main(argv, report_loader=report_loader, token=token)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        raise SystemExit(1)
