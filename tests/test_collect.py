"""가짜 API 응답으로 수집기 전체 흐름을 확인합니다. 실행: python tests/test_collect.py"""
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = tmp
os.environ["BACKFILL_FROM"] = "20260101"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect  # noqa: E402

collect.ROWS = 3  # 페이지 넘김을 시험하려고 작게


def posting(no, date, ident, name, spec, price, cat="시설공통자재(기계설비)"):
    return {"prceNticeNo": no, "nticeDt": date + " 10:00", "bsnsDivNm": cat, "prdctClsfcNo": "40141901",
            "prdctIdntNo": ident, "prdctClsfcNoNm": name, "krnPrdctNm": spec, "unit": "m", "prce": str(price),
            "splyJrsdctRgnNm": "전지역(제주제외)", "dlvryCndtnNm": "현장도착도", "vatYnNm": "부가가치세별도"}


DB = [posting("1", "2026-01-10", "A1", "배관용탄소강관", "SPP 50A", 9800),
      posting("2", "2026-01-10", "B1", "게이트밸브", "50A 10K", 118000),
      posting("3", "2026-02-03", "C1", "동관", "L형 25A", 14800),
      posting("4", "2026-02-20", "D1", "레미콘", "25-24-150", 92000, "시설공통자재(토목)"),
      posting("5", "2026-04-21", "A1", "배관용탄소강관", "SPP 50A", 10300),
      posting("6", "2026-04-21", "B1", "게이트밸브", "50A 10K", 118000),
      posting("7", "2026-04-21", "C1", "동관", "L형 25A", 15100)]


def fake_get(params):
    b, e = params["inqryBgnDate"], params["inqryEndDate"]
    rows = [r for r in DB if b <= r["nticeDt"][:10].replace("-", "") <= e]
    n, p = int(params["numOfRows"]), int(params["pageNo"])
    page = rows[(p - 1) * n:p * n]
    return json.dumps({"response": {"header": {"resultCode": "00", "resultMsg": "정상"},
                                    "body": {"items": page, "totalCount": len(rows), "pageNo": p, "numOfRows": n}}})


# 1) 첫 실행: 2026-01-01 ~ 2026-03-31 백필, 알림 없음
out, ch = collect.run("KEY", fake_get, today=dt.date(2026, 4, 1), sleep=0)
assert out["count"] == 4, out["count"]
assert ch == [] and not (Path(tmp) / "changes.md").exists()
assert json.loads((Path(tmp) / "state.json").read_text())["last_end"] == "20260331"

# 2) 다음 실행: 4월 상반기 공고로 강관 +5.1%, 동관 +2.0%, 밸브 변동 없음
out, ch = collect.run("KEY", fake_get, today=dt.date(2026, 4, 27), sleep=0)
by = {i["name"]: i for i in out["items"]}
assert by["배관용탄소강관"]["p"] == 10300 and by["배관용탄소강관"]["ch"] == 5.1
assert by["동관"]["ch"] == 2.03
assert by["게이트밸브"]["ch"] is None and len(by["게이트밸브"]["h"]) == 1  # 같은 값 반복은 이력 1개
assert [c["name"] for c in ch] == ["배관용탄소강관"]
md = (Path(tmp) / "changes.md").read_text()
assert "+5.1%" in md and "9,800" in md and "10,300" in md
assert len(collect.load_postings(Path(tmp) / "postings.csv")) == 7  # 겹친 기간도 중복 없음

# 3) 다시 실행해도 같은 변동을 또 알리지 않음
out, ch = collect.run("KEY", fake_get, today=dt.date(2026, 4, 28), sleep=0)
assert ch == [] and not (Path(tmp) / "changes.md").exists()

# 4) 인증키 오류(XML 응답)는 분명한 메시지로 멈춤
try:
    collect.parse_page("<OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>30</returnReasonCode>"
                       "</cmmMsgHeader></OpenAPI_ServiceResponse>")
    raise SystemExit("오류가 나야 함")
except collect.ApiError as e:
    assert "JSON이 아닌 응답" in str(e)

# 5) 결과 코드 오류
try:
    collect.parse_page(json.dumps({"response": {"header": {"resultCode": "22", "resultMsg": "LIMITED"}}}))
    raise SystemExit("오류가 나야 함")
except collect.ApiError as e:
    assert "22" in str(e)

# 6) items가 {"item": {...}} 한 건짜리 형태로 와도 처리
items, total = collect.parse_page(json.dumps({"response": {"header": {"resultCode": "00"},
                                  "body": {"items": {"item": DB[0]}, "totalCount": 1}}}))
assert len(items) == 1 and total == 1
print("모든 테스트 통과")
