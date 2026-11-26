#!/usr/bin/env python3
"""*****"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import nr_data as NR  # noqa: E402
# 평문은 저장소 밖(private-plain/data)에서만 다루고, data/ 에는 잠근 본만 둔다.
DATA = NR.ensure_plain_dir()
OUT = os.path.join(DATA, "day125.json")
# 저장소 밖 비공개 평문 폴더 — 잠근 자료(hotbar·hotbar_monthly·popup·radar)의 평문 사본을 두는 곳.
#   이 폴더와 그 자료는 저장소에 절대 올리지 않는다. 비밀코드도 여기에 적지 않는다.
PLAIN_DIRS = tuple(d for d in (
    os.environ.get("NEWSRADAR_PLAIN_DIR", ""),
    os.path.join(os.path.dirname(SITE), "private-plain"),
) if d)
# *****
# *****
PINK_LISTS = ("pink_today_hotbar.json", "pink_today_pick.json", "pink_today_popup.json")
KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"}

WEEK_KEEP = 52        # 차트에 싣는 주봉 수(1년)
WEEK_FETCH = 300      # 240주선을 재려면 240 + 52 — 네이버 주봉은 300주까지 준다
MONTH_KEEP = 30       # 차트에 싣는 월봉 수(2년 6개월)
MONTH_START = "20130101"   # 월봉 120개월선용 — 10년보다 넉넉히 받아 둔다


def jload(name):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def plain_path(name):
    """저장소 밖 평문 사본의 경로 — 없으면 ''."""
    for d in PLAIN_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return ""


def jload_private(name):
    """비공개 탭 자료 — data/<name> 이 평문이면 그대로, 잠금본({enc:1})이면 저장소 밖 평문 사본을 쓴다.

    둘 다 없으면(깃허브 액션처럼 저장소만 있는 곳) 빈 자료를 준다 — 그 탭 종목은 이번 빌드에서 건너뛴다.
    잠근 파일은 열지 않는다(비밀코드는 이 스크립트에 없다).
    """
    d = jload(name)
    if isinstance(d, dict) and not d.get("enc"):
        return d
    p = plain_path(name)
    if p:
        try:
            with open(p, encoding="utf-8") as f:
                m = json.load(f)
            if isinstance(m, dict):
                return m
        except Exception:
            pass
    return {}


def jload_calendar():
    """테마달력 자료(달의 상한가 종목) — 공개 평문이다."""
    d = jload_private("calendar.json")
    return d if isinstance(d, dict) and d.get("months") else {"months": []}


def doc_codes(doc):
    """비공개 자료에서 '차트가 열려야 하는 종목코드'만 뽑는다 — 이름·단계·판단은 쓰지 않는다."""
    out: list = []
    if not isinstance(doc, dict):
        return out
    for sec in doc.get("sections") or []:                  # hotbar: sections[].stages[].stocks[]
        if not isinstance(sec, dict):
            continue
        for stg in sec.get("stages") or []:
            for s in stg.get("stocks") or []:
                if isinstance(s, dict):
                    out.append(s.get("code"))
    secs = doc.get("sections")                             # popup: sections{buy,radar,pink}[]
    if isinstance(secs, dict):
        for v in secs.values():
            for s in v or []:
                if isinstance(s, dict):
                    out.append(s.get("code"))
    for s in doc.get("items") or []:                       # popup 예전 형식
        if isinstance(s, dict):
            out.append(s.get("code"))
    for th in doc.get("themes") or []:                     # hotbar_monthly: themes[].stocks[]
        for s in th.get("stocks") or []:
            if isinstance(s, dict):
                out.append(s.get("code"))
    out.extend((doc.get("charts") or {}).keys())           # hotbar_monthly: charts{code:…}
    for t in doc.get("tiers") or []:                       # radar: tiers[].stocks[]
        for s in t.get("stocks") or []:
            if isinstance(s, dict):
                out.append(s.get("code"))
    return out


def pink_codes(cal: dict) -> list[tuple[str, str]]:
    """오늘 형광↑(분홍↑) 종목 (코드, 이름) — 형광↑ 알림 팝업에 뜨는 종목은 차트도 열려야 한다.

    2026-11-23 — 팝업에서 피앤에스로보틱스(460940)를 눌렀을 때 "이 종목 일봉 시세가 아직 없습니다"가
    떴다. 그 종목은 테마달력·상한가·레이더에는 없고 비밀 핫바에만 형광↑가 떠 있었다.
     ① 테마달력 평문 원본의 pink_stocks — 목록이면 그 안의 code/name (지금은 개수(int)만 온다)
     ② 달력 종목의 pinkArrow(기준일 당일 화살)
     ③ 핫바·10단계가 적어 둔 오늘 형광↑ 명단(brain/cache/pink_today_*.json)
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(code, name=""):
        c = str(code or "").strip().upper()
        if len(c) == 6 and all(ch.isdigit() or ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" for ch in c) and c not in seen:
            seen.add(c)
            out.append((c, str(name or "").strip()))

    ps = cal.get("pink_stocks")
    if isinstance(ps, list):
        for s in ps:
            if isinstance(s, dict):
                add(s.get("code"), s.get("name"))
            elif isinstance(s, (list, tuple)) and s:
                add(s[0], s[1] if len(s) > 1 else "")
            else:
                add(s)
    for m in cal.get("months") or []:
        for t in m.get("themes") or []:
            for s in t.get("stocks") or []:
                if s.get("pinkArrow"):
                    add(s.get("code"), s.get("name"))

    for nm in PINK_LISTS:
        path = plain_path(nm)
        if not path:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except Exception:
            continue
        for s in (doc.get("stocks") or []):
            if isinstance(s, dict):
                add(s.get("code"), s.get("name"))
    return out


def wanted_codes(keep: dict | None = None) -> tuple[list[str], dict[str, str], list[str]]:
    """화면에서 차트를 여는 종목 (코드, 공개 이름표)."""
    codes: list[str] = []
    names: dict[str, str] = {}

    def add(code, name=""):
        c = str(code or "").strip().upper()
        # 종목코드는 여섯 자리 — 우선주·신주인수권 등은 숫자+영문(예: 18064K)
        if len(c) != 6 or not all(ch.isdigit() or ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" for ch in c):
            return
        if c not in names:
            codes.append(c)
        if name:
            names.setdefault(c, str(name).strip())

    # 이미 자료에 있는 종목은 계속 갱신한다 — 비공개 평문이 없는 곳에서 다시 만들어도 차트가 비지 않게
    for c in (keep or {}):
        add(c)

    cal = jload_calendar()
    # 마스터 테마(153개 · 대장주·부대장주·3등주) 종목도 차트가 열리게 — 테마달력·테마 사전에서 누른다
    #   (2026-11-26 지시: "마스터 테마에 포함된 신규 종목 코드가 day125.json 에 빠져 있으면 채워라")
    for mt in (jload("master_themes.json").get("themes") or []):
        for s in (mt.get("stocks") or []):
            add(s.get("code"), s.get("stock") or s.get("name"))
    # *****
    for code, name in pink_codes(cal):
        add(code, name)
    for m in cal.get("months") or []:
        for t in m.get("themes") or []:
            for s in t.get("stocks") or []:
                add(s.get("code"), s.get("name"))

    news = jload("news.json")
    for it in ((news.get("upper_limits") or {}).get("items") or []):
        add(it.get("code"), it.get("name"))

    # 뉴스 탭 '오늘 뉴스가 부른 테마' 종목 칩 — 이름과 코드가 함께 온다
    for ln in (jload("news_themes.json").get("news_links") or []):
        for s in ln.get("stocks") or []:
            if isinstance(s, dict):
                add(s.get("code"), s.get("name"))

    # 비공개 탭(레이더·실전·오늘 종합 알림)의 종목도 차트가 열리게 — 시세만 싣고 이름·판단은 싣지 않는다
    for nm in ("radar.json", "popup.json", "hotbar.json", "hotbar_monthly.json"):
        for code in doc_codes(jload_private(nm)):
            add(code)

    # 기사 관련 종목(leaders)은 이름만 온다 — 아는 이름표에 있으면 바로, 없으면 나중에 코드를 찾는다
    by_name = {v: k for k, v in names.items() if v}
    loose: list[str] = []
    for key in ("flash", "issues", "articles"):
        for a in news.get(key) or []:
            for nm in a.get("leaders") or []:
                nm = str(nm).strip()
                if not nm:
                    continue
                c = by_name.get(nm)
                if c:
                    add(c, nm)
                elif nm not in loose:
                    loose.append(nm)
    return codes, names, loose


# 기사에 쓰는 이름과 종목명이 다른 것만 손으로 잇는다(자동완성이 다른 회사를 먼저 주는 경우)
ALIAS = {"네이버": "NAVER", "포스코": "POSCO홀딩스", "엘지": "LG", "에스케이": "SK"}


def resolve_names(names: list[str], workers: int = 8) -> dict[str, str]:
    """종목 이름 → 코드 (네이버 종목 자동완성). 이름이 정확히 같은 것만 쓴다."""
    out: dict[str, str] = {}

    def one(nm):
        want = ALIAS.get(nm, nm)
        url = "https://ac.stock.naver.com/ac?q=%s&target=stock" % urllib.parse.quote(want)
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=8) as resp:
                j = json.loads(resp.read().decode("utf-8", errors="replace"))
            for it in (j.get("items") or []):
                code, name = str(it.get("code") or ""), str(it.get("name") or "").strip()
                if name == want and code.isdigit() and len(code) == 6:
                    return nm, code
        except Exception:
            pass
        return nm, ""

    if not names:
        return out
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for nm, code in ex.map(one, names):
            if code:
                out[nm] = code
    return out


def ma_series(closes: list[float], n: int) -> list:
    """봉마다의 단순이동평균 배열 — 앞 n-1봉은 None(그 선이 아직 없다), 나머지는 원 단위 정수.

    차트는 봉 i 의 선 값을 series[i] 로 읽는다 — 길이는 넣은 봉 개수와 반드시 같다.
    """
    out: list = []
    run = 0.0
    for i, v in enumerate(closes):
        run += float(v or 0)
        if i >= n:
            run -= float(closes[i - n] or 0)
        out.append(int(round(run / n)) if i >= n - 1 else None)
    return out


def _norm_date(d: str) -> str:
    return "%s-%s-%s" % (d[:4], d[4:6], d[6:8])


def fetch_bars(code: str, timeframe: str = "day", count: int = 130):
    """네이버 fchart 봉 — 마지막 봉이 오늘(장중이면 진행 중인 봉)이다.

    봉 = [날짜, 시, 고, 저, 종, 거래량] · 날짜는 그 봉의 마지막 거래일.
    timeframe = day | week | month (month 는 네이버가 120개월까지만 준다 — 더 필요하면 fetch_month_long)
    """
    url = ("https://fchart.stock.naver.com/sise.nhn?symbol=%s&timeframe=%s&count=%d&requestType=0"
           % (code, timeframe, count))
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("euc-kr", errors="replace")
            root = ET.fromstring(raw)
            rows = []
            for item in root.findall(".//item"):
                p = item.attrib.get("data", "").split("|")
                if len(p) < 6 or "null" in p[1:5]:
                    continue
                d = p[0]
                try:
                    rows.append([_norm_date(d),
                                 float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5])])
                except ValueError:
                    continue
            rows = [r for r in rows if min(r[1:5]) > 0]
            if rows:
                return rows
        except Exception:
            time.sleep(0.3 * (attempt + 1))
    return []


_MONTH_RX = re.compile(r'\["(\d{8})"\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)')


def fetch_month_long(code: str, start: str = MONTH_START):
    """월봉 10년치 — fchart 는 월봉을 120개월까지만 주므로 siseJson 으로 2013년부터 받는다.

    월봉 120개월선은 120 + (차트에 실을 달) 만큼이 필요하다. 실패하면 [] 를 돌려주고
    부르는 쪽이 fchart 월봉(120개월)으로 대신한다.
    """
    end = datetime.now(KST).strftime("%Y%m%d")
    url = ("https://api.finance.naver.com/siseJson.naver?symbol=%s&requestType=1"
           "&startTime=%s&endTime=%s&timeframe=month" % (code, start, end))
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("euc-kr", errors="replace")
            rows = [[_norm_date(d), float(o), float(h), float(l), float(c), float(v)]
                    for d, o, h, l, c, v in _MONTH_RX.findall(raw)]
            rows = [r for r in rows if min(r[1:5]) > 0]
            if rows:
                return rows
        except Exception:
            time.sleep(0.3 * (attempt + 1))
    return []


def tf_pack(rows: list[list], keep: int, ma_n: int, ma_key: str):
    """주봉·월봉 묶음 — 최근 keep봉과 그 봉마다의 ma_n 이동평균(앞 구간은 null).

    값은 봉과 같은 자리 수로 맞춘 정수 배열. 파일을 가볍게 하려고 날짜는 YYMMDD 정수로 적는다.
    """
    rows = sorted([r for r in rows if r], key=lambda r: r[0])
    if len(rows) < 2:
        return None
    ser = ma_series([r[4] for r in rows], ma_n)
    cut = rows[-keep:]
    return {
        "d": [int(r[0][2:4] + r[0][5:7] + r[0][8:10]) for r in cut],
        "b": [[int(round(r[1])), int(round(r[2])), int(round(r[3])),
               int(round(r[4])), int(round(r[5]))] for r in cut],
        ma_key: ser[-len(cut):],
    }


def fetch_one(code: str, day_count: int):
    """한 종목 — 일봉·주봉·월봉을 한꺼번에 받는다(워커 안에서 도는 함수)."""
    day = fetch_bars(code, "day", day_count)
    week = fetch_bars(code, "week", WEEK_FETCH)
    month = fetch_month_long(code) or fetch_bars(code, "month", 160)
    return code, day, week, month


def encode(stock_rows: dict[str, list[list]], names: dict[str, str], days: int,
           week_rows: dict[str, list[list]] | None = None,
           month_rows: dict[str, list[list]] | None = None) -> dict:
    """종목별 최근 days봉 → {dates:[YYMMDD...], stocks:{code:{n,b,o0|x,ma240,w,m}}}"""
    week_rows = week_rows or {}
    month_rows = month_rows or {}
    cut: dict[str, list[list]] = {}
    for c, rows in stock_rows.items():
        rows = sorted(rows, key=lambda r: r[0])[-days:]
        # 상장 직후(봉이 몇 개 없는) 종목도 차트가 열려야 한다 — 2026-11-26 지시 "day125.json 누락 없이"
        #   신규상장 첫날은 일봉이 1개(1~2개)뿐이다 — 1봉부터 싣고, 그리는 쪽이 125봉 틀에 맞춰 깔끔하게 처리한다
        if len(rows) >= 1:
            cut[c] = rows
    axis = sorted({r[0] for rows in cut.values() for r in rows})
    at = {d: i for i, d in enumerate(axis)}
    stocks = {}
    for c, rows in cut.items():
        bars = [[int(round(r[1])), int(round(r[2])), int(round(r[3])),
                 int(round(r[4])), int(round(r[5]))] for r in rows]
        idx = [at[r[0]] for r in rows]
        rec = {"n": names.get(c, ""), "b": bars}
        if idx == list(range(idx[0], idx[0] + len(idx))):
            rec["o0"] = idx[0]                      # 날짜가 끊기지 않는다 — 시작 자리만
        else:
            rec["x"] = idx
        # 일봉 240선 — 420봉을 받아 재고 최근 days봉 자리만 남긴다
        all_day = sorted(stock_rows[c], key=lambda r: r[0])
        rec["ma240"] = ma_series([r[4] for r in all_day], 240)[-len(rows):]
        # 주봉 52주(+240주선) · 월봉 30개월(+120개월선) — 차트 안 주기 전환용
        w = tf_pack(week_rows.get(c) or [], WEEK_KEEP, 240, "ma240")
        if w:
            rec["w"] = w
        m = tf_pack(month_rows.get(c) or [], MONTH_KEEP, 120, "ma120")
        if m:
            rec["m"] = m
        stocks[c] = rec
    return {"dates": [int(d[2:4] + d[5:7] + d[8:10]) for d in axis], "stocks": stocks, "days": days}


def _last_date(old: dict, code: str) -> str:
    """자료 속 그 종목의 마지막 봉 날짜(YYYY-MM-DD) — 증분 갱신에서 '오늘 봉이 왔는지' 판단용."""
    st = (old.get("stocks") or {}).get(code)
    dates = old.get("dates") or []
    if not st or not st.get("b"):
        return ""
    xs = st.get("x") or [((st.get("o0") or 0) + i) for i in range(len(st["b"]))]
    n = dates[xs[-1]] if xs[-1] < len(dates) else 0
    return "20%02d-%02d-%02d" % (n // 10000, (n // 100) % 100, n % 100) if n else ""


def hot_codes(old: dict, today: str) -> list[str]:
    """오늘 화면에 먼저 뜨는 종목 — 상한가·뉴스 테마 종목부터 봉을 새로 받는다(증분 갱신 순서)."""
    hot: list[str] = []
    news = jload("news.json")
    for it in ((news.get("upper_limits") or {}).get("items") or []):
        c = str(it.get("code") or "")
        if c:
            hot.append(c)
    for ln in (jload("news_themes.json").get("news_links") or []):
        for s in ln.get("stocks") or []:
            c = str((s or {}).get("code") or "")
            if c:
                hot.append(c)
    out, seen = [], set()
    for c in hot:
        if c in seen:
            continue
        seen.add(c)
        if _last_date(old, c) < today:
            out.append(c)
    return out


def public_hot_codes(today: str) -> set:
    """화면에 먼저 뜨는 종목 — 오늘 상한가 · 오늘 뉴스 테마 · 최근 60일 상한가가 있던 달력 종목.

    작은 판(day125_hot.json)에 담을 코드. 종목을 눌렀을 때 8MB 전체를 기다리지 않게 한다.
    """
    out: set = set()
    news = jload("news.json")
    name_to_code = jload("day125.json").get("names") or {}
    for it in ((news.get("upper_limits") or {}).get("items") or []):
        if it.get("code"):
            out.add(str(it["code"]))
    for key in ("flash", "issues", "articles"):
        for a in news.get(key) or []:
            for nm in a.get("leaders") or []:
                c = name_to_code.get(str(nm).strip())
                if c:
                    out.add(str(c))
    for ln in (jload("news_themes.json").get("news_links") or []):
        for s in ln.get("stocks") or []:
            if (s or {}).get("code"):
                out.add(str(s["code"]))
    try:
        cut = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=60)).strftime("%Y-%m-%d")
    except ValueError:
        cut = ""
    for m in (jload_calendar().get("months") or []):
        for t in (m.get("themes") or []):
            for s in (t.get("stocks") or []):
                dates = [str(x) for x in (s.get("dates") or [])]
                if dates and max(dates) >= cut and s.get("code"):
                    out.add(str(s["code"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=125)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--count", type=int, default=0, help="받아올 일봉 수(기본 days+240, 최소 420)")
    ap.add_argument("--min-age-min", type=int, default=0)
    ap.add_argument("--max-codes", type=int, default=0)
    ap.add_argument("--fill-missing", action="store_true",
                    help="이미 자료에 있는 종목은 다시 받지 않고, 새로 생긴 종목만 받는다(매시 갱신용)")
    ap.add_argument("--hot-refresh", type=int, default=0,
                    help="오늘 상한가·뉴스 테마 종목 중 오늘 봉이 아직 없는 종목을 이 수만큼 새로 받는다")
    ap.add_argument("--out", default="", help="다른 파일로 저장(시험용) — 기본은 data/day125.json")
    args = ap.parse_args()
    count = args.count or max(args.days + 240, 420)
    out_path = args.out or OUT

    old = {}
    try:
        with open(out_path, encoding="utf-8") as f:
            old = json.load(f)
    except Exception:
        old = {}
    if args.min_age_min and old.get("generated_at"):
        try:
            age = (datetime.now(KST) - datetime.fromisoformat(old["generated_at"])).total_seconds() / 60
            if age < args.min_age_min:
                print("일봉 125봉 자료가 %d분 전 자료라 건너뜁니다 (%s)" % (int(age), old["generated_at"]))
                return
        except Exception:
            pass

    codes, names, loose = wanted_codes(old.get("stocks") or {})
    # 예전 자료에 이미 공개돼 있던 이름은 그대로 이어 쓴다(공개된 정보 — 새로 드러나는 것은 없다)
    for nm, c in (old.get("names") or {}).items():
        if c and nm:
            names.setdefault(str(c), str(nm))
    if loose and not args.max_codes:
        got = resolve_names(loose)
        for nm, c in got.items():
            if c not in names:
                names[c] = nm
                codes.append(c)
    if args.max_codes:
        codes = codes[:args.max_codes]
    # 같은 코드가 여러 자료(달력·뉴스·핫바)에서 이름 없이 반복해 들어올 수 있다 — 한 번씩만 받는다
    codes = list(dict.fromkeys(codes))
    if not codes:
        print("공개 화면에 종목이 없습니다 — data/*.json 을 확인하세요", file=sys.stderr)
        return

    t0 = time.time()
    old_stocks = old.get("stocks") or {}
    today = datetime.now(KST).strftime("%Y-%m-%d")
    if args.fill_missing:
        need = [c for c in codes if c not in old_stocks]
        hot = hot_codes(old, today) if args.hot_refresh else []
        fetch = need + [c for c in hot if c not in need][:args.hot_refresh]
        print("증분 갱신 — 새 종목 %d · 오늘 봉 없는 종목 %d · 건너뛰는 종목 %d"
              % (len(need), len(fetch) - len(need), len(codes) - len(fetch)), flush=True)
    else:
        fetch = codes
    if args.fill_missing and not fetch:
        print("새로 채울 종목이 없습니다 — 일봉 자료를 그대로 둡니다(%s)" % today, flush=True)
        return

    got: dict[str, list[list]] = {}
    got_w: dict[str, list[list]] = {}
    got_m: dict[str, list[list]] = {}
    miss: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for c, day, week, month in ex.map(lambda x: fetch_one(x, count), fetch):
            if day:
                got[c] = day
            else:
                miss.append(c)
            if week:
                got_w[c] = week
            if month:
                got_m[c] = month

    # 이미 있던 봉은 날짜로 합친다 — 오늘 못 받은 종목도 어제까지의 봉은 남는다
    old_dates = old.get("dates") or []
    old_stocks = old.get("stocks") or {}
    merged: dict[str, list[list]] = {}
    for c in codes:
        rows = list(got.get(c) or [])
        o = old_stocks.get(c)
        if o and o.get("b"):
            seen = {r[0] for r in rows}
            idx = o.get("x") or (list(range(o.get("o0", 0), o.get("o0", 0) + len(o["b"]))))
            for k, b in enumerate(o["b"]):
                if k >= len(idx) or idx[k] >= len(old_dates):
                    continue
                n = old_dates[idx[k]]
                day = "20%02d-%02d-%02d" % (n // 10000, (n // 100) % 100, n % 100)
                if day in seen:
                    continue
                rows.append([day, b[0], b[1], b[2], b[3], b[4], b[5] if len(b) > 5 else 0])
        if rows:
            merged[c] = rows

    enc = encode(merged, names, args.days,
                 week_rows={c: (got_w.get(c) or []) for c in codes},
                 month_rows={c: (got_m.get(c) or []) for c in codes})
    if not enc["stocks"]:
        print("받은 종목이 없습니다 — 네트워크를 확인하세요", file=sys.stderr)
        sys.exit(1)

    # 주봉·월봉을 이번에 못 받은 종목은 지난 자료의 봉을 그대로 둔다(차트가 주·월봉에서 비지 않게)
    for c, rec in enc["stocks"].items():
        o = old_stocks.get(c) or {}
        for k in ("w", "m"):
            if k not in rec and o.get(k):
                rec[k] = o[k]
        # 증분 갱신에서 안 받은 종목은 지난 240일선을 그대로 둔다
        #   (오늘 받은 125봉만으로 240일선을 다시 재면 전부 null 이 되어 선이 사라진다)
        if c not in got and o.get("ma240") and len(o["ma240"]) == len(rec["b"]):
            rec["ma240"] = o["ma240"]

    as_of = ""
    for c, rows in merged.items():
        if c in enc["stocks"]:
            as_of = max(as_of, max(r[0] for r in rows))
    doc = {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "as_of": as_of,
        "days": args.days,
        "dates": enc["dates"],
        "stocks": enc["stocks"],
        "names": {v: c for c, v in names.items() if c in enc["stocks"] and v},
    }
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, out_path)

    # 화면에 먼저 뜨는 종목만 담은 작은 판(day125_hot.json) — 종목을 누를 때 8MB 전부를 기다리지 않게.
    # *****
    hot = public_hot_codes(as_of or today)
    hot_doc = {
        "generated_at": doc["generated_at"],
        "as_of": as_of,
        "days": args.days,
        "dates": enc["dates"],
        "stocks": {c: {k: v for k, v in rec.items() if k in ("n", "b", "o0", "x", "ma240")}
                   for c, rec in enc["stocks"].items() if c in hot},
        "names": {nm: c for nm, c in doc["names"].items() if c in hot},
    }
    hot_path = os.path.join(os.path.dirname(out_path), "day125_hot.json")
    htmp = hot_path + ".tmp"
    with open(htmp, "w", encoding="utf-8") as f:
        json.dump(hot_doc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(htmp, hot_path)
    bars_n = sum(len(v["b"]) for v in doc["stocks"].values())
    w_n = sum(1 for v in doc["stocks"].values() if v.get("w"))
    m_n = sum(1 for v in doc["stocks"].values() if v.get("m"))
    ma_n = sum(1 for v in doc["stocks"].values()
               if any(x is not None for x in (v.get("ma240") or [])))
    print("일봉 125봉 차트 %d종목 · 봉 %d · %s · %.0f초 · %.0fKB%s"
          % (len(doc["stocks"]), bars_n, as_of, time.time() - t0,
             os.path.getsize(out_path) / 1024,
             (" · 못 받은 종목 %d(이전 봉 유지)" % len(miss)) if miss else ""), flush=True)
    print("  240일선 %d종목 · 주봉 %d종목 · 월봉 %d종목" % (ma_n, w_n, m_n), flush=True)
    print("  먼저 뜨는 종목 %d개 -> %s (%.0fKB)"
          % (len(hot_doc["stocks"]), hot_path, os.path.getsize(hot_path) / 1024), flush=True)
    NR.seal_all()   # data/*.json 전체를 잠근다(평문은 private-plain/data)


if __name__ == "__main__":
    main()
