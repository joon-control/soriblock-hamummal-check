"""Update only today's 설정된 조 하멈말 checks through the site's own API.

Login credentials arrive through short-lived environment variables set by the
PowerShell wrapper. The request body with the Slack-validated roster arrives on
stdin. No browser session or KakaoTalk UI is accessed here.
"""

from __future__ import annotations

import datetime as dt
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


from runtime_config import CONFIG, MEMBERS, MEMBER_COUNT, KST
BASE = CONFIG["site"]["base_url"].rstrip("/")


class SiteError(RuntimeError):
    pass


class SiteClient:
    def __init__(self) -> None:
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def request(self, path: str, *, params: dict | None = None, body: dict | None = None) -> dict:
        url = BASE + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST" if body is not None else "GET")
        try:
            with self.opener.open(req, timeout=20) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            raise SiteError(f"사이트 API HTTP {exc.code}: {path}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise SiteError(f"사이트 API 응답 확인 실패: {path} ({type(exc).__name__})") from exc
        if not isinstance(result, dict) or not result.get("success"):
            raise SiteError(f"사이트 API 실패: {path} ({result.get('error', 'unknown') if isinstance(result, dict) else 'invalid JSON'})")
        return result


def load_expected_names() -> dict[str, str]:
    names = {m["site_name"]: m["real_name"] for m in MEMBERS}
    if len(names) != MEMBER_COUNT or len(set(names.values())) != MEMBER_COUNT:
        raise SiteError("Notion 기준 기준 인원 명단이 유일하지 않음")
    return names


def checked(checks: dict, member_id: int, mission_id: int) -> bool:
    by_member = checks.get(str(member_id), checks.get(member_id, {}))
    value = by_member.get(str(mission_id), by_member.get(mission_id, {}))
    return bool(value.get("status")) if isinstance(value, dict) else False


def matching_rows(members: list[dict], expected: dict[str, str], group_id: int) -> dict[str, dict]:
    by_real: dict[str, dict] = {}
    for member in members:
        real = str(member.get("real_name") or "").strip()
        if real in by_real or int(member.get("group_id") or 0) != group_id:
            raise SiteError("사이트 명단의 이름 중복 또는 조 불일치")
        by_real[real] = member
    if len(members) != MEMBER_COUNT or set(by_real) != set(expected.values()):
        raise SiteError("사이트의 설정된 조 기준 인원 명단과 Notion 명단 불일치")
    return by_real


def main() -> None:
    payload = json.load(sys.stdin)
    day = dt.date.fromisoformat(payload["date"])
    if day != dt.datetime.now(KST).date():
        raise SiteError("실행 당일 날짜만 체크 가능")
    completed = payload["completed"]
    missing = payload["missing"]
    expected = load_expected_names()
    if (not isinstance(completed, list) or not isinstance(missing, list)
            or len(completed) + len(missing) != MEMBER_COUNT
            or len(set(completed + missing)) != MEMBER_COUNT
            or set(completed + missing) != set(expected)):
        raise SiteError("Slack 검증 결과와 기준 인원 명단 불일치")

    phone = os.environ.get("SORITUNE_LEADER_PHONE", "")
    if not phone:
        raise SiteError("소리튠 조장 로그인 휴대폰 번호가 설정되지 않음")
    client = SiteClient()
    login = client.request("/api/admin.php?action=login_phone", body={"phone": phone})
    admin = login.get("admin") or {}
    roles = admin.get("admin_roles") or []
    group_id = int(admin.get("bootcamp_group_id") or 0)
    if not set(roles).intersection({"leader", "subleader"}) or not group_id:
        raise SiteError("조장 계정 권한 또는 할당 조를 확인할 수 없음")

    cohorts = client.request("/api/bootcamp.php?action=cohorts").get("cohorts") or []
    cohort_matches = [c for c in cohorts if str(c.get("cohort")) == CONFIG["cohort"]]
    if len(cohort_matches) != 1:
        raise SiteError("설정된 기수 기수를 유일하게 찾지 못함")
    cohort_id = int(cohort_matches[0]["id"])
    groups = client.request("/api/bootcamp.php?action=groups",
                            params={"cohort_id": cohort_id}).get("groups") or []
    group_matches = [g for g in groups if int(g.get("id") or 0) == group_id and g.get("name") == CONFIG["group"]]
    if len(group_matches) != 1:
        raise SiteError("로그인 계정의 할당 조가 설정된 기수 설정된 조가 아님")
    missions = client.request("/api/bootcamp.php?action=mission_types").get("mission_types") or []
    mission_matches = [m for m in missions if m.get("name") == CONFIG["mission"]]
    if len(mission_matches) != 1:
        raise SiteError("하멈말 과제 코드를 유일하게 찾지 못함")
    mission_id = int(mission_matches[0]["id"])
    mission_code = str(mission_matches[0]["code"])
    if not mission_code:
        raise SiteError("하멈말 과제 코드 없음")

    params = {"cohort_id": cohort_id, "group_id": group_id,
              "date": day.isoformat(), "include_expelled": 1}
    before = client.request("/api/bootcamp.php?action=checklist", params=params)
    by_real = matching_rows(before.get("members") or [], expected, group_id)
    checks_before = before.get("checks") or {}
    items = []
    already_checked = 0
    for site_name in completed:
        member_id = int(by_real[expected[site_name]]["id"])
        if checked(checks_before, member_id, mission_id):
            already_checked += 1
        else:
            items.append({"member_id": member_id, "mission_type_code": mission_code,
                          "check_date": day.isoformat(), "status": True})

    if items:
        client.request("/api/bootcamp.php?action=check_bulk_save",
                       body={"check_date": day.isoformat(), "items": items})
    after = client.request("/api/bootcamp.php?action=checklist", params=params)
    after_rows = matching_rows(after.get("members") or [], expected, group_id)
    checks_after = after.get("checks") or {}
    for site_name in completed:
        member_id = int(after_rows[expected[site_name]]["id"])
        if not checked(checks_after, member_id, mission_id):
            raise SiteError(f"저장 후 하멈말 체크가 확인되지 않음: {site_name}")
    for site_name in missing:
        member_id = int(after_rows[expected[site_name]]["id"])
        if checked(checks_after, member_id, mission_id) != checked(checks_before, member_id, mission_id):
            raise SiteError(f"미완료자의 기존 체크 상태가 변경됨: {site_name}")
    print(json.dumps({"saved": True, "date": day.isoformat(), "cohort": CONFIG["cohort"],
                      "group": CONFIG["group"], "completed_count": len(completed),
                      "newly_checked": len(items), "already_checked": already_checked,
                      "verified_after_save": True}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (SiteError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        raise SystemExit(1)
