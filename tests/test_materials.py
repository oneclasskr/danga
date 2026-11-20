"""가짜 ECOS 응답으로 원자재 동향 수집을 확인합니다. 실행: python tests/test_materials.py"""
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import materials  # noqa: E402

ITEMS = [("1", "총지수"), ("2", "열연강대"), ("3", "용접강관"), ("4", "스테인리스강관"), ("5", "스테인리스 냉연강판"),
         ("6", "전기동"), ("7", "동 및 동합금관"), ("8", "아연괴"), ("9", "폴리염화비닐수지"), ("15", "강관연결구류"), ("10", "플라스틱관"),
         ("11", "밸브"), ("12", "주철관 및 주철이음쇠"), ("13", "스테인리스강관용 강대")]
calls = []


def series_for(code, months):
    base = 100 + int(code)
    rows = [{"TIME": m, "DATA_VALUE": f"{base + i * 0.5:.2f}"} for i, m in enumerate(months)]
    if code == "6" and months and months[-1] == "202610":   # 10월에 구리만 급등
        rows[-1]["DATA_VALUE"] = f"{float(rows[-2]['DATA_VALUE']) * 1.06:.2f}"
    return rows


def make_get(last_month):
    def get(url):
        calls.append(url)
        parts = url.rstrip("/").split("/")
        svc = parts[4]
        if svc == "StatisticItemList":
            return json.dumps({"StatisticItemList": {"list_total_count": len(ITEMS), "row": [
                {"ITEM_CODE": c, "ITEM_NAME": n, "CYCLE": "M", "UNIT_NAME": "2020=100"} for c, n in ITEMS]}})
        code, frm, to = parts[-1], parts[-3], parts[-2]
        assert frm < to
        months = [f"{y}{m:02d}" for y in range(2023, 2027) for m in range(1, 13) if frm <= f"{y}{m:02d}" <= last_month]
        return json.dumps({"StatisticSearch": {"list_total_count": len(months), "row": series_for(code, months)}})
    return get


tmp = Path(tempfile.mkdtemp())
# 1) 첫 수집: 지표를 이름으로 찾고, 알림은 없음
md = materials.run(tmp, "KEY", make_get("202609"), today=dt.date(2026, 11, 20))
mat = json.loads((tmp / "materials.json").read_text())
by = {o["id"]: o for o in mat["items"]}
assert md == ""
assert by["hrc"]["item"] == "열연강대"
assert by["stsplate"]["item"] == "스테인리스 냉연강판"       # 띄어쓰기 달라도 찾음
assert by["cupipe"]["item"] == "동 및 동합금관"
assert by["castpipe"]["item"].startswith("주철관")
assert mat["missing"] == ["니켈"], mat["missing"]           # 목록에 없으면 빠진 지표로 표시
assert by["copper"]["m"] == "2026-09" and by["copper"]["mom"] is not None and by["copper"]["yoy"] is not None
assert len(by["hrc"]["s"]) <= 37
assert "니켈괴" not in (tmp / "ecos_items.txt").read_text() and "열연강대" in (tmp / "ecos_items.txt").read_text()

# 2) 새 기준월(10월)이 들어오면 3% 이상 움직인 지표만 알림
md = materials.run(tmp, "KEY", make_get("202610"), today=dt.date(2026, 11, 27))
assert "원자재 동향" in md and "동(구리)" in md, md
assert "열연강판" not in md   # 월 0.5포인트(약 0.4%) 변동은 알림 대상 아님

# 3) 같은 기준월이면 다시 알리지 않음
assert materials.run(tmp, "KEY", make_get("202610"), today=dt.date(2026, 12, 4)) == ""

# 4) 인증키 오류면 이전 자료를 그대로 둠
before = (tmp / "materials.json").read_text()
bad = lambda url: json.dumps({"RESULT": {"CODE": "INFO-100", "MESSAGE": "인증키가 유효하지 않습니다."}})
assert materials.run(tmp, "BAD", bad) == ""
assert (tmp / "materials.json").read_text() == before

# 5) 인증키는 주소에 들어가되 형식이 맞는지
assert calls[0].startswith("https://ecos.bok.or.kr/api/StatisticItemList/KEY/json/kr/1/5000/404Y016/")
assert any("/StatisticSearch/KEY/json/kr/1/200/404Y016/M/" in c for c in calls)
print("모든 테스트 통과")
