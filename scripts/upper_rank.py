#!/usr/bin/env python3
"""오늘 상한가 — 테마 묶음 · 선도주 순위 · 불건전 기업 제외 · 125봉 바닥 첫 상한가 · 뉴스↔테마달력 연결.

collect_news.py 가 '오늘 상한가'를 만든 뒤 이 모듈을 부른다. 하는 일은 넷이다.

  1) 불건전 기업 제외 (brief 3)
     네이버 증권 랭킹 API(stock.naver.com/api/domestic/market/stock/default)가 종목마다 실어 주는
     공식 필드로 거른다 — 관리종목(manageStatusGb)·거래정지(tradeStopYn·tradableStatus)·
     시장경보(marketAlertType: 투자주의/경고/위험)·DR(type)·우선주(종목코드 끝자리)·SPAC(이름)·
     자본잠식(자산총계-부채총계 ≤ 0).
     ①-b) 공식 필드에 없는 것(투자주의환기종목·감사의견 거절/한정·상장폐지·횡령·배임·회생절차/파산·
     자본잠식)은 그 종목 기사로 판정한다(2026-11-26 지시 — news_screen). 종목 이름이 기사에 실제로
     나온 최근 악재만 세고, '해소·해제·벗어·적정의견' 같은 완화 문맥은 건너뛰며, 뺄 때는
     「제목·날짜·매체」를 excluded 에 그대로 남긴다.

  2) 상한가 도달 순서 (brief 2 — '상한가를 먼저 갔던 종목 필두')
     api.finance.naver.com/siseJson.naver 의 1분봉(그날 하루만)에서 '처음 상한가 가격에 닿은 분'을 찾는다.
     분봉 종가 기준이라 1분 단위 근사치다(문제점으로 보고).
     2026-11-26 지시 — 장중(평달 09:00~15:30)에는 긁지 않는다. 장 마감 뒤에만 조회해 확정하고,
     장중 실행에서는 값을 비우거나 그날 마감 뒤 이미 잰 값을 그대로 이어 쓴다(collect_news.arrival_window).

  3) 125봉 바닥횡보 첫 상한가 (brief 2 — '무조건 1번')
     일봉 125봉(오늘 빼고 직전 124봉)에서
       ① 상한가 이력이 하나도 없고(고가/전일종가-1 ≥ UPPER_RATE)
       ② 125봉 최고 대비 전일 종가가 40% 이상 내려와 있고(바닥권)
       ③ 최근 60봉 최고~최저 폭이 80% 이내(횡보)이면
     '바닥횡보 첫 상한가'로 보고 그 묶음의 1번으로 올린다.
     문턱값은 아래 상수 — 실측값(base.dd·pos·rng_box·range_pct)을 자료에 남기므로 나중에 조정할 수 있다.

  4) 테마 묶음 + 뉴스↔테마달력 연결 (brief 1·5)
     달력(calendar.json)의 테마·종목과 오늘 상한가 종목을 코드로 잇고, 오늘 뉴스(db_themes)를
     그 테마에 걸어 data/news_themes.json 을 새로 쓴다(지난 배포본은 2026-11-24 에서 멈춰 있었다).

공개 시세·공개 기사만 쓴다. 개인 판단(기준선·단계·점수)은 쓰지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

# ------------------------------------------------------------------ 문턱값
BASE_BARS = 125          # '125봉' — 오늘 봉 포함 125개(직전 124봉 + 오늘)
UPPER_RATE = 29.0        # 일봉 고가/전일 종가 - 1(%) 이보다 크면 그날 상한가로 본다(상한가는 30% 안팎)
BOX_BARS = 60            # '횡보 상자'를 재는 봉 수 — 최근 3개월(단기 급등락을 빼고 바닥 다지기를 본다)
BOX_RANGE_MAX = 80.0     # 그 60봉 최고~최저 폭(%) — 이보다 넓으면 횡보로 보지 않는다
BOTTOM_DD = -40.0        # 125봉 최고가 대비 전일 종가(%) — 이보다 더 내려와 있어야 '바닥권'
BOX_POS_MAX = 0.35       # 125봉 범위 안에서 전일 종가의 위치(0=최저, 1=최고) — 아래 35% 이내
MIN_BARS_FOR_BASE = 60   # 이보다 봉이 적으면(신규상장 등) 바닥 판정을 하지 않는다
WORKERS = 6              # 종목별 분봉·일봉 조회 동시 요청 수
FETCH_DELAY = 0.05       # 요청 사이 간격(초)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
KST = timezone(timedelta(hours=9))

# 시장경보 코드 → 이름 (네이버 증권 m.stock basic API 의 marketAlertType.text 와 같다)
ALERT_LABEL = {"00": "", "01": "투자주의", "02": "투자경고", "03": "투자위험", "04": "투자위험"}
# 관리종목 사유 코드(네이버가 주는 숫자 코드) — 이름을 모르면 코드만 남긴다
MANAGE_REASON = {}
# 우선주 이름 꼬리 — 코드 끝자리 규칙(보통주는 0)을 못 믿을 때 보조로 쓴다
PREF_NAME_RE = re.compile(r"(?:\d)?우(?:B|C)?$")


# ------------------------------------------------------------------ 작은 유틸
def _get(url: str, encoding: str = "utf-8", timeout: int = 15, tries: int = 2) -> str:
    last = None
    for _ in range(tries):
        try:
            time.sleep(FETCH_DELAY)
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode(encoding, "replace")
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(str(last))


def _num(v, default=None):
    try:
        s = str(v if v is not None else "").replace(",", "").strip()
        if s in ("", "-", "null", "None"):
            return default
        return float(s)
    except (TypeError, ValueError):
        return default


def load_calendar(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def calendar_index(cal: dict) -> tuple[dict, dict]:
    """달력 → (테마명 색인, 종목코드 색인).

    theme_of_name[name] = {"kind","months":[최근순], "stocks":[{"name","code","dates","leader"}], "last": 최근 상한가}
    theme_of_code[code] = [{"name","kind","month","dates"}...]  (최근 달 먼저)
    """
    by_name: dict = {}
    by_code: dict = {}
    for m in (cal.get("months") or []):
        month = str(m.get("month") or "")
        for t in (m.get("themes") or []):
            name = str(t.get("name") or "").strip()
            if not name:
                continue
            rec = by_name.setdefault(name, {"name": name, "kind": t.get("kind") or "", "months": [],
                                            "stocks": [], "last": ""})
            if month and month not in rec["months"]:
                rec["months"].append(month)
            for s in (t.get("stocks") or []):
                code = str(s.get("code") or "").strip().upper()
                if not code:
                    continue
                dates = [str(x) for x in (s.get("dates") or [])]
                rec["stocks"].append({"name": s.get("name") or "", "code": code,
                                      "dates": dates, "leader": int(s.get("leader") or 0)})
                last = max(dates) if dates else ""
                rec["last"] = max(rec["last"], last)
                by_code.setdefault(code, []).append({"name": name, "kind": rec["kind"],
                                                     "month": month, "last": last})
    for rec in by_name.values():
        # 종목 중복 제거(같은 달에 두 번 들어온 경우) + 최근 상한가 순
        seen, uniq = set(), []
        for s in rec["stocks"]:
            if s["code"] in seen:
                continue
            seen.add(s["code"])
            uniq.append(s)
        uniq.sort(key=lambda s: (s["leader"], (s["dates"] or [""])[-1]), reverse=True)
        rec["stocks"] = uniq
    for code, lst in by_code.items():
        lst.sort(key=lambda x: (x["last"], x["month"]), reverse=True)
    return by_name, by_code


# ------------------------------------------------------------------ 마스터 테마(153) 색인
def load_master(path: str = "") -> dict:
    """data/master_themes.json — 테마마다 대장주·부대장주·3등주와 종목→테마 역색인."""
    p = path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "data", "master_themes.json")
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("themes") else {}
    except Exception:  # noqa: BLE001
        return {}


def master_index(doc: dict) -> tuple[dict, dict]:
    """마스터 자료 → (테마명 색인, 종목코드 색인).

    themes[name] = {"name","stocks":[{"role","name","code"}]}
    by_code[code] = [테마명, ...]  (역색인 — 그 종목이 어느 마스터 테마에 속하는지)
    """
    themes: dict = {}
    by_code: dict = {}
    for mt in (doc.get("themes") or []):
        name = str(mt.get("name") or "").strip()
        if not name:
            continue
        stocks = [{"role": str(s.get("role") or ""), "name": str(s.get("stock") or s.get("name") or ""),
                   "code": str(s.get("code") or "")} for s in (mt.get("stocks") or [])]
        themes[name] = {"name": name, "stocks": stocks,
                        "cal_themes": [str(c.get("name") or "") for c in (mt.get("cal_themes") or [])]}
        for s in stocks:
            if s["code"]:
                by_code.setdefault(s["code"], [])
                if name not in by_code[s["code"]]:
                    by_code[s["code"]].append(name)
    for code, lst in (doc.get("code_index") or {}).items():
        for name in lst:
            if name in themes:
                by_code.setdefault(str(code), [])
                if name not in by_code[str(code)]:
                    by_code[str(code)].append(name)
    return themes, by_code


# ------------------------------------------------------------------ 1) 불건전 기업 제외
def screen(row: dict) -> list:
    """상한가 랭킹 한 줄 → 제외 사유 목록(비어 있으면 통과).

    row 는 fetch_upper_stocks 가 네이버 랭킹 API 에서 그대로 실어 온 필드를 담는다.
    """
    why = []
    code = str(row.get("code") or "")
    name = str(row.get("name") or "")
    st = row.get("status") or {}

    if str(row.get("type") or "ST") != "ST":
        why.append("DR·ETF 등 주식 아님")
    if code and len(code) == 6 and code[-1] != "0":
        why.append("우선주")
    elif PREF_NAME_RE.search(name):
        why.append("우선주")
    if str(st.get("isManagement") or st.get("manageStatusGb") or "0") not in ("0", "False", "false", ""):
        why.append("관리종목")
    if str(st.get("tradeStopYn") or "N").upper() == "Y":
        why.append("거래정지")
    tradable = str(st.get("tradableStatus") or "tradable")
    if tradable not in ("tradable", ""):
        why.append("거래상태 " + tradable)
    alert = str(st.get("marketAlertType") or "00")
    if alert not in ("00", "", "None"):
        why.append(ALERT_LABEL.get(alert, "시장경보 " + alert))
    if "스팩" in name or "SPAC" in name.upper() or "기업인수목적" in name:
        why.append("SPAC")
    assets, debt = _num(row.get("assets")), _num(row.get("debt"))
    if assets is not None and debt is not None and assets - debt <= 0:
        why.append("자본잠식(자본총계 0 이하)")
    return why


# ------------------------------------------------------------------ 1-b) 뉴스로 보는 불건전 기업
#   네이버 랭킹/기본 API 에 항목이 없는 것들(투자주의환기종목·감사의견 거절/한정·상장폐지·횡령·배임·
#   회생절차·파산·자본잠식)은 그 종목 기사로 판정한다(2026-11-26 지시).
#   · 종목 이름이 기사 제목·도입부에 실제로 나온 경우만 근거로 쓴다(시장 전체 기사 오탐 방지)
#   · '해소·해제·벗어·적정의견·무혐의' 같은 해제/완화 문맥이 낱말 옆에 있으면 세지 않는다
#   · 최근 NEWS_WINDOW_DAYS 일 기사만 본다 — 옛 악재로 지금 종목을 빼지 않는다
#   · 제외 사유에는 어떤 낱말·제목·날짜로 뺐는지 그대로 남긴다
NEWS_WINDOW_DAYS = 180
NEWS_RULES = (
    ("투자주의환기종목", ("환기종목", "투자주의환기", "환기 지정", "환기지정")),
    ("감사의견 거절·한정", ("감사의견 거절", "감사의견거절", "감사의견한정", "의견거절",
                          "감사의견 한정", "한정의견", "감사의견 부적정", "부적정의견")),
    ("상장폐지", ("상장폐지", "상장 폐지")),
    ("횡령·배임", ("횡령", "배임")),
    ("회생절차·파산", ("회생절차", "법정관리", "기업회생", "파산")),
    ("자본잠식", ("자본잠식",)),
)
# 악재 낱말 옆에 있으면 '이미 풀린 일'로 보는 낱말 — 이때는 제외 근거로 쓰지 않는다
RELIEF_MARKERS = ("해소", "해제", "벗어", "탈피", "졸업", "개선", "회복", "기각", "무혐의",
                  "불기소", "무죄", "적정의견", "적정 의견", "면제", "종결", "취소", "철회")
NEWS_CTX = 24            # 낱말 앞뒤로 함께 읽는 글자 수(같은 문장 안의 완화 문맥 판정용)


def _flat(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def news_screen(name: str, articles: list) -> tuple[list, list]:
    """그 종목 기사 → (제외 사유 목록, 근거 hits). 근거가 없으면 빈 목록."""
    reasons: list = []
    hits: list = []
    nn = _flat(name)
    if not nn or not articles:
        return reasons, hits
    # 우선주(동양2우B 등)는 기사에 보통주 이름(동양)으로만 나오기도 한다 — 그 이름까지 같이 본다
    names = [nn]
    m_pref = re.match(r"^(.{2,}?)\d*우(?:B|C)?$", nn)
    if m_pref:
        names.append(m_pref.group(1))
    oldest = datetime.now(KST) - timedelta(days=NEWS_WINDOW_DAYS)
    seen = set()
    for a in articles:
        dt = a.get("dt")
        if dt is not None and dt < oldest:
            continue
        title = str(a.get("title") or "")
        text = _flat(title + " " + str(a.get("body") or ""))
        if not title or not any(n in text for n in names):
            continue
        for label, kws in NEWS_RULES:
            for kw in kws:
                for m in re.finditer(re.escape(_flat(kw)), text):
                    i = m.start()
                    ctx = text[max(0, i - NEWS_CTX): i + len(_flat(kw)) + NEWS_CTX]
                    if any(r in ctx for r in RELIEF_MARKERS):
                        continue
                    if (label, title) in seen:
                        continue
                    seen.add((label, title))
                    date = dt.strftime("%Y-%m-%d") if dt is not None else ""
                    where = ", ".join(x for x in (date, a.get("press") or "") if x)
                    if len(reasons) < 3:      # 사유는 세 줄까지만 — 나머지는 hits 에 남는다
                        reasons.append("뉴스: %s — 「%s」%s"
                                       % (label, title[:78], (" (" + where + ")") if where else ""))
                    hits.append({"rule": label, "keyword": kw, "title": title,
                                 "press": a.get("press") or "", "date": date,
                                 "url": a.get("url") or ""})
                    break
    return reasons, hits


# ------------------------------------------------------------------ 2) 상한가 도달 시각
def _ymd(s: str) -> str:
    return re.sub(r"[^0-9]", "", s or "")[:8]


def first_touch(code: str, base_date: str, upper_price: int) -> dict | None:
    """그날 1분봉에서 '처음 상한가 가격에 닿은 분' — {t:'HH:MM', min: 개장 후 분, after: 장외여부}."""
    d = _ymd(base_date)
    if not d or not upper_price:
        return None
    url = ("https://api.finance.naver.com/siseJson.naver?symbol=%s&requestType=1"
           "&startTime=%s&endTime=%s&timeframe=minute" % (code, d, d))
    try:
        raw = _get(url, "euc-kr")
    except Exception:  # noqa: BLE001
        return None
    rows = re.findall(r'\["(\d{12})"\s*,\s*(null|[\d.]+)\s*,\s*(null|[\d.]+)\s*,\s*(null|[\d.]+)'
                      r'\s*,\s*(null|[\d.]+)\s*,\s*(null|[\d.]+)', raw)
    if not rows:
        return None
    hit = None
    for ts, _o, _h, _l, c, _v in rows:      # 내림차순으로 온다 — 뒤에서부터 보면 처음 닿은 분
        if ts[:8] != d:
            continue
        if c == "null":
            continue
        if _num(c, 0) >= upper_price:
            hit = ts
    if not hit:
        return None
    hh, mm = int(hit[8:10]), int(hit[10:12])
    minute = hh * 60 + mm - 9 * 60          # 09:00 = 0
    return {"t": "%02d:%02d" % (hh, mm), "min": minute, "after": minute > 390}


# ------------------------------------------------------------------ 3) 125봉 바닥횡보 첫 상한가
def daily_rows(code: str, base_date: str) -> list:
    """일봉 — base_date 까지. 값이 0 인 줄(거래정지 표시 등)은 버린다."""
    d = _ymd(base_date)
    try:
        end = datetime.strptime(d, "%Y%m%d")
    except ValueError:
        return []
    start = (end - timedelta(days=800)).strftime("%Y%m%d")
    url = ("https://api.finance.naver.com/siseJson.naver?symbol=%s&requestType=1"
           "&startTime=%s&endTime=%s&timeframe=day" % (code, start, d))
    try:
        raw = _get(url, "euc-kr")
    except Exception:  # noqa: BLE001
        return []
    rows = []
    for r in re.findall(r'\["(\d{8})"\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)'
                        r'\s*,\s*([\d.]+)', raw):
        row = [r[0]] + [float(x) for x in r[1:]]
        if min(row[1:5]) <= 0:              # 시·고·저·종 중 0 이 있으면 그날 자료는 믿지 않는다
            continue
        if row[0] <= d:
            rows.append(row)
    rows.sort(key=lambda r: r[0])
    return rows


def base_check(code: str, base_date: str) -> dict:
    """125봉 바닥횡보 + 첫 상한가 판정 — 실측값을 그대로 남긴다(문턱 조정용).

    ① first_upper — 직전 124봉에 상한가(고가/전일종가 ≥ 29%)가 하나도 없다
    ② bottom      — 125봉 최고가 대비 전일 종가가 BOTTOM_DD% 이하이고, 125봉 범위의 아래 BOX_POS_MAX
    ③ box         — 최근 BOX_BARS(60)봉 최고~최저 폭이 BOX_RANGE_MAX% 이내
    셋 다 맞으면 base_first = True → 그 테마의 1번.
    """
    out = {"bars": 0, "enough": False, "prior_upper": 0, "range_pct": None, "pos": None,
           "dd": None, "rng_box": None, "first_upper": False, "bottom": False,
           "box": False, "base_first": False}
    rows = daily_rows(code, base_date)
    if len(rows) < 2:
        return out
    prev = rows[-(BASE_BARS):-1]            # 오늘 봉을 뺀 직전 124봉(자료가 모자라면 그만큼)
    out["bars"] = len(prev)
    out["enough"] = len(prev) >= MIN_BARS_FOR_BASE
    if not prev:
        return out
    n_upper = 0
    for i in range(1, len(prev)):
        pc = prev[i - 1][4]
        if pc and (prev[i][2] / pc - 1) * 100 >= UPPER_RATE:
            n_upper += 1
    out["prior_upper"] = n_upper
    hi = max(r[2] for r in prev)
    lo = min(r[3] for r in prev)
    prev_close = rows[-2][4]
    out["hi"], out["lo"] = int(hi), int(lo)
    out["range_pct"] = round((hi - lo) / lo * 100, 1) if lo > 0 else None
    out["dd"] = round((prev_close / hi - 1) * 100, 1) if hi > 0 else None
    out["pos"] = round((prev_close - lo) / (hi - lo), 2) if hi > lo else None
    box = prev[-BOX_BARS:]
    bhi = max(r[2] for r in box)
    blo = min(r[3] for r in box)
    out["rng_box"] = round((bhi - blo) / blo * 100, 1) if blo > 0 else None
    out["first_upper"] = out["enough"] and n_upper == 0
    out["bottom"] = (out["dd"] is not None and out["pos"] is not None
                      and out["dd"] <= BOTTOM_DD and out["pos"] <= BOX_POS_MAX)
    out["box"] = out["rng_box"] is not None and out["rng_box"] <= BOX_RANGE_MAX
    out["base_first"] = bool(out["first_upper"] and out["bottom"] and out["box"])
    return out


# ------------------------------------------------------------------ 4) 테마 묶음 · 순위
def _short_theme(name: str) -> str:
    """긴 테마명 → 화면에 쓰는 짧은 이름(괄호 앞)."""
    s = re.sub(r"\s*\([^)]*\)\s*", " ", name or "").strip()
    return s or (name or "")


def group_items(items: list, by_name: dict, by_code: dict,
                master: dict | None = None,
                master_by_code: dict | None = None,
                cal_master: dict | None = None) -> tuple[list, list]:
    """상한가 종목 → (테마 묶음 목록, 종목별 순위가 붙은 목록).

    묶는 순서
      ① 오늘 상한가 종목이 2개 이상 겹치는 달력 테마 (같은 이슈·같은 섹터)
      ①-b 겹치는 종목이 없으면 마스터 테마(153개)에서 2개 이상 겹치는 테마 — 이름·대장주 그대로
      ② 겹치는 종목이 없으면 오늘 기사 키워드 테마가 같은 종목끼리
      ③ 그것도 없으면 그 종목이 속한 달력 테마 이름 하나(단독 묶음)
      ④ 달력에 없는 종목은 '개별 상한가'

    master — 마스터 테마 색인({테마명: {name, stocks}}) · master_by_code — 종목→마스터 테마 역색인.
    붙으면 묶음에 `master`(대장주·부대장주·3등주)를 실어 화면이 그대로 보여 준다.
    """
    master = master or {}
    master_by_code = master_by_code or {}
    cal_master = cal_master or {}
    codes = [it["code"] for it in items]
    code_set = set(codes)
    # ① 달력 테마 겹침 — 오늘 상한가 종목이 2개 이상 함께 있는 테마
    theme_hits: dict = {}
    for code in codes:
        for cand in (by_code.get(code) or [])[:8]:
            rec = by_name.get(cand["name"]) or {}
            over = [c for c in (s["code"] for s in rec.get("stocks") or []) if c in code_set]
            if len(over) >= 2 and code in over:
                theme_hits.setdefault(cand["name"], over)
    assign: dict = {}
    for name, over in theme_hits.items():
        rec = by_name.get(name) or {}
        for c in over:
            cur = assign.get(c)
            if cur is None or len(over) > cur["over"] or rec.get("last", "") > cur["last"]:
                assign[c] = {"theme": name, "kind": rec.get("kind") or "동반테마",
                             "over": len(over), "last": rec.get("last", "")}
    # ①-b 마스터 테마 겹침 — 달력에서 못 묶인 종목끼리 153개 사전으로 다시 묶는다
    m_hits: dict = {}
    for it in items:
        if it["code"] in assign:
            continue
        for name in (master_by_code.get(it["code"]) or []):
            over = [c for c in (s["code"] for s in master.get(name, {}).get("stocks") or [])
                    if c and c in code_set]
            if len(over) >= 2 and it["code"] in over:
                m_hits.setdefault(name, set()).update(over)
    for name, over in m_hits.items():
        for c in over:
            if c in assign:
                continue
            assign[c] = {"theme": name, "kind": "동반테마", "over": len(over), "last": "",
                         "master": name}
    # ② 키워드 테마가 같은 종목끼리
    kw_codes: dict = {}
    for it in items:
        if it["code"] in assign:
            continue
        label = (it.get("theme") or "").strip()
        if label:
            kw_codes.setdefault(label, []).append(it["code"])
    for label, cs in kw_codes.items():
        if len(cs) >= 2:
            for c in cs:
                assign[c] = {"theme": label + " (오늘 키워드)", "kind": "새 이슈",
                             "over": len(cs), "last": ""}
    # ③ 단독 달력 테마 · ④ 개별
    for it in items:
        c = it["code"]
        if c in assign:
            continue
        cands = by_code.get(c) or []
        if cands:
            name = cands[0]["name"]
            rec = by_name.get(name) or {}
            mt = cal_master.get(name) if cal_master else None
            assign[c] = {"theme": name, "kind": cands[0]["kind"] or rec.get("kind") or "",
                         "over": 1, "last": cands[0]["last"], "master": mt}
        else:
            # 달력에 없는 종목 — 서로 다른 재료를 한 통에 담지 않는다(종목마다 따로 세운다)
            label = (it.get("theme") or "").strip()
            assign[c] = {"theme": (label + " 관련" if label else str(it.get("name") or c)),
                         "kind": "새 이슈" if label else "개별상한가", "over": 1, "last": ""}

    # 묶음 만들기
    groups: dict = {}
    for it in items:
        a = assign[it["code"]]
        g = groups.setdefault(a["theme"], {"name": a["theme"], "short": _short_theme(a["theme"]),
                                           "kind": a["kind"], "last": a["last"], "items": [],
                                           "master": a.get("master") or ""})
        g["items"].append(it)
    out_groups = []
    for g in groups.values():
        g["items"].sort(key=lambda it: (
            0 if it.get("base_first") else 1,
            it.get("arrival_min") if it.get("arrival_min") is not None else 10 ** 6,
            -(_num(it.get("trading_value"), 0) or 0)))
        for i, it in enumerate(g["items"]):
            it["group"] = g["name"]
            it["group_short"] = g["short"]
            it["group_kind"] = g["kind"]
            it["group_rank"] = i + 1
            it["leader"] = 1 if i == 0 else 0
        g["count"] = len(g["items"])
        g["base_first"] = 1 if any(it.get("base_first") for it in g["items"]) else 0
        mins = [it["arrival_min"] for it in g["items"] if it.get("arrival_min") is not None]
        g["arrival_min"] = min(mins) if mins else None
        g["arrival"] = g["items"][0].get("arrival") or ""
        g["value"] = sum((_num(it.get("trading_value"), 0) or 0) for it in g["items"])
        g["issue"] = next((it.get("issue_summary") or it.get("article_title") or ""
                           for it in g["items"] if it.get("issue_summary") or it.get("article_title")), "")
        g["issue_url"] = next((it.get("article_url") or "" for it in g["items"] if it.get("article_url")), "")
        out_groups.append(g)
    # 달력 테마에 마스터 메타가 없으면 — 묶음 종목들이 속한 마스터 테마(역색인)로 채운다
    if master_by_code:
        for g in out_groups:
            if g.get("master") or g.get("kind") == "개별상한가":
                continue
            tally: dict = {}
            for it in g["items"]:
                for nm in (master_by_code.get(it["code"]) or []):
                    tally[nm] = tally.get(nm, 0) + 1
            if tally:
                best = max(tally.items(), key=lambda kv: (kv[1], kv[0]))
                if best[1] >= 2:          # 묶음 종목 두 개 이상이 같은 마스터 테마일 때만
                    g["master"] = best[0]
    out_groups.sort(key=lambda g: (0 if g["base_first"] else 1,
                                    g["arrival_min"] if g["arrival_min"] is not None else 10 ** 6,
                                    -g["value"]))
    for i, g in enumerate(out_groups):
        g["rank"] = i + 1
        for it in g["items"]:
            it["theme_rank"] = i + 1
    # 전체 순위 — 묶음 순서대로 이어 붙인다
    flat, seen = [], set()
    for g in out_groups:
        for it in g["items"]:
            if it["code"] in seen:
                continue
            seen.add(it["code"])
            it["rank"] = len(flat) + 1
            flat.append(it)
    return out_groups, flat


def _group_payload(g: dict, master: dict | None = None) -> dict:
    """묶음 하나 → 화면 페이로드. master 가 있으면 그 테마의 대장주·부대장주·3등주를 함께 싣는다."""
    mt = (master or {}).get(g.get("master") or "") or {}
    return {
        "master": ({"name": mt.get("name") or "",
                    "stocks": [{"role": x.get("role") or "", "name": x.get("name") or "",
                                "code": x.get("code") or ""} for x in (mt.get("stocks") or [])]}
                   if mt else None),
        "name": g["name"],
        "short": g["short"],
        "kind": g["kind"],
        "rank": g["rank"],
        "count": g["count"],
        "base_first": g["base_first"],
        "arrival": g.get("arrival") or "",
        "issue": g.get("issue") or "",
        "issue_url": g.get("issue_url") or "",
        "last_lu": g.get("last") or "",
        "stocks": [{"code": it["code"], "name": it["name"], "rank": it["group_rank"],
                    "leader": it["leader"], "base_first": 1 if it.get("base_first") else 0,
                    "arrival": it.get("arrival") or ""} for it in g["items"]],
    }


def rank(items: list, base_date: str, cal: dict, issues: list | None = None,
         limit_base: int = 80, workers: int = WORKERS,
         news_by_code: dict | None = None, arrival_ok: bool = True,
         keep_arrival: dict | None = None) -> tuple[list, list, list, list]:
    """오늘 상한가 목록 → (통과 종목, 테마 묶음, 제외 종목, 갱신된 종목 목록).

    items 는 collect_news 가 만든 상한가 카드(dict). 여기서 상태 검사·도달시각·바닥판정·묶음을 붙인다.
    news_by_code — 종목코드 → 그 종목 기사 목록(제목·도입부·날짜). 뉴스로 불건전을 판정한다.
    arrival_ok   — 1분봉으로 도달 시각을 잴 수 있는 때인지(장중에는 긁지 않는다 — 2026-11-26 지시).
    keep_arrival — 장 마감 후 이미 확정한 도달 시각(코드 → {arrival, arrival_min, arrival_after}).
    """
    by_name, by_code = calendar_index(cal)
    news_by_code = news_by_code or {}
    keep_arrival = keep_arrival or {}
    passed, excluded = [], []
    for it in items:
        why = screen(it)
        hits = []
        if not why:                       # 공식 필드에서 안 걸린 종목만 뉴스로 한 번 더 본다
            why, hits = news_screen(it.get("name"), news_by_code.get(it["code"]) or [])
        if why:
            row = {"name": it.get("name"), "code": it.get("code"),
                   "market": it.get("market"), "reasons": why,
                   "change_rate": it.get("change_rate"),
                   "trading_value_text": it.get("trading_value_text")}
            if hits:
                row["news_hits"] = hits[:5]
            excluded.append(row)
        else:
            passed.append(it)

    # 뉴스 기사 연결 — 오늘 모은 이슈에서 이 종목 이름이 나온 기사
    issue_of = {}
    for a in (issues or []):
        blob = " ".join([str(a.get("title") or ""), " ".join(a.get("tags") or []),
                         " ".join(a.get("leaders") or [])])
        for it in passed:
            nm = str(it.get("name") or "")
            if nm and nm in blob and it["code"] not in issue_of:
                issue_of[it["code"]] = {"title": a.get("title") or "", "url": a.get("url") or "",
                                        "press": a.get("press") or "", "time": a.get("time") or ""}

    # 도달 시각 + 125봉 바닥 판정 (종목별 네트워크 2회 — 실패해도 나머지는 그대로)
    work = passed[:max(0, limit_base)]
    rest = passed[len(work):]

    def one(it):
        code = it["code"]
        price = int(_num(it.get("price"), 0) or 0)
        t = first_touch(code, base_date, price) if arrival_ok else None
        b = base_check(code, base_date)
        return it, t, b

    if work:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for it, t, b in ex.map(one, work):
                carry = keep_arrival.get(it["code"]) or {}
                it["arrival"] = (t or {}).get("t") or str(carry.get("arrival") or "")
                it["arrival_min"] = ((t or {}).get("min") if t else carry.get("arrival_min"))
                it["arrival_after"] = 1 if (t or {}).get("after") else int(carry.get("arrival_after") or 0)
                it["base"] = b
                it["base_first"] = 1 if b.get("base_first") else 0
    for it in rest:
        carry = keep_arrival.get(it["code"]) or {}
        it["arrival"] = str(carry.get("arrival") or "")
        it["arrival_min"] = carry.get("arrival_min")
        it["arrival_after"] = int(carry.get("arrival_after") or 0)
        it["base"] = {"note": "이번 차례에 판정하지 않음"}
        it["base_first"] = 0

    mdoc = load_master()
    m_themes, m_by_code = master_index(mdoc)
    cal_master = {}
    for m in (cal.get("months") or []):
        for t in (m.get("themes") or []):
            nm, mt = str(t.get("name") or ""), (t.get("master") or {}).get("name")
            if nm and mt:
                cal_master.setdefault(nm, mt)
    groups, flat = group_items(passed, by_name, by_code, m_themes, m_by_code, cal_master)

    # 달력 연결 — 이 종목이 어느 달력 테마에 있었는지(최근 달)
    for it in flat:
        cands = by_code.get(it["code"]) or []
        it["cal_theme"] = cands[0]["name"] if cands else ""
        it["cal_theme_kind"] = cands[0]["kind"] if cands else ""
        it["cal_last"] = cands[0]["last"] if cands else ""
        it["cal_seen"] = len({c["name"] for c in cands}) if cands else 0
        if it["code"] in issue_of:
            it["news"] = issue_of[it["code"]]
    return flat, [_group_payload(g, m_themes) for g in groups], excluded, restore_order(items, flat)


def restore_order(items: list, flat: list) -> list:
    """카드 배열을 '전체 순위' 순으로 다시 세운다(제외된 종목은 빠진다)."""
    rank_of = {it["code"]: it for it in flat}
    out = []
    for it in items:
        if it["code"] in rank_of:
            out.append(rank_of[it["code"]])
    return out


# ------------------------------------------------------------------ 5) 뉴스 ↔ 테마달력 (news_themes.json)
def build_news_themes(issues: list, upper: dict, cal: dict, limit: int = 8) -> dict:
    """오늘 뉴스 이슈 → 달력 테마·종목. news_themes.json (뉴스 탭 '오늘 뉴스가 부른 테마').

    기존 화면(index.html radarLinkHtml)이 읽는 모양을 그대로 지킨다 —
    theme, short, kind, issue, issue_url, presses, presses_max, articles, kw, stocks, last_lu, more.
    """
    by_name, by_code = calendar_index(cal)
    up_by_code = {it.get("code"): it for it in (upper.get("items") or [])}
    picked: dict = {}
    for a in issues:
        names = [str(n) for n in (a.get("db_themes") or []) if n]
        if not names:
            continue
        name = names[0]
        rec = by_name.get(name) or {}
        if not rec:
            continue
        cur = picked.get(name)
        presses = int(a.get("presses") or 1)
        if cur is None:
            picked[name] = {"rep": a, "presses": presses, "presses_max": presses,
                            "articles": int(a.get("article_count") or 1), "more": []}
            continue
        cur["presses_max"] = max(cur["presses_max"], presses)
        cur["articles"] += int(a.get("article_count") or 1)
        if presses > cur["presses"]:
            cur["more"].append({"title": cur["rep"].get("title") or "",
                                "presses": cur["presses"], "url": cur["rep"].get("url") or ""})
            cur["rep"], cur["presses"] = a, presses
        elif len(cur["more"]) < 2:
            cur["more"].append({"title": a.get("title") or "", "presses": presses,
                                "url": a.get("url") or ""})
    links = []
    for name, cur in picked.items():
        rec = by_name.get(name) or {}
        rep = cur["rep"]
        stocks = []
        for s in (rec.get("stocks") or [])[:6]:
            up = up_by_code.get(s["code"])
            stocks.append({"name": s["name"], "code": s["code"],
                           **({"upper": 1, "rank": up.get("rank"),
                               "base_first": up.get("base_first") or 0,
                               "arrival": up.get("arrival") or ""} if up else {})})
        last_lu = max([s["dates"][-1] for s in rec.get("stocks") or [] if s.get("dates")] or [""]) \
            if rec.get("stocks") else ""
        kw = [x for x in (rep.get("tags") or []) if x][:4]
        links.append({
            "theme": name,
            "short": _short_theme(name),
            "kind": rec.get("kind") or "",
            "issue": rep.get("title") or "",
            "issue_url": rep.get("url") or "",
            "presses": cur["presses"],
            "presses_max": cur["presses_max"],
            "articles": cur["articles"],
            "kw": kw,
            "stocks": stocks,
            "last_lu": last_lu,
            "more": cur["more"][:2],
            "upper_count": sum(1 for s in stocks if s.get("upper")),
        })
    links.sort(key=lambda x: (-(x["presses_max"] or 0), -(x["upper_count"] or 0), x["theme"]))
    now = datetime.now(KST)
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_at_kst": now.strftime("%Y.%m.%d %H:%M"),
        "news_updated_kst": upper.get("generated_at_kst") or now.strftime("%Y.%m.%d %H:%M"),
        "note": "오늘 뉴스 이슈를 테마달력(calendar.json)의 테마·종목에 이어 붙인 목록 — "
                "테마가 나오면 테마와 종목을 여기에 적어 두고, 화면에서는 종목을 눌러 125봉 차트를 연다.",
        "news_links": links[:limit],
    }


def write_json(path: str, doc: dict) -> None:
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)
