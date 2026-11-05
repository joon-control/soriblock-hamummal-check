"""Read only the configured bootcamp communication room for 하멈말 submissions.

The raw SQLCipher key and decrypted DB remain in memory. No Kakao UI is used.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor" / "kakao_cli"))
from kwin import cli, decryptor, memkey, sqlcipher_v4

from check_common import KST, ROSTER, is_audio, notion_roster, plaintext_snapshot, slack_message
from runtime_config import CONFIG, MEMBERS, START_TIME, FINAL_TIME


ROOM_ID = int(CONFIG["kakao"]["room_id"])
ROOM_TITLE = CONFIG["kakao"]["room_title"]
USER_DIR = Path(CONFIG["kakao"]["user_dir"])
SOURCE = USER_DIR / "chat_data" / f"chatLogs_{ROOM_ID}.edb"
COMMUNICATION_AUTHORS = {m["site_name"]: int(m["author_id"]) if m["author_id"] is not None else None for m in MEMBERS}


def recover_key() -> bytes:
    first_page = decryptor.first_page(str(SOURCE))
    for pid in memkey.find_pids():
        regions = cli._read_process_regions(pid)
        codecs = cli._codec_contexts_from_regions(regions)
        for candidate in cli._candidate_v2_keys_from_codecs(regions, codecs):
            key = candidate["key"]
            if sqlcipher_v4.try_raw_key(first_page, key):
                return key
    raise RuntimeError("소통방 DB 복호화 키를 KakaoTalk 프로세스에서 찾지 못함")


def report(cutoff: dt.datetime, *, label_time: dt.datetime | None = None) -> dict:
    start = dt.datetime.combine(cutoff.date(), START_TIME, KST)
    end = dt.datetime.combine(cutoff.date(), FINAL_TIME, KST) - dt.timedelta(seconds=1)
    if cutoff < start or cutoff > end + dt.timedelta(seconds=1):
        raise RuntimeError("점검 시각은 설정한 제출 시간 범위여야 함")
    if not SOURCE.exists():
        raise RuntimeError("소통방 DB 없음")
    members = notion_roster()
    if set(members) != set(ROSTER):
        raise RuntimeError("조원 명단 불일치")
    if set(COMMUNICATION_AUTHORS) != {item["site_name"] for item in members.values()}:
        raise RuntimeError("소통방 작성자 매핑과 Notion 명단 불일치")
    valid_ids = [uid for uid in COMMUNICATION_AUTHORS.values() if uid is not None]
    if len(valid_ids) != len(set(valid_ids)) or len(valid_ids) != sum(m["author_id"] is not None for m in MEMBERS):
        raise RuntimeError("소통방 작성자 ID 중복 또는 인원 불일치")
    plain = bytearray(plaintext_snapshot(SOURCE, recover_key()))
    plain[18:20] = b"\x01\x01"
    connection = sqlite3.connect(":memory:")
    connection.deserialize(bytes(plain))
    try:
        if connection.execute("pragma quick_check").fetchone()[0] != "ok":
            raise RuntimeError("소통방 DB 무결성 검사 실패")
        rows = connection.execute(
            """SELECT logId, authorId, type, sendAt, message, attachement
               FROM chatLogs WHERE sendAt BETWEEN ? AND ? AND deleted=0
               ORDER BY sendAt, logId""",
            (int(start.timestamp()), int(min(cutoff, end).timestamp())),
        ).fetchall()
    finally:
        connection.close()
    author_to_site = {uid: name for name, uid in COMMUNICATION_AUTHORS.items() if uid is not None}
    found: dict[str, list] = {}
    evidence = []
    for log_id, author_id, kind, sent_at, message, attachment in rows:
        audio = is_audio(message, attachment, kind)
        if author_id in author_to_site and kind == 5 and not audio:
            sent = dt.datetime.fromtimestamp(sent_at, KST).isoformat(timespec="seconds")
            raise RuntimeError(
                f"조원 음성 메시지 형식을 판별할 수 없음: {author_to_site[author_id]} "
                f"{sent} logId={log_id}"
            )
        if audio:
            item = {"author_id": author_id, "time": dt.datetime.fromtimestamp(sent_at, KST).isoformat(timespec="seconds"),
                    "log_id": log_id, "type": kind, "site_name": author_to_site.get(author_id)}
            evidence.append(item)
            if author_id in author_to_site:
                found.setdefault(author_to_site[author_id], []).append(item)
    by_site = {item["site_name"]: item for item in members.values()}
    final = cutoff.time() == FINAL_TIME
    # Each person's first audio message determines their position in the final report.
    completed = (sorted(found, key=lambda name: (found[name][0]["time"], found[name][0]["log_id"]))
                 if final else sorted(found, key=str.casefold))
    missing = sorted((name for name in by_site if name not in found), key=str.casefold)
    completed_room = [by_site[name]["group_room"] for name in completed]
    if not final:
        completed_room.sort(key=str.casefold)
    missing_room = sorted((by_site[name]["group_room"] for name in missing), key=str.casefold)
    return {"room": ROOM_TITLE, "checked_through": cutoff.isoformat(timespec="seconds"),
            "source_last_write": dt.datetime.fromtimestamp(SOURCE.stat().st_mtime, KST).isoformat(timespec="seconds"),
            "wal_last_write": dt.datetime.fromtimestamp(SOURCE.with_name(SOURCE.name + "-wal").stat().st_mtime, KST).isoformat(timespec="seconds")
            if SOURCE.with_name(SOURCE.name + "-wal").exists() else None,
            "completed": completed, "missing": missing,
            "slack_message": slack_message(completed_room, missing_room, label_time or cutoff, final=final),
            "audio_evidence": [item for item in evidence if item["site_name"]],
            "messages_in_window": len(rows), "all_audio_messages_in_window": len(evidence)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--date", default=dt.datetime.now(KST).date().isoformat())
    args = parser.parse_args()
    cutoff = dt.datetime.fromisoformat(f"{args.date}T{args.as_of}").replace(tzinfo=KST)
    if dt.datetime.now(KST) < cutoff:
        raise SystemExit("점검 시각이 아직 되지 않았거나 범위를 벗어남")
    print(json.dumps(report(cutoff), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
