"""Submit a fixed current-check request to the user's resident worker."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import time
import uuid

from local_state import write_json
from runtime_config import STATE_DIR


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    state_dir = STATE_DIR / "slack_listener"
    status = json.loads((state_dir / "status.json").read_text(encoding="utf-8"))
    checked = dt.datetime.fromisoformat(status["checked_at"])
    if (dt.datetime.now(dt.timezone.utc) - checked).total_seconds() > 120:
        raise RuntimeError("상주 점검 수신기의 실행 상태를 확인해주세요.")
    path = state_dir / "quick_requests" / (uuid.uuid4().hex + ".json")
    requested = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    write_json(path, {"state": "pending", "requested_at": requested.isoformat(),
                      "action": "preview" if args.preview else "send"})
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        response = json.loads(path.read_text(encoding="utf-8"))
        if response["state"] == "completed":
            print(json.dumps(response["result"], ensure_ascii=False))
            return
        if response["state"] == "failed":
            raise RuntimeError(response["error"])
        time.sleep(0.2)
    raise RuntimeError("완료 응답 대기 시간이 지났습니다. 동일 요청을 중복 실행하지 말고 상태를 확인해주세요.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        raise SystemExit(str(exc))
