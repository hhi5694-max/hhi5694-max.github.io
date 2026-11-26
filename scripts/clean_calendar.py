#!/usr/bin/env python3
"""*****"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
BASIC = "https://m.stock.naver.com/api/stock/{code}/basic"
FIN = "https://m.stock.naver.com/api/stock/{code}/finance/annual"
KST = timezone(timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nr_data as NR  # noqa: E402
DATA = NR.plain_path("calendar.json")
WORKERS = 16
PREF_NAME = re.compile(r"(?:\d)?우(?:B|C)?$")
CLEAN_RULE = ("과거 달력 정리(2026-11-26) — 관리종목·거래정지·투자경고/위험·SPAC·완전자본잠식 종목을 뺐다. "
              "우선주는 남겼다(같은 불건전 사유에 걸리면 예외로 뺀다). 투자주의(시장경보 01)는 남겼다.")


def _get(url: str, tries: int = 3, timeout: int = 12) -> dict:
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*",
                                                       "Referer": "https://m.stock.naver.com/"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.2)
    raise RuntimeError(str(last))


def _num(v):
    s = str(v if v is not None else "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def status_of(code: str) -> dict:
    """공개 API 로 그 종목의 지금 상태를 읽는다(실패하면 error 만 남긴다)."""
    out = {"code": code}
    try:
        d = _get(BASIC.format(code=code))
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:100]
        return out
    alert = d.get("marketAlertType") or {}
    out["name"] = d.get("stockName") or ""
    out["isManagement"] = bool(d.get("isManagement"))
    out["alertCode"] = str(alert.get("code") or "")
    out["alert"] = alert.get("text") or ""
    out["tradableStatus"] = str(d.get("tradableStatus") or "")
    out["tradeStop"] = (d.get("tradeStopType") or {}).get("name") or ""
    out["endType"] = d.get("stockEndType") or ""
    return out


def debt_ratio_of(code: str):
    """가장 최근 회계연도 부채비율(%). 자본총계가 0 이하면 음수로 온다."""
    try:
        d = _get(FIN.format(code=code))
    except Exception:  # noqa: BLE001
        return None
    for r in (d.get("financeInfo") or {}).get("rowList") or []:
        if r.get("title") != "부채비율":
            continue
        nums = []
        for k, v in (r.get("columns") or {}).items():
            x = _num(v.get("value"))
            if x is not None:
                nums.append((k, x))
        if nums:
            nums.sort()
            return nums[-1][1]
    return None


def is_pref(code: str, name: str) -> bool:
    return (str(code)[-1] != "0") or bool(PREF_NAME.search(name or ""))


def reasons_of(st: dict, name: str) -> list:
    """이 종목을 달력에서 빼야 하는 이유(없으면 빈 목록)."""
    why = []
    if st.get("error"):
        return why                       # 못 읽은 종목은 건드리지 않는다(자료를 지우지 않는다)
    if st.get("isManagement"):
        why.append("관리종목")
    if st.get("alertCode") in ("02", "03"):
        why.append("시장경보 " + (st.get("alert") or st.get("alertCode")))
    if st.get("tradableStatus") and st["tradableStatus"] != "tradable":
        why.append("거래상태 " + st["tradableStatus"])
    if st.get("tradeStop") and st["tradeStop"] != "TRADING":
        why.append("거래정지 " + st["tradeStop"])
    if any(k in (name or "") for k in ("스팩", "SPAC", "기업인수목적")) or "SPAC" in (name or "").upper():
        why.append("SPAC")
    dr = st.get("debtRatio")
    if dr is not None and dr < 0:
        why.append("완전자본잠식(부채비율 %.1f%%)" % dr)
    return why


def collect_stocks(cal: dict) -> tuple[list, dict]:
    codes, names = [], {}
    for m in cal.get("months") or []:
        for t in m.get("themes") or []:
            for s in t.get("stocks") or []:
                c = str(s.get("code") or "").upper()
                if not c:
                    continue
                if c not in names:
                    names[c] = s.get("name") or ""
                    codes.append(c)
    return codes, names


def scan(codes: list, names: dict) -> dict:
    """모든 종목의 상태 — 불건전에 걸린 것만 부채비율까지 본다."""
    st: dict = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for r in ex.map(status_of, codes):
            st[r["code"]] = r
    print("상태 확인 %d종목 %.0f초" % (len(st), time.time() - t0), file=sys.stderr)
    rest = [c for c in codes if not reasons_of(st[c], names.get(c) or st[c].get("name") or "")]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for c, dr in zip(rest, ex.map(debt_ratio_of, rest)):
            st[c]["debtRatio"] = dr
    print("부채비율 확인 %d종목 %.0f초" % (len(rest), time.time() - t0), file=sys.stderr)
    return st


def total_lu(cal: dict) -> dict:
    """종목코드 → 달력 전체의 상한가 날짜(중복 없이) — 대장주 사유의 '통산 N회'."""
    seen: dict = {}
    for m in cal.get("months") or []:
        for t in m.get("themes") or []:
            for s in t.get("stocks") or []:
                c = str(s.get("code") or "")
                seen.setdefault(c, set()).update(str(d) for d in (s.get("dates") or []))
    return {c: sorted(v) for c, v in seen.items()}


def clean(cal: dict, st: dict, names: dict) -> tuple[dict, list]:
    removed = []
    for m in cal.get("months") or []:
        for t in m.get("themes") or []:
            for s in t.get("stocks") or []:
                c = str(s.get("code") or "").upper()
                why = reasons_of(st.get(c) or {}, s.get("name") or names.get(c) or "")
                if why:
                    removed.append({"month": m.get("month"), "theme": t.get("name"),
                                    "code": c, "name": s.get("name") or "",
                                    "reasons": why,
                                    "pink": 1 if s.get("pinkArrow") else 0})
    drop = {r["code"] for r in removed}
    lu_all = total_lu(cal)

    out_months = []
    for m in cal.get("months") or []:
        themes = []
        for t in m.get("themes") or []:
            stocks = [s for s in (t.get("stocks") or []) if str(s.get("code") or "").upper() not in drop]
            if not stocks:
                continue                     # 종목이 하나도 안 남은 테마는 지운다
            t = dict(t)
            t["stocks"] = stocks
            t["count"] = len(stocks)
            # *****
            lead = t.get("leader") or {}
            lead_code = str(lead.get("code") or "")
            codes_now = [str(s.get("code") or "") for s in stocks]
            if lead_code not in codes_now and codes_now:
                best = max(stocks, key=lambda s: (len(s.get("dates") or []),
                                                  (s.get("dates") or [""])[-1],
                                                  str(s.get("name") or "")))
                lc = str(best.get("code") or "")
                dates = sorted(str(d) for d in (best.get("dates") or []))
                why = "그 달 상한가 %d회%s · 통산 %d회" % (
                    len(dates), ("(%s부터)" % dates[0]) if dates else "",
                    len(lu_all.get(lc) or []))
                t["leader"] = {"name": best.get("name") or "", "code": lc, "why": why}
                for s in stocks:
                    s["leader"] = 1 if str(s.get("code") or "") == lc else 0
                lead_code = lc
            rep = t.get("rep") or {}
            if str(rep.get("code") or "") not in codes_now and lead_code:
                lead_rec = next((s for s in stocks if str(s.get("code") or "") == lead_code), None)
                if lead_rec:
                    dates = sorted(str(d) for d in (lead_rec.get("dates") or []))
                    t["rep"] = {"name": lead_rec.get("name") or "", "code": lead_code,
                                "date": dates[0] if dates else ""}
            themes.append(t)
        if not themes:
            continue
        m = dict(m)
        m["themes"] = themes
        m["theme_count"] = len(themes)
        kind_count: dict = {}
        for t in themes:
            k = t.get("kind") or "동반테마"
            kind_count[k] = kind_count.get(k, 0) + 1
        m["kind_count"] = kind_count
        m["stock_count"] = sum(len(t.get("stocks") or []) for t in themes)
        m["leader_count"] = sum(1 for t in themes if (t.get("leader") or {}).get("code"))
        m["pink_count"] = sum(1 for t in themes for s in (t.get("stocks") or []) if s.get("pinkArrow"))
        out_months.append(m)

    out = dict(cal)
    out["months"] = out_months
    out["theme_total"] = sum(m["theme_count"] for m in out_months)
    kind_total: dict = {}
    for m in out_months:
        for k, v in (m.get("kind_count") or {}).items():
            kind_total[k] = kind_total.get(k, 0) + v
    out["kind_total"] = kind_total
    out["stock_total"] = sum(m["stock_count"] for m in out_months)
    pink = [s for m in out_months for t in m["themes"] for s in (t.get("stocks") or []) if s.get("pinkArrow")]
    out["pink_total"] = len(pink)
    out["pink_stocks"] = len({str(s.get("code")) for s in pink})
    rng = dict(out.get("range") or {})
    if out_months:
        rng["from"] = out_months[0].get("month")
        rng["to"] = out_months[-1].get("month")
        rng["months"] = len(out_months)
    out["range"] = rng
    out["cleaned_at"] = datetime.now(KST).isoformat(timespec="seconds")
    out["clean_rule"] = CLEAN_RULE
    return out, removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="파일을 고치지 않고 뺄 목록만 본다")
    ap.add_argument("--report", default="", help="뺀 종목·사유를 이 JSON 파일로 남긴다")
    ap.add_argument("--path", default=DATA)
    args = ap.parse_args()

    with open(args.path, encoding="utf-8") as f:
        cal = json.load(f)
    codes, names = collect_stocks(cal)
    print("달력 종목 %d" % len(codes), file=sys.stderr)
    st = scan(codes, names)
    new_cal, removed = clean(cal, st, names)
    kept = len(codes) - len({r["code"] for r in removed})
    print("뺄 종목 %d · 남길 종목 %d · 테마 %d→%d · 달력 종목 %d→%d"
          % (len({r["code"] for r in removed}), kept,
             cal.get("theme_total") or 0, new_cal["theme_total"],
             cal.get("stock_total") or 0, new_cal["stock_total"]), file=sys.stderr)
    for r in removed:
        print("  %s %s (%s) · %s" % (r["code"], r["name"], r["month"], " / ".join(r["reasons"])), file=sys.stderr)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump({"cleaned_at": new_cal["cleaned_at"], "removed": removed}, f,
                      ensure_ascii=False, indent=1)
    if args.dry_run:
        return
    tmp = args.path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        # 원래 달력 자료와 같은 촬밀한 모양(구분자에 공백 없음) — 표면만 다듬고 내용만 바뀌게
        json.dump(new_cal, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    os.replace(tmp, args.path)
    print("저장 %s" % args.path, file=sys.stderr)
    NR.seal_all()


if __name__ == "__main__":
    main()
