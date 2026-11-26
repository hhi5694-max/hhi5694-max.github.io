#!/usr/bin/env python3
"""장전픽 · 장중픽 자동 추출 — 진화론 님 스냅샷이 아니라 **우리 자료**로 매일 뽑아 누적한다.

쓰는 자료(모두 공개 시세·공개 기사)
  data/day125.json     종목별 125봉 일봉(바닥·횡보·눌림목·상한가 이력 계산)
  data/calendar.json   최근 1년 테마달력(테마 보유 여부·최근 상한가)
  data/news.json       오늘 뉴스·테마 순위·오늘 상한가(이슈 한 줄·매체 수)
  네이버 증권 공개 API  현재가·시장경보·관리종목/거래정지, 오늘 상승률 순위, 1분봉(포착 시각)

모드
  --mode pre     평일 08:30~08:55. 직전 거래일 기준 장전픽 3~5종목. 이미 확정된 당일 장전픽은 덮어쓰지 않고
                 가격·등락률만 갱신한다(픽은 그날 아침의 판단을 그대로 둔다).
  --mode intra   평일 09:05~15:25. 오늘 실시간 상한가·급등 테마 선도주 중 아직 없는 종목을 장중픽으로 추가
                 (하루 최대 5개)하고, 기존 픽의 현재가·등락률을 갱신한다.
  --mode after   장 마감 뒤(15:30 이후). 오늘 종가·상한가·테마·마감 뒤 뉴스로 **내일 볼 장후픽 3~5종목**을
                 뽑는다(기준가 = 오늘 종가). 이미 뽑혀 있으면 덮어쓰지 않고 가격만 갱신한다.
                 --mode update 도 15:30 이후에는 장후픽을 함께 만든다.
  --mode update  장 마감 뒤(15:45) 또는 매시간. 오늘 픽 전부의 현재가(마감 뒤엔 종가)와 등락률을 확정하고,
                 마감 뒤면 장후픽까지 채운다.

불건전 제외
  upper_rank.screen(관리종목·거래정지·투자경고/위험·우선주·SPAC·DR·자본잠식)과
  upper_rank.news_screen(환기종목·감사의견·상폐·횡령/배임·회생/파산·자본잠식 기사)을 그대로 통과한 종목만 쓴다.

저장
  평문 장부(재빌드·누적용)  ../private-plain/picks_results.json   (저장소 밖 — 절대 커밋하지 않는다)
  공개 파일(잠금)          data/picks_results.json  {enc,salt,iv,ct} — hotbar/radar 와 같은 AES-256-GCM
  실전·레이더·종합 안내    data/hotbar.json · hotbar_monthly.json · radar.json · popup.json
                           (build_boards.py 가 같은 장부에서 오늘 픽만 골라 다시 만든다 — 이전 날 픽은 남기지 않는다)

  python3 scripts/build_picks.py --mode pre
  python3 scripts/build_picks.py --mode intra
  python3 scripts/build_picks.py --mode after
  python3 scripts/build_picks.py --mode update
  python3 scripts/build_picks.py --mode pre --dry-run       # 저장하지 않고 고른 종목만 보여 준다
비밀코드는 --code · 환경변수 PICKS_PW · 파일 ../private-plain/.picks_code 순서로 읽는다(저장소에 적지 않는다).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import upper_rank as UR  # noqa: E402  (불건전 필터·1분봉·일봉 파서를 그대로 쓴다)

KST = timezone(timedelta(hours=9))
DATA = os.path.join(ROOT, "data")
DAY125 = os.path.join(DATA, "day125.json")
CAL = os.path.join(DATA, "calendar.json")
NEWS = os.path.join(DATA, "news.json")
OUT = os.path.join(DATA, "picks_results.json")
PLAIN = os.path.join(os.path.dirname(ROOT), "private-plain", "picks_results.json")
CODE_FILE = os.path.join(os.path.dirname(ROOT), "private-plain", ".picks_code")

PBKDF2_ITER = 100000          # index.html 의 HOT_ITER 와 같아야 한다
UA = UR.UA
BASIC = "https://m.stock.naver.com/api/stock/{code}/basic"
FIN = "https://m.stock.naver.com/api/stock/{code}/finance/annual"
RANK_API = ("https://stock.naver.com/api/domestic/market/stock/default"
            "?tradeType=KRX&marketType={market}&orderType=up&startIdx=0&pageSize={size}")
RANK_REFERER = "https://stock.naver.com/market/stock/kr/stocklist/upper"
STOCK_NEWS_API = "https://m.stock.naver.com/api/news/stock/{code}?pageSize=20&page=1"
MARKETS = (("KOSPI", "코스피"), ("KOSDAQ", "코스닥"))

# ---- 픽 규칙 문턱값 (upper_rank 의 바닥·횡보 기준과 같은 값을 쓴다)
UPPER_RATE = UR.UPPER_RATE        # 29.0 — 그날 상한가로 볼 고가/전일종가 상승률
BOX_BARS = UR.BOX_BARS            # 60
BOX_RANGE_MAX = UR.BOX_RANGE_MAX  # 80%
BOTTOM_DD = UR.BOTTOM_DD          # -40%
BOX_POS_MAX = UR.BOX_POS_MAX      # 0.35
PRE_MIN, PRE_MAX = 3, 5           # 장전픽 3~5종목
INTRA_MAX = 5                     # 장중픽 하루 최대 5종목
AFTER_MIN, AFTER_MAX = 3, 5       # 장후픽 3~5종목 (내일 볼 자리)
INTRA_SURGE = 8.0                 # 장중 '급등'으로 볼 등락률(%)
CAPTURE_SURGE = 5.0               # 1분봉에서 '포착'으로 보는 등락률(%) — 포착가를 잡는 기준
PULLBACK_MAX_BARS = 60            # 최근 상한가 뒤 눌림목 — 상한가가 이 봉 수 안에 있어야 한다
PULLBACK_DD = (-32.0, -3.0)       # 상한가 고점 대비 지금 위치(%)
PULLBACK_VOL = 0.65               # 눌림 구간 거래량이 상한가 봉의 65% 이하


# ------------------------------------------------------------------ 작은 유틸
def now_kst() -> datetime:
    return datetime.now(KST)


def read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def write_json(path: str, doc) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def http_json(url: str, referer: str = "https://m.stock.naver.com/", timeout: int = 12, tries: int = 3):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Referer": referer})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.25)
    raise RuntimeError(str(last))


def num(v, default=None):
    try:
        s = str(v if v is not None else "").replace(",", "").strip()
        if s in ("", "-", "null", "None"):
            return default
        return float(s)
    except (TypeError, ValueError):
        return default


def short_theme(name: str) -> str:
    """'로봇·피지컬 AI (엔비디아·현대차그룹)' → '로봇·피지컬 AI'"""
    return str(name or "").split(" — ")[0].split(" (")[0].strip()


def norm(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(s or ""))


# ------------------------------------------------------------------ 잠금 (hotbar·radar 와 같은 방식)
def seal(payload, pw: str) -> dict:
    """브라우저 Web Crypto 가 그대로 풀 수 있는 형태(AES-256-GCM · PBKDF2-SHA256 10만회)."""
    from Crypto.Cipher import AES
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    key = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, PBKDF2_ITER, dklen=32)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ct, tag = AES.new(key, AES.MODE_GCM, nonce=iv).encrypt_and_digest(raw)
    b64 = lambda x: base64.b64encode(x).decode("ascii")  # noqa: E731
    return {"enc": 1, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct + tag)}


def secret_code(args) -> str:
    code = (args.code or os.environ.get("PICKS_PW") or "").strip()
    if code:
        return code
    try:
        with open(CODE_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:  # noqa: BLE001
        return ""


# ------------------------------------------------------------------ 시세
def quote(code: str) -> dict:
    """지금 시세 — 현재가·전일 종가·등락률·시장 상태·건전성 필드."""
    out = {"code": code}
    try:
        d = http_json(BASIC.format(code=code))
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:80]
        return out
    price = num(d.get("closePrice"))
    diff = num(d.get("compareToPreviousClosePrice"), 0) or 0
    prev = (price - diff) if price is not None else None
    alert = d.get("marketAlertType") or {}
    out.update({
        "name": d.get("stockName") or "",
        "price": int(price) if price else None,
        "prev_close": int(prev) if prev else None,
        "pct": num(d.get("fluctuationsRatio")),
        "market_status": d.get("marketStatus") or "",
        "traded_at": d.get("localTradedAt") or "",
        "isManagement": bool(d.get("isManagement")),
        "alertCode": str(alert.get("code") or "00"),
        "tradableStatus": str(d.get("tradableStatus") or ""),
        "tradeStop": ((d.get("tradeStopType") or {}).get("name") or ""),
        "endType": str(d.get("stockEndType") or ""),
        "market": d.get("stockExchangeName") or "",
    })
    return out


def debt_ratio(code: str):
    try:
        d = http_json(FIN.format(code=code))
    except Exception:  # noqa: BLE001
        return None
    for r in (d.get("financeInfo") or {}).get("rowList") or []:
        if r.get("title") != "부채비율":
            continue
        nums = []
        for k, v in (r.get("columns") or {}).items():
            x = num((v or {}).get("value"))
            if x is not None:
                nums.append((k, x))
        if nums:
            nums.sort()
            return nums[-1][1]
    return None


def stock_news(code: str) -> list:
    """그 종목 기사(제목·도입부·매체·시각) — news_screen 판정용."""
    out = []
    try:
        blocks = http_json(STOCK_NEWS_API.format(code=code))
    except Exception:  # noqa: BLE001
        return out
    for b in blocks or []:
        for it in (b or {}).get("items") or []:
            try:
                dt = datetime.strptime(str(it.get("datetime") or ""), "%Y%m%d%H%M").replace(tzinfo=KST)
            except ValueError:
                continue
            out.append({"title": str(it.get("titleFull") or it.get("title") or ""),
                        "body": str(it.get("body") or ""),
                        "press": str(it.get("officeName") or ""),
                        "url": str(it.get("mobileNewsUrl") or ""), "dt": dt})
    return out


def minute_prices(code: str, day: str) -> list:
    """그날 1분봉 종가 [(HHMM, 가격)] 오름차순. 실패하면 빈 목록."""
    d = re.sub(r"[^0-9]", "", day)[:8]
    url = ("https://api.finance.naver.com/siseJson.naver?symbol=%s&requestType=1"
           "&startTime=%s&endTime=%s&timeframe=minute" % (code, d, d))
    try:
        raw = UR._get(url, "euc-kr")
    except Exception:  # noqa: BLE001
        return []
    out = []
    for ts, c in re.findall(r'\["(\d{12})"\s*,\s*(?:null|[\d.]+)\s*,\s*(?:null|[\d.]+)'
                            r'\s*,\s*(?:null|[\d.]+)\s*,\s*(null|[\d.]+)', raw):
        if ts[:8] != d or c == "null":
            continue
        out.append((ts[8:12], int(float(c))))
    out.sort()
    return out


def capture_point(code: str, day: str, prev_close: float) -> tuple[str, int] | None:
    """그 종목이 처음 CAPTURE_SURGE% 위로 올라선 분 — (HH:MM, 그때 가격). 없으면 None."""
    if not prev_close:
        return None
    thr = prev_close * (1 + CAPTURE_SURGE / 100.0)
    for hhmm, px in minute_prices(code, day):
        if px >= thr:
            return f"{hhmm[:2]}:{hhmm[2:]}", px
    return None


def rank_rows(size: int = 200) -> list:
    """코스피·코스닥 상승률 순위(상한가 포함) — 네이버 랭킹 API 그대로."""
    rows, seen = [], set()
    for market, label in MARKETS:
        try:
            data = http_json(RANK_API.format(market=market, size=size), referer=RANK_REFERER)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] rank {market}: {e}", file=sys.stderr)
            continue
        if not isinstance(data, list):
            continue
        for x in data:
            code = str(x.get("itemcode") or "")
            if not code or code in seen:
                continue
            seen.add(code)
            price = num(x.get("nowPrice"))
            limit = num(x.get("upperLimitPrice"))
            rows.append({
                "name": str(x.get("itemname") or "").strip(),
                "code": code,
                "market": label,
                "price": int(price) if price else None,
                "pct": num(x.get("prevChangeRate")),
                "is_upper": bool(price and limit and price == limit),
                "trading_value": num(x.get("tradeAmount"), 0) or 0,
                "type": str(x.get("type") or "ST"),
                "assets": x.get("propertyTotal"), "debt": x.get("debtTotal"),
                "status": {
                    "manageStatusGb": str(x.get("manageStatusGb") or "0"),
                    "managementReasonCode": x.get("managementReasonCode"),
                    "tradeStopYn": str(x.get("tradeStopYn") or "N"),
                    "tradableStatus": str(x.get("tradableStatus") or ""),
                    "marketAlertType": str(x.get("marketAlertType") or "00"),
                    "tradingHaltReasonCode": x.get("tradingHaltReasonCode"),
                },
            })
    rows.sort(key=lambda r: -(r.get("pct") or 0))
    return rows


# ------------------------------------------------------------------ 자료 읽기
def load_day125() -> dict:
    d = read_json(DAY125, {}) or {}
    if not d.get("stocks"):
        raise SystemExit("data/day125.json 이 없습니다 — 먼저 scripts/build_day125.py 를 실행하세요")
    return d


def bars_of(day: dict, code: str) -> list:
    st = (day.get("stocks") or {}).get(str(code)) or {}
    return [[float(x) for x in b] for b in (st.get("b") or []) if b and len(b) >= 5]


def bars_until(day: dict, code: str, date: str, skip_last_same: bool = False) -> tuple[list, list]:
    """그 종목의 봉을 date 까지 자른다 → (봉, 그 봉들의 날짜).
       종목별 봉 배열은 dates 의 꼬리에 맞춰 들어 있으므로 길이 차이를 감안해 맞춘다."""
    bars = bars_of(day, code)
    dates = dates_of(day)
    if not bars:
        return [], []
    tail = dates[-len(bars):]
    pair = [(b, d) for b, d in zip(bars, tail) if d and d <= date]
    if skip_last_same and pair and pair[-1][1] == date:
        pair = pair[:-1]
    return [p[0] for p in pair], [p[1] for p in pair]


def iso_date(raw) -> str:
    """day125 의 달력일(YYMMDD, 예: 261126) → '2026-11-26'."""
    s = re.sub(r"[^0-9]", "", str(raw or ""))
    if len(s) == 6:
        return f"20{s[:2]}-{s[2:4]}-{s[4:]}"
    if len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return ""


def dates_of(day: dict) -> list:
    return [iso_date(x) for x in (day.get("dates") or [])]


def name_of(day: dict, code: str) -> str:
    st = (day.get("stocks") or {}).get(str(code)) or {}
    return st.get("n") or ""


def base_metrics(bars: list, idx: int) -> dict:
    """idx 봉(상한가 당일) 기준 — 125봉 바닥·횡보·첫 상한가·눌림목."""
    m = {"bars": len(bars)}
    if idx < 20 or idx >= len(bars):
        return m
    rng = bars[max(0, idx - 124): idx + 1]
    prior = bars[max(0, idx - 124): idx]
    hi = max(b[1] for b in rng)
    lo = min(b[2] for b in rng)
    close = bars[idx][3]
    prev_close = bars[idx - 1][3]
    m["hi125"] = int(hi)
    m["lo125"] = int(lo)
    m["dd"] = round((prev_close / hi - 1) * 100, 1) if hi else 0.0
    m["pos"] = round((prev_close - lo) / (hi - lo), 2) if hi > lo else 0.0
    box = bars[max(0, idx - BOX_BARS): idx]
    if box:
        bh, bl = max(b[1] for b in box), min(b[2] for b in box)
        m["box_range"] = round((bh / bl - 1) * 100, 1) if bl else 0.0
        m["box_close"] = round((bh / prev_close - 1) * 100, 1) if prev_close else 0.0
    def is_up(i):
        if i < 1:
            return False
        pc = bars[i - 1][3]
        return bool(pc) and (bars[i][1] / pc - 1) * 100 >= UPPER_RATE
    m["first_upper"] = not any(is_up(i) for i in range(max(1, idx - 124), idx))
    m["prior_upper"] = sum(1 for i in range(max(1, idx - 124), idx) if is_up(i))
    m["pct"] = round((close / prev_close - 1) * 100, 2) if prev_close else 0.0
    m["upper_ok"] = is_up(idx)
    m["value"] = int(bars[idx][3] * bars[idx][4])
    # 바닥횡보 첫 상한가 조건
    m["bottom_first"] = bool(
        m["first_upper"] and m["bars"] >= UR.MIN_BARS_FOR_BASE
        and m["dd"] <= BOTTOM_DD and (m.get("box_range") or 999) <= BOX_RANGE_MAX
        and m["pos"] <= BOX_POS_MAX)
    # 최근 상한가 뒤 건전 눌림목 — 상한가 고점 대비 -3~-32%, 거래량 마름, 20일선 위
    pull = None
    look_from = max(1, idx - PULLBACK_MAX_BARS)
    for i in range(idx, look_from - 1, -1):
        if not is_up(i):
            continue
        top = bars[i][1]
        dd = (close / top - 1) * 100 if top else 0.0
        if not (PULLBACK_DD[0] <= dd <= PULLBACK_DD[1]):
            continue
        v_ref = bars[i][4] or 1
        v_now = sum(b[4] for b in bars[max(0, idx - 4): idx + 1]) / max(1, len(bars[max(0, idx - 4): idx + 1]))
        if v_now > v_ref * PULLBACK_VOL:
            continue
        ma20 = sum(b[3] for b in bars[max(0, idx - 19): idx + 1]) / max(1, len(bars[max(0, idx - 19): idx + 1]))
        if bars[idx][3] < ma20 * 0.97:
            continue
        pull = {"bars_ago": idx - i, "dd": round(dd, 1), "vol": round(v_now / v_ref, 2) if v_ref else 0}
        break
    m["pullback"] = pull
    return m


def calendar_index(cal: dict) -> tuple[dict, dict]:
    """(테마명 색인, 종목코드 → [테마...]) — 최근 달부터."""
    by_name, by_code = {}, {}
    months = sorted((cal.get("months") or []), key=lambda m: str(m.get("month") or ""), reverse=True)
    for mi, m in enumerate(months):
        month = str(m.get("month") or "")
        for t in (m.get("themes") or []):
            name = str(t.get("name") or "").strip()
            if not name:
                continue
            rec = by_name.setdefault(name, {"name": name, "kind": t.get("kind") or "",
                                            "months": [], "stocks": [], "last": ""})
            if month and month not in rec["months"]:
                rec["months"].append((month, mi))
            for s in (t.get("stocks") or []):
                code = str(s.get("code") or "").strip().upper()
                dates = [str(x) for x in (s.get("dates") or [])]
                rec["stocks"].append({"name": s.get("name") or "", "code": code,
                                      "dates": dates, "leader": int(s.get("leader") or 0)})
                if dates:
                    rec["last"] = max(rec["last"], max(dates))
                if code:
                    lst = by_code.setdefault(code, [])
                    if not any(x["name"] == name for x in lst):
                        lst.append({"name": name, "kind": t.get("kind") or "",
                                    "month": month, "last": max(dates) if dates else ""})
    return by_name, by_code


def news_index(news: dict) -> dict:
    """오늘 뉴스 색인 — {'items':[{blob, rec}], 'themes':{정규화테마: rec}}

    종목은 '이름이 기사 제목·요약에 실제로 나온 기사'만 근거로 쓴다(태그만으로 잇지 않는다).
    """
    out = {"items": [], "themes": {}}
    seen = set()
    for a in (news.get("issues") or []) + (news.get("articles") or []):
        title = str(a.get("title") or "")
        if not title or title in seen:
            continue
        seen.add(title)
        presses = int(num(a.get("presses"), 1) or 1)
        rec = {"title": title, "presses": presses, "url": a.get("url") or "",
               "time": a.get("time") or "", "themes": [str(x) for x in (a.get("db_themes") or [])]}
        out["items"].append({"blob": norm(title + " " + str(a.get("summary") or "")), "rec": rec})
        for th in rec["themes"]:
            k = norm(short_theme(th))
            if k and (k not in out["themes"] or presses > out["themes"][k]["presses"]):
                out["themes"][k] = dict(rec, theme=th)
    for t in (news.get("themes_rank") or []):
        k = norm(short_theme(t.get("label")))
        if not k:
            continue
        hl = (t.get("headlines") or [{}])[0]
        rec = {"title": hl.get("title") or "", "presses": int(num(t.get("presses"), 1) or 1),
               "url": hl.get("url") or "", "time": hl.get("time") or "", "themes": [t.get("label") or ""]}
        if k not in out["themes"] or rec["presses"] > out["themes"][k]["presses"]:
            out["themes"][k] = dict(rec, theme=t.get("label") or "")
    return out


def news_hit_for(nidx: dict, name: str) -> dict | None:
    """그 종목 이름이 기사 제목·요약에 실제로 나온 기사 중 가장 많이 다룬 것 — 없으면 None.
       테마만 같은 기사는 선정 사유로 쓰지 않는다(그 종목이 왜 움직였는지의 근거가 아니므로)."""
    k = norm(name)
    if not k:
        return None
    best = None
    for it in nidx.get("items") or []:
        if k not in it["blob"]:
            continue
        rec = it["rec"]
        if not best or rec["presses"] > best["presses"]:
            best = rec
    return dict(best, via="name") if best else None


def theme_news(nidx: dict, theme: str) -> dict | None:
    """그 테마를 다룬 오늘 기사(점수용) — 사유 문장에는 쓰지 않는다."""
    if not theme:
        return None
    return (nidx.get("themes") or {}).get(norm(short_theme(theme)))


# ------------------------------------------------------------------ 불건전 제외
def screen_candidate(code: str, name: str, row: dict | None = None) -> tuple[list, dict]:
    """upper_rank.screen + news_screen 을 그대로 통과시킨다. (제외 사유, 시세)"""
    q = quote(code)
    reasons: list = []
    if row:
        r = dict(row)
        r.setdefault("name", name)
        reasons += UR.screen(r)
    else:
        # 공식 필드가 없는 자료(일봉·달력에서 온 종목)는 종목 기본 API 의 상태로 같은 검사를 한다
        fake = {"code": code, "name": name or q.get("name") or "",
                "type": "ST" if q.get("endType") in ("", "stock") else "DR",
                "assets": None, "debt": None,
                "status": {"manageStatusGb": "1" if q.get("isManagement") else "0",
                           "tradeStopYn": "Y" if q.get("tradeStop") and q.get("tradeStop") != "TRADING" else "N",
                           "tradableStatus": q.get("tradableStatus") or "tradable",
                           "marketAlertType": q.get("alertCode") or "00"}}
        reasons += UR.screen(fake)
        dr = debt_ratio(code)
        if dr is not None and dr <= 0:
            reasons.append("자본잠식(부채비율 0 이하)")
    if not reasons:
        nreasons, _hits = UR.news_screen(name or q.get("name") or "", stock_news(code))
        reasons += nreasons
    return reasons, q


# ------------------------------------------------------------------ 장부
def load_plain() -> dict:
    d = read_json(PLAIN, {}) or {}
    if not isinstance(d.get("months"), dict):
        d["months"] = {}
    return d


def day_rec(book: dict, date: str) -> dict:
    month = date[:7]
    m = book["months"].setdefault(month, {})
    rec = m.setdefault(date, {})
    rec.setdefault("premarket", [])
    rec.setdefault("intraday", [])
    rec.setdefault("aftermarket", [])
    return rec


def prior_days(book: dict, date: str, n: int = 3) -> list:
    """date 보다 앞선 날짜(최근 순) — 장후픽을 다음 날 따라가기 위해."""
    ds = {d for m in (book.get("months") or {}).values() for d in m.keys() if isinstance(d, str) and d < date}
    return sorted(ds, reverse=True)[:n]


# ------------------------------------------------------------------ 월간 집계
def _leg_agg(rows: list) -> dict:
    """한 갈래(장전·장중·장후)의 월 집계 — 건수 · 오른 건수 · 승률 · 평균 등락률."""
    vals = [p.get("pct") for p in rows if isinstance(p.get("pct"), (int, float)) and not isinstance(p.get("pct"), bool)]
    up = sum(1 for v in vals if v > 0)
    down = sum(1 for v in vals if v < 0)
    return {
        "count": len(rows),
        "priced": len(vals),                 # 결과(%)가 나온 건수 — 대기 중인 장후픽은 빠진다
        "up": up, "down": down, "flat": len(vals) - up - down,
        "win_rate": round(up / len(vals) * 100, 1) if vals else None,
        "avg_pct": round(sum(vals) / len(vals), 2) if vals else None,
    }


def month_summaries(book: dict) -> dict:
    """달마다 월간 집계를 계산해 book['summary']['YYYY-MM'] 에 담는다(덮어쓰기 없이 누적된 장부 기준).

    결과 탭이 화면에서 다시 세지 않아도 되게, 장부 자체가 월 단위 성적표를 들고 있게 한다.
    """
    out = {}
    for month, days in sorted((book.get("months") or {}).items()):
        rows = {"premarket": [], "intraday": [], "aftermarket": []}
        day_n = 0
        for d, rec in days.items():
            if not isinstance(rec, dict) or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(d)):
                continue
            got = False
            for k in rows:
                part = [p for p in (rec.get(k) or []) if isinstance(p, dict)]
                if part:
                    got = True
                rows[k] += part
            if got:
                day_n += 1
        legs = {k: _leg_agg(v) for k, v in rows.items()}
        everything = rows["premarket"] + rows["intraday"] + rows["aftermarket"]
        tot = _leg_agg(everything)
        priced = [p for p in everything if isinstance(p.get("pct"), (int, float)) and not isinstance(p.get("pct"), bool)]
        best = max(priced, key=lambda p: p["pct"], default=None)
        worst = min(priced, key=lambda p: p["pct"], default=None)
        out[month] = {
            "month": month,
            "days": day_n,
            "total": tot["count"],
            "priced": tot["priced"],
            "up": tot["up"], "down": tot["down"], "flat": tot["flat"],
            "win_rate": tot["win_rate"],
            "avg_pct": tot["avg_pct"],
            "legs": legs,
            "best": None if not best else {"name": best.get("name"), "pct": best.get("pct")},
            "worst": None if not worst else {"name": worst.get("name"), "pct": worst.get("pct")},
        }
    return out


def trading_days_ok(dt: datetime) -> bool:
    return dt.weekday() < 5


def market_open_today() -> bool | None:
    """오늘이 실제 거래일인가 — 네이버 시장상태 API. 모르면 None(평일 규칙으로 진행)."""
    try:
        d = http_json("https://stock.naver.com/api/stockSecurity/exchanges/market-status?exchanges=krx",
                      referer="https://stock.naver.com/")
        for ex in (d or {}).get("exchanges") or []:
            if str(ex.get("exchange")).lower() != "krx":
                continue
            for st in ex.get("statuses") or []:
                if st.get("marketType") not in ("KOSPI", "KOSDAQ"):
                    continue
                today = st.get("today") or {}
                if today.get("date") and today.get("date") == now_kst().strftime("%Y-%m-%d"):
                    return bool(today.get("isTradingDay", True))
    except Exception:  # noqa: BLE001
        return None
    return None


def market_phase(dt: datetime) -> str:
    """'pre'(장전) · 'open'(장중) · 'after'(마감 뒤) · 'closed'(휴장)"""
    if not trading_days_ok(dt):
        return "closed"
    mins = dt.hour * 60 + dt.minute
    if mins < 9 * 60:
        return "pre"
    if mins <= 15 * 60 + 30:
        return "open"
    return "after"


def price_now(code: str, day: dict, date: str) -> tuple[int | None, str]:
    """지금 가격 — 장중·장전이면 현재가, 마감 뒤면 그날 종가(일봉). (가격, 기준 설명)"""
    q = quote(code)
    if q.get("price"):
        return q["price"], q.get("market_status") or ""
    bars, _ds = bars_until(day, code, date)
    if bars:
        return int(bars[-1][3]), "일봉"
    return None, ""


def pct_of(cur: int | None, ref: int | None) -> float | None:
    if not cur or not ref:
        return None
    return round((cur / ref - 1) * 100, 2)


def refresh_prices(book: dict, date: str, day: dict, mark_closed: bool) -> int:
    """그날 픽 전부의 현재가·등락률 갱신. mark_closed 면 상태를 '마감'으로 확정.

    장후픽은 기준가가 **그날 종가**라서 그날 안에서는 값이 움직이지 않는다(상태 '대기').
    다음 거래일부터 그날 현재가로 따라가고, 그날 마감이면 '마감'으로 끝낸다.
    """
    rec = day_rec(book, date)
    n = 0
    for key in ("premarket", "intraday"):
        for p in rec[key]:
            cur, _src = price_now(p.get("code"), day, date)
            if cur:
                p["current_price"] = int(cur)
                p["pct"] = pct_of(cur, p.get("ref_price"))
                n += 1
            p["status"] = "마감" if mark_closed else "진행"
    for p in rec.get("aftermarket") or []:
        p.setdefault("status", "대기")
    # 앞선 날의 장후픽 — 다음 거래일(오늘) 현재가로 따라간다
    for d in prior_days(book, date, 3):
        for p in (book["months"][d[:7]].get(d) or {}).get("aftermarket") or []:
            if p.get("status") == "마감":
                continue
            cur, _src = price_now(p.get("code"), day, date)
            if cur:
                p["current_price"] = int(cur)
                p["pct"] = pct_of(cur, p.get("ref_price"))
                n += 1
            p["status"] = "마감" if mark_closed else "진행"
    return n


# ------------------------------------------------------------------ 장전픽
def pick_reason(name: str, theme: str, m: dict, news_hit: dict | None,
                cal_rec: dict | None, upper_date: str) -> str:
    """선정 근거 한 줄 — 실제로 잰 값만 적는다."""
    d = upper_date[5:].replace("-", "/")
    parts = []
    if m.get("bottom_first"):
        parts.append(f"125봉 바닥 횡보 뒤 첫 상한가({d})")
    elif m.get("pullback"):
        pb = m["pullback"]
        parts.append(f"최근 상한가 뒤 {pb['bars_ago']}봉 눌림목 {pb['dd']:+.0f}% · 거래량 {pb['vol']:.2f}배")
    elif m.get("first_upper"):
        parts.append(f"125봉 안 첫 상한가({d} {m.get('pct', 0):+.1f}%) · 고점 대비 {m.get('dd', 0):+.0f}%")
    else:
        parts.append(f"상한가({d} {m.get('pct', 0):+.1f}%) · 고점 대비 {m.get('dd', 0):+.0f}%")
    if m.get("box_range") is not None and m.get("bottom_first"):
        parts.append(f"60봉 폭 {m['box_range']:.0f}%")
    if theme:
        if cal_rec:
            parts.append(f"테마 「{short_theme(theme)}」 달력 {len(cal_rec.get('stocks') or [])}종목")
        else:
            parts.append(f"테마 「{short_theme(theme)}」")
    if news_hit and news_hit.get("title"):
        parts.append(f"뉴스 「{news_hit['title'][:24]}」 {news_hit.get('presses', 1)}곳")
    # 화면 한 줄에 들어가게 — 넘치면 뒤쪽(뉴스·테마)부터 덜어 낸다
    while parts and len(" · ".join(parts)) > 118 and len(parts) > 1:
        parts.pop()
    return " · ".join(parts)[:170]


def build_pre(book: dict, day: dict, cal: dict, news: dict, date: str, force: bool) -> list:
    rec = day_rec(book, date)
    if rec["premarket"] and not force:
        print(f"[info] {date} 장전픽 {len(rec['premarket'])}종목 — 이미 확정, 가격만 갱신")
        return rec["premarket"]

    by_name, by_code = calendar_index(cal or {})
    nidx = news_index(news or {})
    upper_today = {str(x.get("code")): x for x in ((news or {}).get("upper_limits") or {}).get("items") or []}

    cands = []
    for code, st in (day.get("stocks") or {}).items():
        bars, ds = bars_until(day, code, date, skip_last_same=True)   # 직전 거래일까지
        idx = len(bars) - 1
        if idx < 20:
            continue
        upper_date = ds[idx]
        m = base_metrics(bars, idx)
        if not m.get("upper_ok"):
            continue
        name = st.get("n") or ""
        if not name:
            continue
        code = str(code).upper()
        themes = by_code.get(code) or []
        theme = themes[0]["name"] if themes else ""
        cal_rec = by_name.get(theme) if theme else None
        up = upper_today.get(code) or {}
        if not theme and up.get("cal_theme"):
            theme = str(up["cal_theme"])
            cal_rec = by_name.get(theme)
        news_hit = news_hit_for(nidx, name)
        th_news = theme_news(nidx, theme)
        score = 0.0
        if m.get("bottom_first"):
            score += 40
        elif m.get("pullback"):
            score += 30 - min(10, m["pullback"]["bars_ago"] / 6)
        elif m.get("first_upper"):
            score += 22
        score += max(0.0, min(14.0, -m["dd"] / 6))         # 125봉 고점에서 멀수록(바닥에 가까울수록)
        if cal_rec:
            months = dict(cal_rec["months"]).get(upper_date[:7])
            score += 10 if months is not None else 6
            score += min(6.0, len(cal_rec["stocks"]) / 2)
        if th_news:
            score += min(8.0, 2.5 + 1.6 * (th_news.get("presses") or 1))
        if up.get("leader"):
            score += 4
        if (m.get("value") or 0) > 5_000_000_000:
            score += 3
        cands.append({"code": code, "name": name, "theme": theme, "m": m, "cal": cal_rec,
                      "news": news_hit, "score": round(score, 1), "upper": up,
                      "basis": upper_date, "last_close": int(bars[-1][3])})
    cands.sort(key=lambda c: -c["score"])
    basis = cands[0]["basis"] if cands else ""
    print(f"[info] {basis} 상한가 {len(cands)}종목에서 장전픽 후보를 고릅니다")

    picked = []
    for c in cands:
        if len(picked) >= PRE_MAX:
            break
        reasons, q = screen_candidate(c["code"], c["name"], None)
        if reasons:
            print(f"[skip] {c['code']} {c['name']} — {' / '.join(reasons)[:110]}", file=sys.stderr)
            continue
        ref = q.get("prev_close") or c["last_close"]
        cur = q.get("price") or ref
        picked.append({
            "code": c["code"],
            "name": c["name"],
            "market": "코스닥" if "KOSDAQ" in str(q.get("market") or "").upper() else ("코스피" if q.get("market") else ""),
            "theme": short_theme(c["theme"]) or "개별",
            "reason": pick_reason(c["name"], c["theme"], c["m"], c["news"], c["cal"], c["basis"]),
            "pick_time": now_kst().strftime("%H:%M"),
            "ref_price": int(ref),
            "ref_kind": "전일 종가",
            "current_price": int(cur),
            "pct": pct_of(cur, ref),
            "status": "진행",
            "basis_date": c["basis"],
        })
        if len(picked) >= PRE_MIN and len(cands) <= len(picked):
            break
    rec["premarket"] = picked
    rec["basis_date"] = basis
    print(f"[ok] 장전픽 {len(picked)}종목: " + ", ".join(f"{p['name']}({p['pct']:+.2f}%)" for p in picked if p.get("pct") is not None))
    return picked


# ------------------------------------------------------------------ 장중픽
def build_intra(book: dict, day: dict, cal: dict, news: dict, date: str, phase: str) -> list:
    rec = day_rec(book, date)
    by_name, by_code = calendar_index(cal or {})
    nidx = news_index(news or {})
    rows = rank_rows(200)
    have = {str(p.get("code")) for k in ("premarket", "intraday") for p in rec[k]}
    print(f"[info] 상승률 순위 {len(rows)}종목 · 이미 픽 {len(have)}종목")

    # 테마별로 몇 종목이 함께 오르는지 — 오늘 급등 테마의 세기
    theme_count: dict = {}
    for r in rows:
        if (r.get("pct") or 0) < 5:
            continue
        code = r["code"]
        th = (by_code.get(code) or [{}])[0].get("name") or ""
        if not th:
            hit = news_hit_for(nidx, r["name"])
            th = str(((hit or {}).get("themes") or [""])[0] or "")
        r["_theme"] = th
        if th:
            k = norm(short_theme(th))
            theme_count[k] = theme_count.get(k, 0) + 1

    cands = []
    for r in rows:
        if r["code"] in have:
            continue
        if r.get("type") != "ST":
            continue
        pct = r.get("pct") or 0
        if pct < INTRA_SURGE and not r.get("is_upper"):
            continue
        th = r.get("_theme") or ""
        k = norm(short_theme(th))
        tcount = theme_count.get(k, 0) if k else 0
        score = pct + (6 if r.get("is_upper") else 0) + min(12, tcount * 2.5)
        score += min(6.0, (r.get("trading_value") or 0) / 5e10)
        if nidx["themes"].get(k):
            score += 3
        cands.append((score, r, th))
    cands.sort(key=lambda x: -x[0])

    added = 0
    for score, r, th in cands:
        if len(rec["intraday"]) >= INTRA_MAX:
            break
        if r["code"] in {p.get("code") for p in rec["intraday"]}:
            continue
        reasons, q = screen_candidate(r["code"], r["name"], r)
        if reasons:
            print(f"[skip] {r['code']} {r['name']} — {' / '.join(reasons)[:110]}", file=sys.stderr)
            continue
        prev_close = q.get("prev_close")
        cap = capture_point(r["code"], date, prev_close) if phase == "open" else None
        cur = q.get("price") or r.get("price")
        if cap:
            pick_time, ref = cap
            ref_kind = f"포착가 · 전일 종가 대비 +{CAPTURE_SURGE:.0f}% 선"
        else:
            pick_time, ref = now_kst().strftime("%H:%M"), cur
            ref_kind = "포착가"
        n_hit = news_hit_for(nidx, r["name"])
        why = []
        if r.get("is_upper"):
            why.append("오늘 상한가")
        else:
            why.append(f"장중 +{r['pct']:.1f}%")
        if th:
            cnt = theme_count.get(norm(short_theme(th)), 0)
            why.append(f"테마 「{short_theme(th)}」 동반 {cnt}종목" if cnt > 1 else f"테마 「{short_theme(th)}」")
        if n_hit and n_hit.get("title"):
            why.append(f"뉴스 「{n_hit['title'][:30]}」 {n_hit.get('presses', 1)}곳")
        rec["intraday"].append({
            "code": r["code"], "name": r["name"], "market": r.get("market") or "",
            "theme": short_theme(th) or "개별",
            "reason": " · ".join(why)[:160],
            "pick_time": pick_time,
            "ref_price": int(ref) if ref else None,
            "ref_kind": ref_kind,
            "current_price": int(cur) if cur else None,
            "pct": pct_of(cur, ref),
            "status": "진행" if phase == "open" else "마감",
        })
        added += 1
    print(f"[ok] 장중픽 {added}종목 추가 — 오늘 장중픽 {len(rec['intraday'])}종목")
    return rec["intraday"]


# ------------------------------------------------------------------ 장후픽
def after_reason(name: str, theme: str, m: dict, row: dict, theme_n: int,
                 news_hit: dict | None) -> str:
    """장후픽 근거 한 줄 — 오늘 실제로 잰 값만 적는다(내일 볼 자리)."""
    pct = row.get("pct") or 0
    parts = [f"오늘 상한가({pct:+.1f}%)" if row.get("is_upper") else f"오늘 {pct:+.1f}%"]
    touch = "" if row.get("is_upper") else "(장중 터치)"
    if m.get("bottom_first"):
        parts.append("125봉 바닥 횡보 뒤 첫 상한가" + touch)
    elif m.get("first_upper"):
        parts.append("125봉 안 첫 상한가" + touch)
    elif not row.get("is_upper") and m.get("pullback") and (m["pullback"].get("bars_ago") or 0) > 0:
        pb = m["pullback"]
        parts.append(f"눌림목 {pb['dd']:+.0f}% · 거래량 {pb['vol']:.2f}배")
    if m.get("dd") is not None:
        parts.append(f"고점 대비 {m['dd']:+.0f}%")
    if theme:
        parts.append(f"테마 「{short_theme(theme)}」 오늘 {theme_n}종목" if theme_n > 1
                     else f"테마 「{short_theme(theme)}」")
    if news_hit and news_hit.get("title"):
        parts.append(f"뉴스 「{news_hit['title'][:24]}」 {news_hit.get('presses', 1)}곳")
    while parts and len(" · ".join(parts)) > 118 and len(parts) > 1:
        parts.pop()
    return " · ".join(parts)[:170]


def build_after(book: dict, day: dict, cal: dict, news: dict, date: str, force: bool) -> list:
    """장후픽 — 오늘 종가로 **내일 볼 자리 3~5종목**. 기준가는 오늘 종가."""
    rec = day_rec(book, date)
    if rec["aftermarket"] and not force:
        print(f"[info] {date} 장후픽 {len(rec['aftermarket'])}종목 — 이미 확정, 가격만 갱신")
        return rec["aftermarket"]

    by_name, by_code = calendar_index(cal or {})
    nidx = news_index(news or {})
    rows = rank_rows(200)
    have = {str(p.get("code")) for k in ("premarket", "intraday", "aftermarket") for p in rec[k]}
    print(f"[info] 마감 순위 {len(rows)}종목 · 오늘 이미 픽 {len(have)}종목")

    # 오늘 같은 테마에서 함께 오른 종목 수 — 내일도 볼 테마인지
    theme_count: dict = {}
    for r in rows:
        if (r.get("pct") or 0) < 8:
            continue
        th = (by_code.get(r["code"]) or [{}])[0].get("name") or ""
        r["_theme"] = th
        if th:
            k = norm(short_theme(th))
            theme_count[k] = theme_count.get(k, 0) + 1

    cands = []
    for r in rows:
        if r["code"] in have or r.get("type") != "ST":
            continue
        pct = r.get("pct") or 0
        if pct < 8 and not r.get("is_upper"):
            continue
        bars, ds = bars_until(day, r["code"], date)
        if len(bars) < 21:
            continue
        # 오늘 봉이 아직 차트에 없으면(장 마감 직후 갱신 전) 상한가·눌림목 판정은 쓰지 않고
        # 어제까지의 고점 거리만 근거로 삼는다 — 어제 상한가를 오늘로 잘못 적지 않게.
        today_bar = bool(ds) and ds[-1] == date
        m = base_metrics(bars, len(bars) - 1) if today_bar else {}
        if not today_bar:
            m = {"dd": base_metrics(bars, len(bars) - 1).get("dd")}
        th = r.get("_theme") or ""
        if th.startswith("재료 미확인"):          # '재료 미확인·수급 단독 상한가'는 테마가 아니다
            th = ""
        if not th:
            hit = news_hit_for(nidx, r["name"])
            th = str(((hit or {}).get("themes") or [""])[0] or "")
        tn = theme_count.get(norm(short_theme(th)), 0) if th else 0
        nh = news_hit_for(nidx, r["name"])
        score = 30.0 if r.get("is_upper") else min(18.0, pct)
        if m.get("bottom_first"):
            score += 16
        elif m.get("first_upper"):
            score += 9
        elif m.get("pullback"):
            score += 7
        score += max(0.0, min(12.0, -(m.get("dd") or 0) / 5))     # 고점에서 멀수록(바닥에 가까울수록)
        score += min(12.0, tn * 2.5)
        score += min(6.0, (r.get("trading_value") or 0) / 5e10)
        if nh:
            score += 4
        cands.append({"row": r, "m": m, "theme": th, "tn": tn, "news": nh,
                      "score": round(score, 1)})
    cands.sort(key=lambda c: -c["score"])
    print(f"[info] 장후픽 후보 {len(cands)}종목 — 내일 볼 자리를 고릅니다")

    picked = []
    for c in cands:
        if len(picked) >= AFTER_MAX:
            break
        r = c["row"]
        reasons, q = screen_candidate(r["code"], r["name"], r)
        if reasons:
            print(f"[skip] {r['code']} {r['name']} — {' / '.join(reasons)[:110]}", file=sys.stderr)
            continue
        close = q.get("price") or r.get("price")
        if not close:
            continue
        picked.append({
            "code": r["code"], "name": r["name"],
            "market": "코스닥" if "KOSDAQ" in str(q.get("market") or "").upper() else ("코스피" if q.get("market") else (r.get("market") or "")),
            "theme": short_theme(c["theme"]) or "개별",
            "reason": after_reason(r["name"], c["theme"], c["m"], r, c["tn"], c["news"]),
            "pick_time": now_kst().strftime("%H:%M"),
            "ref_price": int(close),
            "ref_kind": "당일 종가",
            "current_price": int(close),
            "pct": 0.0,
            "status": "대기",                 # 다음 거래일에 '진행' → 마감에 '마감'
            "basis_date": date,
        })
    rec["aftermarket"] = picked
    print(f"[ok] 장후픽 {len(picked)}종목(기준 오늘 종가): "
          + ", ".join(f"{p['name']}({p['ref_price']:,}원)" for p in picked))
    return picked


# ------------------------------------------------------------------ day125 채우기 확인
def ensure_day125(day: dict, date: str) -> None:
    book_codes = set((day.get("stocks") or {}).keys())
    missing = []
    for month in (load_plain().get("months") or {}).values():
        for rec in month.values():
            for p in (rec.get("premarket") or []) + (rec.get("intraday") or []):
                c = str(p.get("code") or "")
                if c and c not in book_codes:
                    missing.append(c)
    if not missing:
        return
    print(f"[warn] 125봉에 없는 픽 종목 {len(missing)}개: {missing[:8]} — build_day125.py --fill-missing 실행",
          file=sys.stderr)
    import subprocess
    try:
        subprocess.run([sys.executable, os.path.join(HERE, "build_day125.py"), "--fill-missing"],
                       cwd=ROOT, check=False, timeout=900)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] build_day125 실패: {e}", file=sys.stderr)


# ------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser(description="장전픽·장중픽·장후픽 자동 추출")
    ap.add_argument("--mode", choices=("pre", "intra", "after", "update"), required=True)
    ap.add_argument("--date", default="", help="기준 날짜(YYYY-MM-DD) — 기본은 오늘(KST)")
    ap.add_argument("--code", default="", help="비밀코드(기본: PICKS_PW 환경변수 · private-plain/.picks_code)")
    ap.add_argument("--out", default=OUT, help="잠근 공개 파일")
    ap.add_argument("--plain", default=PLAIN, help="평문 장부(저장소 밖)")
    ap.add_argument("--force", action="store_true", help="이미 확정된 픽(장전·장후)도 다시 뽑는다")
    ap.add_argument("--dry-run", action="store_true", help="저장하지 않고 결과만 보여 준다")
    args = ap.parse_args()

    dt = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=KST) if args.date else now_kst()
    date = dt.strftime("%Y-%m-%d")
    phase = market_phase(dt)
    if not args.date and phase != "closed" and market_open_today() is False:
        print(f"[skip] {date} 은 휴장일입니다 — 픽을 만들지 않습니다")
        return
    day = load_day125()
    cal = read_json(CAL, {}) or {}
    news = read_json(NEWS, {}) or {}
    book = load_plain()

    if args.mode == "pre":
        build_pre(book, day, cal, news, date, args.force)
        refresh_prices(book, date, day, mark_closed=(phase == "after"))
    elif args.mode == "intra":
        build_intra(book, day, cal, news, date, phase)
        refresh_prices(book, date, day, mark_closed=False)
    elif args.mode == "after":
        if not args.date and phase != "after" and not (args.force or args.dry_run):
            print(f"[skip] {date} 은 아직 장 마감 전입니다 — 장후픽은 15:30 마감 뒤에 뽑습니다")
            return
        build_after(book, day, cal, news, date, args.force)
        refresh_prices(book, date, day, mark_closed=False)
    else:
        refresh_prices(book, date, day, mark_closed=(phase in ("after", "closed")))
        if phase == "after":                 # 15:30 이후 update 회차는 장후픽까지 만든다
            build_after(book, day, cal, news, date, False)

    # 상태 확정 — 지난 날짜 중 아직 '진행'인 픽은 마감으로 정리하고 종가를 넣는다
    for month, days in book["months"].items():
        for d, rec in days.items():
            if d >= date:
                continue
            for p in (rec.get("premarket") or []) + (rec.get("intraday") or []) + (rec.get("aftermarket") or []):
                if p.get("status") not in ("마감", "대기"):
                    cur, _ = price_now(p.get("code"), day, d)
                    if cur:
                        p["current_price"] = int(cur)
                        p["pct"] = pct_of(cur, p.get("ref_price"))
                    p["status"] = "마감"

    book["updated_at"] = now_kst().isoformat(timespec="seconds")
    book["updated_kst"] = now_kst().strftime("%Y.%m.%d %H:%M")
    book["summary"] = month_summaries(book)          # 달마다 월간 성적표도 장부 안에 함께 남긴다
    book["version"] = 1

    rec = day_rec(book, date)
    summ = {
        "premarket": len(rec["premarket"]), "intraday": len(rec["intraday"]),
        "aftermarket": len(rec.get("aftermarket") or []),
    }
    print(f"[sum] {date} 장전 {summ['premarket']} · 장중 {summ['intraday']} · 장후 {summ['aftermarket']}")
    for m, s in (book.get("summary") or {}).items():
        print(f"   월집계 {m}: {s['total']}건(결과 {s['priced']}) · 승률 {s['win_rate']}% · 평균 {s['avg_pct']}%"
              + f" · 장전 {s['legs']['premarket']['count']} · 장중 {s['legs']['intraday']['count']}"
              + f" · 장후 {s['legs']['aftermarket']['count']}")
    for k in ("premarket", "intraday", "aftermarket"):
        for p in (rec.get(k) or []):
            print(f"   {k[:3]} {p['name']:<10} 기준 {p.get('ref_price'):>8} → {p.get('current_price'):>8} "
                  f"{('' if p.get('pct') is None else format(p['pct'], '+.2f') + '%')}  {p.get('status','')}  {p.get('reason','')[:60]}")

    if args.dry_run:
        print("[dry-run] 저장하지 않았습니다")
        return

    write_json(args.plain, book)
    code = secret_code(args)
    if not code:
        raise SystemExit("비밀코드가 없습니다 — --code · PICKS_PW · private-plain/.picks_code 중 하나가 필요합니다")
    write_json(args.out, seal(book, code))
    print(f"[ok] {args.plain} · {args.out} (잠금 완료)")
    # 실전(실전 첫 칸·테마 칸) · 레이더 · 오늘 종합 안내도 같은 장부의 오늘 픽으로 다시 만든다
    # — 이전 날 픽이 그 화면에 남지 않게 매 회차 같이 갈아 끼운다.
    try:
        import build_boards
        counts = build_boards.write_all(book, date, code)
        print(f"[ok] 실전·레이더·종합 안내 갱신 — 장전 {counts['premarket']} · 장중 {counts['intraday']}"
              + (f" · 장후 {counts.get('aftermarket', 0)}" if counts.get("aftermarket") else ""))
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 보드(hotbar·radar·popup) 갱신 실패: {e}", file=sys.stderr)
    ensure_day125(day, date)


if __name__ == "__main__":
    main()
