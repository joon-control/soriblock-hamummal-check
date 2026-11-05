"""Voice detection and committed WAL snapshots shared by the room reader."""
import datetime as dt
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor/kakao_cli"))
from kwin.sqlcipher_v4 import decrypt_bytes, decrypt_page
from runtime_config import MEMBERS, KST, TITLE


PAGE_SIZE = 4096
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac", ".opus", ".wma")
ROSTER = {index: member["site_name"] for index, member in enumerate(MEMBERS)}


def notion_roster():
    return dict(enumerate(MEMBERS))


def slack_message(completed, missing, cutoff, *, final=False):
    lines = [f"{index}.{name}" for index, name in enumerate(completed, 1)] or ["없음"]
    if final:
        return "\n".join([
            f"🔥 {TITLE} 최종본 {cutoff:%Y-%m-%d}",
            "",
            f"✅ 완료 ({len(completed)}명)",
            *lines,
        ])
    label = cutoff.strftime("%H:%M:%S" if cutoff.second else "%H:%M")
    missing_lines = [f"@{name}" for name in missing] or ["없음"]
    return "\n".join([
        f"🔥 {TITLE} 체크 {label} 기준",
        f"✅ 완료 ({len(completed)}명)",
        *lines,
        "",
        f"⏳ 미완료 ({len(missing)}명)",
        *missing_lines,
    ])


def decode(value):
    if isinstance(value, bytes):
        for encoding in ("utf-8", "cp949", "euc-kr"):
            try:
                return value.decode(encoding)
            except UnicodeDecodeError:
                pass
        return value.decode("utf-8", "replace")
    return value or ""

def is_audio(message, attachment, kind):
    body = str(decode(message)).strip()
    try:
        metadata = json.loads(decode(attachment) or "{}")
    except (TypeError, json.JSONDecodeError):
        metadata = {}
    names = []
    if isinstance(metadata, dict):
        names.extend(str(metadata.get(key) or "") for key in ("name", "filename", "fileName", "path"))
        url_path = urlsplit(str(metadata.get("url") or "").replace("\\/", "/")).path
        names.append(url_path)
        mime = str(metadata.get("type") or metadata.get("mimeType") or "").lower()
        if mime.startswith("audio/"):
            return True
        if any(name.lower().endswith(AUDIO_EXTENSIONS) for name in names):
            return True
    if body.replace(" ", "") in ("음성메시지", "음성메세지"):
        return True
    return kind == 18 and body.lower().endswith(AUDIO_EXTENSIONS)

def plaintext_snapshot(encrypted_db: Path, key: bytes) -> bytes:
    plain = bytearray(decrypt_bytes(encrypted_db.read_bytes(), key))
    if not plain.startswith(b"SQLite format 3\0"):
        raise RuntimeError("소통방 DB 복호화 검증 실패")

    wal = encrypted_db.with_name(encrypted_db.name + "-wal")
    if not wal.exists() or wal.stat().st_size <= 32:
        return bytes(plain)
    raw = wal.read_bytes()
    if len(raw) < 32 or int.from_bytes(raw[8:12], "big") not in (0, PAGE_SIZE):
        raise RuntimeError("카카오톡 WAL 형식을 확인할 수 없어 최신 메시지 판정을 중단함")
    frame_size = 24 + PAGE_SIZE
    frames = []
    for offset in range(32, len(raw) - frame_size + 1, frame_size):
        header = raw[offset : offset + 24]
        if header[8:16] != raw[16:24]:
            break
        page_no = int.from_bytes(header[0:4], "big")
        db_pages = int.from_bytes(header[4:8], "big")
        if page_no <= 0:
            break
        frames.append((page_no, db_pages, raw[offset + 24 : offset + frame_size]))
    last_commit = max((i for i, frame in enumerate(frames) if frame[1] > 0), default=-1)
    if last_commit < 0:
        raise RuntimeError("커밋되지 않은 WAL이 있어 최신 메시지 판정을 중단함")
    for page_no, _, page in frames[: last_commit + 1]:
        begin = (page_no - 1) * PAGE_SIZE
        if len(plain) < begin + PAGE_SIZE:
            plain.extend(b"\0" * (begin + PAGE_SIZE - len(plain)))
        plain[begin : begin + PAGE_SIZE] = decrypt_page(page, key, page_no)
    db_pages = frames[last_commit][1]
    return bytes(plain[: db_pages * PAGE_SIZE])
