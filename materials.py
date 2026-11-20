"""배관 원자재 동향 수집기 (한국은행 ECOS 생산자물가지수).

환경변수
  ECOS_API_KEY   한국은행 ECOS 인증키 (없으면 이 단계는 건너뜀)

만드는 파일
  data/materials.json   지표별 최근 36개월 지수와 전월·전년 대비 변동률
  data/ecos_items.txt   지표를 못 찾았을 때 고를 수 있는 관련 품목 이름 목록
"""
import datetime as dt
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://ecos.bok.or.kr/api"
TABLES = ["404Y016", "404Y014"]   # 생산자물가지수 품목별 → 없으면 기본분류
MONTHS = 36

# 배관 자재와 연결되는 지표. names: 우선순위대로 찾을 품목 이름, links: 앱 단가 검색에서 연결할 품목 단어
INDICATORS = [
    {"id": "hrc", "label": "열연강판", "names": ["열연강대", "열연강판", "열연"], "links": ["강관", "SPP", "SPPS", "아연도"], "role": "탄소강관의 원재료"},
    {"id": "wpipe", "label": "용접강관", "names": ["용접강관", "철강관"], "links": ["강관", "SPP", "SPPS"], "role": "탄소강관"},
    {"id": "stsplate", "label": "스테인리스 강판", "names": ["스테인리스냉연강판", "스테인리스강판", "스테인리스열연강판", "스테인리스"], "links": ["스테인리스", "STS"], "role": "스테인리스강관의 원재료"},
    {"id": "stspipe", "label": "스테인리스강관", "names": ["스테인리스강관"], "links": ["스테인리스", "STS"], "role": "스테인리스강관"},
    {"id": "nickel", "label": "니켈", "names": ["니켈괴", "니켈1차정련품", "니켈"], "links": ["스테인리스", "STS"], "role": "스테인리스의 주원료"},
    {"id": "copper", "label": "동(구리)", "names": ["전기동", "동1차정련품", "동괴", "나동선", "동제련,정련및합금제품"], "links": ["동관", "황동", "청동"], "role": "동관·황동 밸브의 원재료"},
    {"id": "cupipe", "label": "동관", "names": ["동관", "동및동합금관", "동압연제품", "동1차제품"], "links": ["동관"], "role": "동관"},
    {"id": "zinc", "label": "아연", "names": ["아연괴", "아연1차정련품", "아연", "연및아연제련,정련및합금제품"], "links": ["아연도", "백관"], "role": "아연도강관 도금 원료"},
    {"id": "pvc", "label": "PVC 수지", "names": ["폴리염화비닐수지", "폴리염화비닐", "PVC", "플라스틱1차제품"], "links": ["PVC", "VG"], "role": "PVC관의 원재료"},
    {"id": "plpipe", "label": "플라스틱관", "names": ["플라스틱관", "플라스틱파이프", "합성수지관", "건축용플라스틱제품"], "links": ["PVC", "PE", "PP", "폴리"], "role": "PVC·PE관"},
    {"id": "valve", "label": "밸브", "names": ["밸브"], "links": ["밸브"], "role": "밸브류"},
    {"id": "castpipe", "label": "주철관", "names": ["주철관", "덕타일주철관", "주철"], "links": ["주철"], "role": "주철관"},
]
HINT_WORDS = ["강", "관", "동", "니켈", "아연", "염화", "플라스틱", "밸브", "주철", "스테인리스"]


class EcosError(Exception):
    pass


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "danga-collector/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def call(get, service, key, *parts, start=1, end=1000):
    url = "/".join([BASE, service, urllib.parse.quote(key), "json", "kr", str(start), str(end)] +
                   [urllib.parse.quote(str(p)) for p in parts]) + "/"
    try:
        doc = json.loads(get(url))
    except json.JSONDecodeError as e:
        raise EcosError("JSON이 아닌 응답") from e
    if service in doc:
        return doc[service].get("row", [])
    res = doc.get("RESULT", {})
    if res.get("CODE") == "INFO-200":   # 해당 데이터 없음
        return []
    raise EcosError(f"{res.get('CODE', '?')}: {res.get('MESSAGE', '알 수 없는 응답')}")


def norm(s):
    return "".join(str(s).split()).replace("·", "")


def find_item(items, names):
    """이름 후보 순서대로 정확히 같은 것 → 그 이름으로 시작하는 것 → 포함하는 것 중 가장 짧은 이름."""
    monthly = [i for i in items if i.get("CYCLE", "M") == "M"]
    for name in names:
        n = norm(name)
        for test in (lambda x: x == n, lambda x: x.startswith(n), lambda x: n in x):
            hits = [i for i in monthly if test(norm(i["ITEM_NAME"]))]
            if hits:
                return min(hits, key=lambda i: len(i["ITEM_NAME"]))
    return None


def pct(a, b):
    return round((a / b - 1) * 100, 2) if a is not None and b else None


def collect(key, get=http_get, today=None):
    today = today or dt.date.today()
    first = (today.replace(day=1) - dt.timedelta(days=MONTHS * 31)).strftime("%Y%m")
    last = today.strftime("%Y%m")
    lists = []
    for t in TABLES:
        try:
            items = call(get, "StatisticItemList", key, t, end=5000)
        except EcosError as e:
            if not lists and t == TABLES[-1]:
                raise
            print(f"  {t} 품목 목록을 못 받음: {e}")
            continue
        if items:
            lists.append((t, items))
    if not lists:
        raise EcosError("생산자물가지수 품목 목록이 비어 있음")
    out, missing = [], []
    for ind in INDICATORS:
        hit = None
        for name in ind["names"]:          # 이름 우선순위를 지키되, 같은 이름은 품목별 표를 먼저
            for t, items in lists:
                it = find_item(items, [name])
                if it:
                    hit = (t, it)
                    break
            if hit:
                break
        if not hit:
            missing.append(ind["label"])
            continue
        t, it = hit
        rows = call(get, "StatisticSearch", key, t, "M", first, last, it["ITEM_CODE"], end=200)
        series = []
        for r in rows:
            try:
                series.append([f"{r['TIME'][:4]}-{r['TIME'][4:6]}", float(r["DATA_VALUE"])])
            except (KeyError, ValueError, TypeError):
                continue
        series.sort()
        if not series:
            missing.append(ind["label"])
            continue
        vals = dict(series)
        cur_m, cur = series[-1]
        y, m = int(cur_m[:4]), int(cur_m[5:])
        prev_m = f"{y - (m == 1)}-{12 if m == 1 else m - 1:02d}"
        yago_m = f"{y - 1}-{m:02d}"
        out.append({"id": ind["id"], "label": ind["label"], "role": ind["role"], "links": ind["links"],
                    "item": it["ITEM_NAME"], "code": it["ITEM_CODE"], "table": t, "unit": it.get("UNIT_NAME") or "지수",
                    "m": cur_m, "v": cur, "mom": pct(cur, vals.get(prev_m)), "yoy": pct(cur, vals.get(yago_m)),
                    "s": series})
    hints = sorted({f"{t}\t{i['ITEM_CODE']}\t{i['ITEM_NAME']}" for t, items in lists for i in items
                    if any(w in i["ITEM_NAME"] for w in HINT_WORDS)})
    return {"through": max((o["m"] for o in out), default=None), "source": "한국은행 생산자물가지수",
            "items": out, "missing": missing}, hints


def changes_md(mat, threshold):
    moved = [o for o in mat["items"] if o["mom"] is not None and abs(o["mom"]) >= threshold]
    if not moved:
        return ""
    lines = ["", f"### 원자재 동향: 전월 대비 {threshold}% 이상 움직인 지표", "",
             "| 지표 | 관련 자재 | 기준월 | 전월 대비 | 전년 대비 |", "|---|---|---|---:|---:|"]
    for o in sorted(moved, key=lambda o: -abs(o["mom"])):
        yoy = f"{o['yoy']:+.1f}%" if o["yoy"] is not None else "—"
        lines.append(f"| {o['label']} | {o['role']} | {o['m']} | {o['mom']:+.1f}% | {yoy} |")
    return "\n".join(lines) + "\n"


def run(data_dir, key, get=http_get, today=None):
    """materials.json을 갱신하고, 알림에 붙일 문단을 돌려줍니다. 실패하면 이전 파일을 그대로 둡니다."""
    data_dir = Path(data_dir)
    path = data_dir / "materials.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    try:
        mat, hints = collect(key, get, today)
    except (OSError, EcosError) as e:
        print("원자재 동향 수집 실패, 이전 자료 유지:", e)
        return ""
    path.write_text(json.dumps(mat, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (data_dir / "ecos_items.txt").write_text("\n".join(hints) + "\n", encoding="utf-8")
    for o in mat["items"]:
        print(f"  {o['label']:<10} ← {o['item']} ({o['code']}) {o['m']} {o['v']}")
    if mat["missing"]:
        print("  찾지 못한 지표:", ", ".join(mat["missing"]), "→ data/ecos_items.txt에서 이름 확인")
    # 처음 받을 때는 알림 없이 쌓기만 하고, 이후에는 새 기준월이 들어왔을 때만 알림
    if not old or old.get("through") == mat["through"]:
        return ""
    return changes_md(mat, float(os.environ.get("MATERIAL_THRESHOLD", "3")))
