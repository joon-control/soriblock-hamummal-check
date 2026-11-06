"""Resident current-check handler. A validated room key stays in RAM only."""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import time

from local_state import write_json
import check_communication_room as reader
import slack_api_delivery as delivery
from runtime_config import START_TIME


class QuickChecker:
    def __init__(self):
        self._key = None
        self._pids = ()
        self.key_hits = 0
        self.key_recoveries = 0
        self.last_key_seconds = 0.0

    def key(self):
        pids = tuple(reader.memkey.find_pids())
        page = reader.decryptor.first_page(str(reader.SOURCE))
        if self._key is not None and pids == self._pids and pids:
            if reader.sqlcipher_v4.try_raw_key(page, self._key):
                self.key_hits += 1
                return self._key
        self._key = None
        start = time.perf_counter()
        self._key = reader.recover_key()
        self.last_key_seconds = time.perf_counter() - start
        self._pids = pids
        self.key_recoveries += 1
        return self._key

    def run(self, requested: dt.datetime, *, token: str = "", thread_ts: str = "", preview=False):
        now = dt.datetime.now(reader.KST)
        if requested.tzinfo is None or requested.date() != now.date() or requested > now:
            raise RuntimeError("당일의 지난 요청 시각만 점검할 수 있습니다.")
        sources = [reader.SOURCE, reader.SOURCE.with_name(reader.SOURCE.name + "-wal")]
        latest = max(path.stat().st_mtime for path in sources if path.exists())
        cutoff = dt.datetime.fromtimestamp(int(min(requested.timestamp(), latest)), reader.KST)
        start_of_window = dt.datetime.combine(now.date(), START_TIME, reader.KST)
        if cutoff < start_of_window:
            raise RuntimeError("설정한 시작 시각 이후의 오늘 소통방 기록이 필요합니다.")
        as_of = cutoff.strftime("%H:%M:%S")
        before_hits, before_recoveries = self.key_hits, self.key_recoveries

        def report_loader(at, day):
            def report(at_time, **kwargs):
                return reader.report(at_time, window_end=cutoff, key_provider=self.key, **kwargs)
            return delivery.validated_report(at, day, reporter=report)

        started = time.perf_counter()
        if preview:
            result = report_loader(as_of, cutoff.date())
            result = {name: result[name] for name in ("completed", "missing", "slack_message")}
            result.update({"preview": True, "as_of": as_of})
        else:
            argv = ["--send", "--date", cutoff.date().isoformat(), "--as-of", as_of]
            if thread_ts:
                argv += ["--thread-ts", thread_ts]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                delivery.main(argv, report_loader=report_loader, token=token)
            result = json.loads(output.getvalue())
        result.update({
            "requested_at": requested.isoformat(),
            "source_lag_seconds": round(requested.timestamp() - cutoff.timestamp(), 2),
            "timing": {
                "worker_seconds": round(time.perf_counter() - started, 4),
                "request_to_completed_seconds": round((dt.datetime.now(reader.KST) - requested).total_seconds(), 4),
                "key_reused": self.key_hits > before_hits,
                "key_recovered": self.key_recoveries > before_recoveries,
            },
        })
        return result


class LocalQuickRequests:
    def __init__(self, directory: Path, checker: QuickChecker, token_loader):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.checker = checker
        self.token_loader = token_loader

    def poll(self):
        for path in sorted(self.directory.glob("*.json")):
            request = json.loads(path.read_text(encoding="utf-8"))
            if request.get("state") == "processing":
                request.update(state="failed", error="수신기가 중단된 요청입니다. 게시 여부를 확인해주세요.")
                write_json(path, request)
                continue
            if request.get("state") != "pending":
                continue
            try:
                requested = dt.datetime.fromisoformat(request["requested_at"])
                age = (dt.datetime.now(reader.KST) - requested).total_seconds()
                if not 0 <= age <= 120 or request["action"] not in ("send", "preview"):
                    raise RuntimeError("요청 시각 또는 동작을 확인할 수 없습니다.")
                request["state"] = "processing"
                write_json(path, request)
                result = self.checker.run(requested, token=self.token_loader() if request["action"] == "send" else "",
                                          preview=request["action"] == "preview")
                request.update(state="completed", result=result)
            except (RuntimeError, OSError, ValueError, KeyError) as exc:
                request.update(state="failed", error=str(exc))
            write_json(path, request)
