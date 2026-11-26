#!/usr/bin/env python3
"""*****"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nr_data as NR  # noqa: E402
DATA = NR.plain_dir()
KST = timezone(timedelta(hours=9))

UPPER_RATE = 0.29        # *****
PULL_MIN = -0.40         # *****
PULL_MAX = -0.08         # *****
HOT_GAIN = 0.45          # *****
HOT_MA = 0.25            # *****
DEEP_DD = -0.40          # 125봉 최고 대비 이만큼 빠졌으면 '바닥권'
STAGE_LABEL = {
    1: "1단계 · 상한가 당일", 2: "2단계 · 초기 분출", 3: "3단계 · 상자 버팀",
    4: "4단계 · 눌림 매수 자리", 5: "5단계 · 전고 돌파", 6: "6단계 · 분출 보유",
    7: "7단계 · 숨 고르기 보유", 8: "8단계 · 과열 매도", 9: "9단계 · 하락 멈춤 대기",
    10: "10단계 · 재출발 대기",
}


# ------------------------------------------------------------------ 자료 읽기
def load_day125(path: str = "") -> dict:
    with open(path or os.path.join(DATA, "day125.json"), encoding="utf-8") as f:
        return json.load(f)


def bars_of(doc: dict, code: str) -> list[list]:
    """종목코드 → [[o,h,l,c,v], ...] (오래된 것부터). 없으면 빈 목록."""
    rec = (doc.get("stocks") or {}).get(str(code))
    return list((rec or {}).get("b") or [])


def name_of(doc: dict, code: str) -> str:
    rec = (doc.get("stocks") or {}).get(str(code)) or {}
    return str(rec.get("n") or "")


def date_of(doc: dict, code: str, back: int = 0) -> str:
    """그 종목의 뒤에서 back번째 봉 날짜(YYYY-MM-DD)."""
    rec = (doc.get("stocks") or {}).get(str(code)) or {}
    bars = rec.get("b") or []
    if not bars:
        return ""
    dates = doc.get("dates") or []
    idx = rec.get("x") or [((rec.get("o0") or 0) + i) for i in range(len(bars))]
    k = len(bars) - 1 - back
    if k < 0 or k >= len(idx) or idx[k] >= len(dates):
        return ""
    n = int(dates[idx[k]])
    return "20%02d-%02d-%02d" % (n // 10000, (n // 100) % 100, n % 100)


# ------------------------------------------------------------------ 계산
def ma(values: list, n: int):
    if len(values) < n or n <= 0:
        return None
    return sum(values[-n:]) / n


def judge(bars: list[list]) -> dict:
    """한 종목의 125봉 → 단계 판정. 봉이 모자라면 단계 없이 사유만 준다."""
    bars = [b for b in (bars or []) if b and len(b) >= 5]
    n = len(bars)
    if n < 5:
        return {"stage10": 0, "stage_txt": "", "why": "일봉이 모자라 판정하지 않음",
                "dd": None, "val20": None, "lu_ago": None, "pos125": None}
    closes = [float(b[3]) for b in bars]
    highs = [float(b[1]) for b in bars]
    lows = [float(b[2]) for b in bars]
    vols = [float(b[4]) for b in bars]
    close = closes[-1]
    ma20, ma60 = ma(closes, 20), ma(closes, 60)
    hi125, lo125 = max(highs), min(lows)
    dd = (close / hi125 - 1.0) if hi125 else None
    pos = ((close - lo125) / (hi125 - lo125)) if hi125 > lo125 else 0.5
    val20 = sum(c * v for c, v in zip(closes[-20:], vols[-20:])) / min(20, n) / 1e8

    # *****
    anchor = None
    for i in range(1, n):
        prev = closes[i - 1]
        if prev > 0 and highs[i] / prev - 1.0 >= UPPER_RATE:
            anchor = i
    if anchor is None:
        ago = None
        anchor_close = anchor_high = None
    else:
        ago = n - 1 - anchor
        anchor_close = closes[anchor]
        anchor_high = max(highs[anchor:])

    def out(stage: int, why: str) -> dict:
        return {"stage10": stage, "stage_txt": STAGE_LABEL[stage], "why": why,
                "dd": round(dd, 4) if dd is not None else None,
                "val20": round(val20, 1), "lu_ago": ago, "pos125": round(pos, 3),
                "ma20": round(ma20, 1) if ma20 else None, "ma60": round(ma60, 1) if ma60 else None,
                "close": round(close, 1), "anchor_high": round(anchor_high, 1) if anchor_high else None,
                "bars": n}

    above20 = ma20 is not None and close >= ma20
    trend_up = ma20 is not None and ma60 is not None and ma20 >= ma60

    if anchor is None:
        # 닻이 없는 종목 — 추세와 바닥만 본다
        if pos >= 0.85 and above20 and trend_up:
            return out(7, "상한가 없이도 전고 부근 상승 유지")
        if above20 and trend_up:
            return out(6, "20일선 위 상승 흐름(상한가 없음)")
        if dd is not None and dd <= DEEP_DD and above20:
            return out(10, "큰 하락 뒤 바닥에서 20일선 회복")
        return out(9, "상한가 이력 없는 바닥권 — 대기")

    gain = close / anchor_close - 1.0 if anchor_close else 0.0
    pull = close / anchor_high - 1.0 if anchor_high else 0.0

    if ago <= 0:
        return out(1, "오늘 상한가 — 초기 분출")
    if ago <= 2:
        return out(2, "상한가 %d봉 전 — 초기 분출" % ago)
    if close > anchor_high * 1.02:
        if gain >= HOT_GAIN or (ma20 and close >= ma20 * (1 + HOT_MA)):
            return out(8, "닻 대비 +%d%% 과열 — 분할 매도 자리" % round(gain * 100))
        if gain >= 0.20:
            return out(6, "전고 돌파 뒤 분출(닻 대비 +%d%%)" % round(gain * 100))
        return out(5, "전고 돌파 직후 — 보유")
    if PULL_MIN <= pull <= PULL_MAX and above20:
        return out(4, "닻 고점 대비 %d%% 눌림 뒤 20일선 회복 — 매수 자리" % round(pull * 100))
    if pull > PULL_MAX and above20:
        return out(3, "닻 뒤 조정 없이 버팀 — 상자")
    if pull > PULL_MAX and not above20:
        return out(3, "닻 뒤 상자 아래 — 20일선 회복 확인 필요")
    if dd is not None and dd <= DEEP_DD:
        if above20 and pos <= 0.5:
            return out(10, "닻 뒤 큰 하락(고점 %d%%) 바닥에서 20일선 회복" % round(dd * 100))
        return out(9, "닻 뒤 큰 하락(고점 %d%%) — 하락 멈춤 대기" % round(dd * 100))
    if above20:
        return out(7, "닻 뒤 20일선 위 숨 고르기")
    return out(9, "닻 뒤 20일선 아래 — 대기")


def judge_code(doc: dict, code: str) -> dict:
    r = judge(bars_of(doc, code))
    r.update(code=str(code), name=name_of(doc, code), date=date_of(doc, code))
    if r.get("lu_ago") is not None:
        r["anchor_date"] = date_of(doc, code, int(r["lu_ago"]))
    else:
        r["anchor_date"] = ""
    r["stage10_late"] = 1 if (r.get("lu_ago") or 0) >= 15 else 0
    return r


# ------------------------------------------------------------------ 목록 만들기
def board_codes(doc: dict, max_bars: int = 400) -> list[str]:
    """9·10단계 대기 후보 — 상한가 이력이 있는 종목(달력·마스터 사전) 위주."""
    out: list[str] = []
    cal_path = os.path.join(DATA, "calendar.json")
    try:
        with open(cal_path, encoding="utf-8") as f:
            cal = json.load(f)
        for m in cal.get("months") or []:
            for t in m.get("themes") or []:
                for s in t.get("stocks") or []:
                    c = str(s.get("code") or "")
                    if c and c not in out:
                        out.append(c)
    except Exception:  # noqa: BLE001
        pass
    try:
        with open(os.path.join(DATA, "master_themes.json"), encoding="utf-8") as f:
            mt = json.load(f)
        for c in (mt.get("code_index") or {}):
            if c not in out:
                out.append(c)
    except Exception:  # noqa: BLE001
        pass
    stocks = doc.get("stocks") or {}
    return [c for c in out if c in stocks][:max_bars]


def scan(doc: dict | None = None, limit: int = 40, stages=(9, 10)) -> list[dict]:
    """9·10단계(재부각 대기) 목록 — 10단계를 먼저, 그다음 고점에서 많이 빠진 순."""
    doc = doc or load_day125()
    rows = []
    for c in board_codes(doc):
        try:
            r = judge_code(doc, c)
        except Exception:  # noqa: BLE001
            continue
        if r.get("stage10") in stages and r.get("lu_ago") is not None:
            rows.append(r)
    rows.sort(key=lambda r: (0 if r["stage10"] == 10 else 1, (r.get("dd") if r.get("dd") is not None else 0),
                             -int(r.get("val20") or 0)))
    return rows[:limit]


def main() -> None:
    ap = argparse.ArgumentParser(description="1~10단계 자체 판정(125봉 + 달력)")
    ap.add_argument("--codes", default="", help="종목코드 쉼표 목록")
    ap.add_argument("--scan", action="store_true", help="9·10단계 재부각 대기 목록")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--day125", default="", help="125봉 자료 경로(기본 data/day125.json)")
    ap.add_argument("--json", default="", help="결과를 이 파일로 저장")
    args = ap.parse_args()

    doc = load_day125(args.day125)
    rows = []
    if args.scan:
        rows = scan(doc, args.limit)
    else:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
        if not codes:
            raise SystemExit("--codes 또는 --scan 이 필요합니다")
        rows = [judge_code(doc, c) for c in codes]
    for r in rows:
        print("%-8s %-12s %-2s %-22s 닻 %s(%s) dd %s%% 거래대금 %s억"
              % (r.get("code"), (r.get("name") or "")[:12], r.get("stage10"), r.get("stage_txt") or "",
                 r.get("lu_ago"), r.get("anchor_date") or "-",
                 round((r.get("dd") or 0) * 100, 1) if r.get("dd") is not None else "-",
                 r.get("val20")))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"generated_at": datetime.now(KST).isoformat(timespec="seconds"),
                       "count": len(rows), "rows": rows}, f, ensure_ascii=False, indent=1)
        print("[ok] %s" % args.json)


if __name__ == "__main__":
    main()
