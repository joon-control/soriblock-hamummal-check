"""Load one team's private settings and reject incomplete author mappings."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
KST = dt.timezone(dt.timedelta(hours=9))


def load_config(path: Path | None = None, *, require_verified: bool = True) -> dict:
    path = path or ROOT / "config.local.json"
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if config.get("schema_version") != 1:
        raise ValueError("지원하는 설정 버전은 1입니다.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", config["profile_id"]):
        raise ValueError("profile_id는 영문 소문자, 숫자, 하이픈으로 지정합니다.")
    for key in ("cohort", "group", "mission"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"{key} 설정이 필요합니다.")
    start = dt.time.fromisoformat(config["window_start"])
    final = dt.time.fromisoformat(config["final_time"])
    if start >= final or final.microsecond or start.microsecond:
        raise ValueError("당일 시작 시각과 최종 시각의 순서를 확인해주세요.")
    checkpoints = config["whole_minute_checkpoints"]
    if not isinstance(checkpoints, list) or len(set(checkpoints)) != len(checkpoints):
        raise ValueError("중간 점검 시각 목록이 중복되었습니다.")
    for checkpoint in checkpoints:
        if not re.fullmatch(r"\d{2}:\d{2}", checkpoint):
            raise ValueError("분 전체 점검 시각은 HH:MM 형식입니다.")
        end = dt.time.fromisoformat(checkpoint).replace(second=59)
        if not start <= end < final:
            raise ValueError("중간 점검 시각이 제출 시간 범위를 벗어납니다.")
    kakao = config["kakao"]
    if not isinstance(kakao["room_id"], str) or not kakao["room_id"].isdigit():
        raise ValueError("방 ID는 정수 손실을 피하도록 숫자 문자열로 저장합니다.")
    if not kakao["room_title"].strip() or not kakao["user_dir"].strip():
        raise ValueError("소통방 제목과 Kakao 사용자 폴더가 필요합니다.")
    slack = config["slack"]
    if not re.fullmatch(r"T[A-Z0-9]+", slack["workspace_id"]):
        raise ValueError("Slack 워크스페이스 ID가 필요합니다.")
    if not re.fullmatch(r"[CG][A-Z0-9]+", slack["channel_id"]):
        raise ValueError("Slack 채널 ID가 필요합니다.")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", slack["token_env"]):
        raise ValueError("Slack 토큰 환경 변수 이름을 확인해주세요.")
    if urlsplit(config["site"]["base_url"]).scheme != "https":
        raise ValueError("사이트 주소는 HTTPS를 사용합니다.")
    members = config["members"]
    count = config["expected_member_count"]
    if type(count) is not int or count < 1 or not isinstance(members, list) or len(members) != count:
        raise ValueError("기준 인원수와 명단 수가 다릅니다.")
    for field in ("real_name", "site_name", "group_room"):
        values = [member.get(field) for member in members]
        if any(not isinstance(value, str) or not value.strip() for value in values) or len(set(values)) != count:
            raise ValueError(f"명단의 {field} 값이 없거나 중복되었습니다.")
    authors = []
    for member in members:
        author = member.get("author_id")
        if author is None:
            if member.get("absent_confirmed") is not True:
                raise ValueError("작성자 ID가 없는 사람은 소통방 부재를 확인해야 합니다.")
        else:
            if not isinstance(author, str) or not author.isdigit() or not 0 < int(author) < 2**63:
                raise ValueError("작성자 ID는 양의 정수 문자열로 저장합니다.")
            if not isinstance(member.get("communication_room"), str) or not member["communication_room"].strip():
                raise ValueError("소통방 표시 이름을 확인해주세요.")
            authors.append(author)
    if len(authors) != len(set(authors)):
        raise ValueError("소통방 작성자 ID가 중복되었습니다.")
    if require_verified and (config.get("source_verified") is not True or config.get("mapping_verified") is not True):
        raise ValueError("소통방 출처와 전체 명단 매칭을 먼저 검증해야 합니다.")
    return config


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    print(json.dumps({"valid": True, "member_count": len(config["members"]), "profile_id": config["profile_id"]}))
else:
    CONFIG = load_config()
    MEMBERS = CONFIG["members"]
    MEMBER_COUNT = len(MEMBERS)
    START_TIME = dt.time.fromisoformat(CONFIG["window_start"])
    FINAL_TIME = dt.time.fromisoformat(CONFIG["final_time"])
    FINAL_LABEL = FINAL_TIME.isoformat(timespec="minutes" if FINAL_TIME.second == 0 else "seconds")
    TITLE = f"{CONFIG['cohort']} {CONFIG['group']} {CONFIG['mission']}"
    STATE_DIR = Path(os.environ.get("LOCALAPPDATA", str(ROOT / "data"))) / "HamummalCheck" / CONFIG["profile_id"]
