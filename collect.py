"""조달청 시설공통자재 가격 수집기.

공공데이터포털 '조달청_나라장터 가격정보현황서비스'의
시설공통자재(종합) 가격정보(getPriceInfoListFcltyCmmnMtrilTotal)를
가격 게시일 기간으로 조회해 이력을 쌓고, 앱이 읽을 최신 단가 파일을 만듭니다.

환경변수
  DATA_GO_KR_KEY   공공데이터포털 일반 인증키 (필수, GitHub Secrets에 저장)
  BACKFILL_FROM    처음 실행할 때 가져올 시작일 YYYYMMDD (기본 20250101)
  ALERT_THRESHOLD  알림 기준 변동률 % (기본 5)

만드는 파일 (data/ 폴더)
  postings.csv  게시된 가격 원본 이력 (가격게시번호 기준 중복 제거)
  prices.json   품목별 최신 단가와 최근 가격 이력 (웹앱이 읽음)
  changes.md    이번 실행에서 기준 이상 바뀐 품목 (있을 때만, 알림용)
  state.json    마지막으로 조회한 날짜
"""
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ENDPOINT = "https://apis.data.go.kr/1230000/ao/PriceInfoService/getPriceInfoListFcltyCmmnMtrilTotal"
DATA = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "data"))
ROWS = 500          # 한 번에 받을 행 수 (서버가 더 적게 주면 그만큼만 받음)
WINDOW_DAYS = 30    # 한 번에 조회할 기간
OVERLAP_DAYS = 7    # 늦게 올라온 게시를 놓치지 않도록 겹쳐 조회
MAX_CALLS = 900     # 개발계정 하루 1,000회 한도 안에서 멈춤
HISTORY_POINTS = 8  # 품목별로 앱에 보낼 가격 이력 개수

FIELDS = ["prceNticeNo", "nticeDt", "bsnsDivNm", "prdctClsfcNo", "prdctIdntNo",
          "prdctClsfcNoNm", "krnPrdctNm", "unit", "prce", "splyJrsdctRgnNm",
          "dlvryCndtnNm", "vatYnNm", "prceDiv", "etcCntnts"]


class ApiError(Exception):
    pass


def http_get(params):
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "danga-collector/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def parse_page(text):
    """응답 한 페이지를 (items, totalCount)로 바꿉니다. 오류면 ApiError."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        # 인증키 오류 등은 type=json이어도 XML로 올 때가 있음
        raise ApiError("JSON이 아닌 응답: " + text[:300].replace("\n", " "))
    resp = doc.get("response", doc)
    header = resp.get("header", {})
    code = str(header.get("resultCode", "00"))
    if code not in ("00", "0", "03"):
        raise ApiError(f"API 오류 {code}: {header.get('resultMsg', '')}")
    body = resp.get("body", {}) or {}
    items = body.get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items, int(body.get("totalCount") or 0)


class Collector:
    def __init__(self, key, get=http_get, sleep=0.2):
        self.key, self.get, self.sleep, self.calls = key, get, sleep, 0

    def fetch_window(self, start, end):
        rows, page = [], 1
        while True:
            if self.calls >= MAX_CALLS:
                raise ApiError("하루 호출 한도에 가까워 멈춤")
            params = {"ServiceKey": self.key, "type": "json", "inqryDiv": "1",
                      "inqryBgnDate": start.strftime("%Y%m%d"),
                      "inqryEndDate": end.strftime("%Y%m%d"),
                      "pageNo": page, "numOfRows": ROWS}
            for attempt in range(3):
                try:
                    self.calls += 1
                    items, total = parse_page(self.get(params))
                    break
                except (OSError, ApiError) as e:
                    if attempt == 2 or (isinstance(e, ApiError) and "API 오류" in str(e)):
                        raise
                    time.sleep(3 * (attempt + 1))
            rows.extend(items)
            if not items or len(rows) >= total:
                return rows
            page += 1
            time.sleep(self.sleep)


def num(v):
    s = "".join(c for c in str(v or "") if c.isdigit() or c == ".")
    try:
        return float(s) if s else None
    except ValueError:
        return None


def item_key(r):
    ident = r.get("prdctIdntNo") or (r.get("prdctClsfcNo", "") + ":" + r.get("krnPrdctNm", ""))
    return "|".join([ident, r.get("splyJrsdctRgnNm", ""), r.get("dlvryCndtnNm", "")])


def load_postings(path):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {r["prceNticeNo"]: r for r in csv.DictReader(f)}


def save_postings(path, posts):
    rows = sorted(posts.values(), key=lambda r: (r["nticeDt"], r["prceNticeNo"]))
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def build(posts, since, threshold):
    """품목별 최신 단가와 이력, 이번 기간에 바뀐 품목 목록을 만듭니다."""
    groups = {}
    for r in posts.values():
        p = num(r.get("prce"))
        if p is None or p <= 0:
            continue
        groups.setdefault(item_key(r), []).append((r["nticeDt"][:10], p, r))
    items, changes = [], []
    for k, g in groups.items():
        g.sort(key=lambda x: (x[0], x[2]["prceNticeNo"]))
        hist = []  # 값이 바뀐 지점만 남김
        for d, p, _ in g:
            if not hist or hist[-1][1] != p:
                hist.append([d, p])
        last = g[-1][2]
        cur, prev = hist[-1], (hist[-2] if len(hist) > 1 else None)
        ch = round((cur[1] / prev[1] - 1) * 100, 2) if prev else None
        it = {"k": k, "cat": (last.get("bsnsDivNm") or "").replace("시설공통자재", "").strip("()") or "기타",
              "name": last.get("prdctClsfcNoNm", ""), "spec": last.get("krnPrdctNm", ""),
              "unit": last.get("unit", ""), "rgn": last.get("splyJrsdctRgnNm", ""),
              "dlv": last.get("dlvryCndtnNm", ""), "vat": last.get("vatYnNm", ""),
              "p": cur[1], "d": g[-1][0], "cd": cur[0], "ch": ch,
              "h": hist[-HISTORY_POINTS:]}
        items.append(it)
        if prev and cur[0] >= since and abs(ch) >= threshold:
            changes.append(it)
    items.sort(key=lambda x: (x["cat"], x["name"], x["spec"]))
    changes.sort(key=lambda x: -abs(x["ch"]))
    return items, changes


def won(v):
    return f"{v:,.0f}"


def changes_md(changes, threshold):
    lines = [f"직전 가격 대비 {threshold}% 이상 바뀐 품목이 {len(changes)}개 있습니다.", "",
             "| 품목 | 규격 | 단위 | 이전 | 현재 | 변동 | 게시일 |", "|---|---|---|---:|---:|---:|---|"]
    for c in changes[:100]:
        prev = c["h"][-2][1]
        lines.append(f"| {c['name']} | {c['spec']} | {c['unit']} | {won(prev)} | {won(c['p'])} | "
                     f"{c['ch']:+.1f}% | {c['cd']} |")
    if len(changes) > 100:
        lines.append(f"\n외 {len(changes) - 100}개는 앱의 '가격 변동 알림'에서 확인하세요.")
    return "\n".join(lines) + "\n"


def run(key, get=http_get, today=None, sleep=0.2):
    DATA.mkdir(parents=True, exist_ok=True)
    today = today or dt.date.today()
    threshold = float(os.environ.get("ALERT_THRESHOLD", "5"))
    state_path, post_path = DATA / "state.json", DATA / "postings.csv"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    end = today - dt.timedelta(days=1)  # 공개 자료는 전일까지 반영
    if state.get("last_end"):
        last = dt.datetime.strptime(state["last_end"], "%Y%m%d").date()
        start = last - dt.timedelta(days=OVERLAP_DAYS)
        since = last + dt.timedelta(days=1)  # 지난 실행 뒤에 바뀐 것만 알림
    else:
        start = dt.datetime.strptime(os.environ.get("BACKFILL_FROM", "20250101"), "%Y%m%d").date()
        since = end + dt.timedelta(days=1)   # 첫 실행은 과거 자료를 쌓기만 하고 알림 없음

    posts = load_postings(post_path)
    before = len(posts)
    col = Collector(key, get, sleep)
    s, done_until = start, None
    try:
        while s <= end:
            e = min(s + dt.timedelta(days=WINDOW_DAYS - 1), end)
            for r in col.fetch_window(s, e):
                if r.get("prceNticeNo"):
                    posts[str(r["prceNticeNo"])] = {f: str(r.get(f) or "").strip() for f in FIELDS}
            print(f"{s}~{e}: 누적 {len(posts):,}건 (호출 {col.calls}회)")
            done_until, s = e, e + dt.timedelta(days=1)
    except ApiError as err:
        print("중단:", err, file=sys.stderr)
        if done_until is None:
            raise
        print(f"{done_until}까지 저장하고 다음 실행에서 이어 받습니다.")

    done_until = done_until or end
    save_postings(post_path, posts)
    items, changes = build(posts, since.isoformat(), threshold)
    out = {"generated": dt.datetime.now().isoformat(timespec="minutes"),
           "through": done_until.isoformat(), "count": len(items), "items": items}
    (DATA / "prices.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    md = DATA / "changes.md"
    if changes:
        md.write_text(changes_md(changes, threshold), encoding="utf-8")
    elif md.exists():
        md.unlink()
    state_path.write_text(json.dumps({"last_end": done_until.strftime("%Y%m%d")}), encoding="utf-8")
    print(f"새 게시 {len(posts) - before:,}건, 품목 {len(items):,}개, 기준 이상 변동 {len(changes)}개")
    return out, changes


if __name__ == "__main__":
    key = os.environ.get("DATA_GO_KR_KEY")
    if not key:
        sys.exit("DATA_GO_KR_KEY 환경변수에 공공데이터포털 인증키를 넣어 주세요.")
    run(key)
