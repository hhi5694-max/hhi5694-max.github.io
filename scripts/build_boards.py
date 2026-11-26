#!/usr/bin/env python3
"""*****"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import stage10_local as S10          # *****
import nr_data as NR  # noqa: E402  (평문 사본·잠금 공용)
DATA = os.path.join(ROOT, "data")
PLAIN_DIR = os.path.join(os.path.dirname(ROOT), "private-plain")
BOOK = os.path.join(PLAIN_DIR, "picks_results.json")
CODE_FILE = os.path.join(PLAIN_DIR, ".picks_code")

PBKDF2_ITER = 100000          # index.html 의 HOT_ITER 와 같아야 한다
KST = timezone(timedelta(hours=9))
WD = "월화수목금토일"

TIER_COLORS = ("#4f8cff", "#ff8b4f", "#39d98a", "#c9a2ff", "#ffd166", "#4fd8ff", "#ff6b9a")


# ------------------------------------------------------------------ 작은 유틸
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


def seal(payload, pw: str) -> dict:
    """브라우저 Web Crypto 가 그대로 풀 수 있는 형태(AES-256-GCM · PBKDF2-SHA256 10만회)."""
    from Crypto.Cipher import AES
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    key = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, PBKDF2_ITER, dklen=32)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ct, tag = AES.new(key, AES.MODE_GCM, nonce=iv).encrypt_and_digest(raw)
    b64 = lambda x: base64.b64encode(x).decode("ascii")  # noqa: E731
    return {"enc": 1, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct + tag)}


def now_kst() -> datetime:
    return datetime.now(KST)


def date_text(date: str) -> str:
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
        return f"{dt:%Y.%m.%d} ({WD[dt.weekday()]})"
    except ValueError:
        return date


def pct_of(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ 장부 읽기
def today_record(book: dict, date: str) -> dict:
    for month in (book.get("months") or {}).values():
        rec = month.get(date)
        if rec:
            return rec
    return {}


def pick_card(p: dict) -> dict:
    """resCard() 가 그대로 읽는 모양 — 종목 카드 · 등락률 · 근거 · 기준가→현재가."""
    status = str(p.get("status") or "진행")
    pct = pct_of(p.get("pct"))
    if status == "대기":
        pct = None                    # *****
    return {
        "code": str(p.get("code") or ""),
        "name": str(p.get("name") or ""),
        "market": str(p.get("market") or ""),
        "theme": str(p.get("theme") or ""),
        "tier": str(p.get("tier") or ""),          # *****
        "reason": str(p.get("reason") or ""),
        "pick_time": str(p.get("pick_time") or ""),
        "ref_kind": str(p.get("ref_kind") or "기준가"),
        "ref_price": p.get("ref_price"),
        "current_price": p.get("current_price"),
        "pct": pct,
        "status": status,
        # *****
        "stage10": 0, "stage_txt": "", "stage_why": "",
        "dd": None, "val20": None, "lu_ago": None, "stage10_late": 0,
    }


def group_by_theme(picks: list, pre_codes: set) -> list:
    """처음 나온 순서대로 테마 묶음 — 비어 있으면 '개별'."""
    order, by = [], {}
    for p in picks:
        th = (p.get("theme") or "").strip() or "개별"
        if th not in by:
            by[th] = []
            order.append(th)
        by[th].append(p)
    out = []
    for th in order:
        rows = by[th]
        n_pre = sum(1 for p in rows if p["code"] in pre_codes)
        n_int = sum(1 for p in rows if p.get("_leg") == "intraday")
        n_aft = sum(1 for p in rows if p.get("_leg") == "aftermarket")
        bits = []
        if n_pre:
            bits.append(f"장전 {n_pre}")
        if n_int:
            bits.append(f"장중 {n_int}")
        if n_aft:
            bits.append(f"장후 {n_aft}")
        out.append({"key": th, "title": th, "note": " · ".join(bits), "picks": rows})
    return out


# ------------------------------------------------------------------ 네 벌
def build_hotbar(date: str, pre: list, intra: list, after: list, session: str) -> dict:
    stamp = now_kst()
    n = len(pre) + len(intra) + len(after)
    n_core = sum(1 for p in intra if p.get("tier") == "core")
    n_extra = sum(1 for p in intra if p.get("tier") == "extra")
    intra_note = "기준 포착가 · 장중에 잡은 자리"
    if n_extra:
        intra_note += f" · 핵심 {n_core} · 추가 {n_extra}"
    return {
        "v": 3,
        "kind": "picks",
        "generated_at": stamp.isoformat(timespec="seconds"),
        "generated_at_kst": stamp.strftime("%Y.%m.%d %H:%M"),
        "base_date": date,
        "base_date_text": f"{date_text(date)} {session} 기준 · 장전 {len(pre)} · 장중 {len(intra)} · 장후 {len(after)}",
        "session": session,
        "counts": {"premarket": len(pre), "intraday": len(intra), "aftermarket": len(after), "picks": n,
                   "intraday_core": n_core, "intraday_extra": n_extra},
        "boards": [
            {"key": "premarket", "title": "🌅 장전픽", "note": "기준 전일 종가 · 아침에 고른 자리",
             "empty": "오늘 아침에는 조건에 맞는 자리가 없었습니다.", "picks": pre},
            {"key": "intraday", "title": "⚡ 장중픽", "note": intra_note,
             "empty": "오늘은 장중에 새로 잡힌 자리가 없습니다.", "picks": intra},
            {"key": "aftermarket", "title": "🌙 장후픽", "note": "기준 오늘 종가 · 내일 볼 자리",
             "empty": "장 마감(15:30) 뒤 15:45에 자동으로 선정합니다." if not after else "", "picks": after},
        ],
    }


def build_hotbar_monthly(date: str, pre: list, intra: list, after: list, session: str) -> dict:
    stamp = now_kst()
    pre_codes = {p["code"] for p in pre}
    boards = group_by_theme(pre + intra + after, pre_codes)
    n = len(pre) + len(intra) + len(after)
    return {
        "v": 3,
        "kind": "picks",
        "generated_at": stamp.isoformat(timespec="seconds"),
        "generated_at_kst": stamp.strftime("%Y.%m.%d %H:%M"),
        "base_date": date,
        "base_date_text": f"{date_text(date)} {session} 기준 · 테마 {len(boards)}개 · 픽 {n}종목",
        "session": session,
        "counts": {"themes": len(boards), "stocks": n,
                   "premarket": len(pre), "intraday": len(intra), "aftermarket": len(after)},
        "boards": boards,
    }


def build_radar(date: str, pre: list, intra: list, after: list, session: str) -> dict:
    stamp = now_kst()
    pre_codes = {p["code"] for p in pre}
    groups = group_by_theme(pre + intra + after, pre_codes)
    tiers = []
    for i, g in enumerate(groups):
        rows = g["picks"]
        why = " / ".join(f"{r['name']} — {r['reason']}" for r in rows if r.get("reason"))
        kws = [t for t in str(g["key"]).replace("·", " ").replace("/", " ").split() if len(t) > 1]
        stocks = []
        for r in rows:
            px = r.get("current_price")
            stocks.append({
                "code": r["code"],
                "name": r["name"],
                "price_text": (f"{int(px):,}원" if px else ""),
                "pct": r.get("pct"),
                "pct_why": f"{r.get('pick_time', '')} {str(r.get('ref_kind') or '기준가').split(' · ')[0]} 대비".strip(),
                "tag": "장전" if r["code"] in pre_codes else ("장후" if r.get("_leg") == "aftermarket" else "장중"),
            })
        tiers.append({
            "rank": i + 1,
            "theme": g["key"],
            "color": TIER_COLORS[i % len(TIER_COLORS)],
            "active": True,
            "keywords": kws,
            "why": why,
            "stocks": stocks,
            "news": None,
            "watch": "",
        })
    n = len(pre) + len(intra) + len(after)
    return {
        "generated_at": stamp.isoformat(timespec="seconds"),
        "generated_at_kst": stamp.strftime("%Y.%m.%d %H:%M"),
        "base_date": date,
        "base_date_text": f"{date_text(date)} {session} 기준 · 오늘 픽 {n}종목",
        "drop_note": "종목 옆 % = 기준가 대비 오늘 등락률 · 종목을 누르면 125봉 일봉 차트",
        "active": True,
        "kind": "picks",
        "session": session,
        "counts": {"themes": len(tiers), "stocks": n},
        "tiers": tiers,
        "news_updated_kst": "",
        "news_issues": 0,
        "news_links": [],
        "news_note": "테마 = 오늘 픽이 잡힌 테마",
        "cwait": None,
    }


def build_popup(date: str, pre: list, intra: list, after: list, session: str) -> dict:
    stamp = now_kst()

    def row(p: dict, label: str, num: int) -> dict:
        return {
            "code": p["code"], "name": p["name"],
            "theme": p.get("theme") or "",
            "reason": p.get("reason") or "",
            "date": date,
            "label": label, "num": num, "active": True,
            "badges": [], "risk": "", "tag": label,
            "stage10": int(p.get("stage10") or 0), "dd": p.get("dd"),
            "val20": p.get("val20"), "lu_ago": p.get("lu_ago"),
            "stage10_late": int(p.get("stage10_late") or 0),
            "stage_txt": p.get("stage_txt") or "",
        }

    return {
        "v": 2,
        "kind": "picks",
        "base_date": date,
        "generated_at": stamp.isoformat(timespec="seconds"),
        "generated_at_kst": stamp.strftime("%Y.%m.%d %H:%M"),
        "session": session,
        "counts": {"buy": len(pre), "buy_all": len(pre),
                   "radar": len(intra), "radar_all": len(intra),
                   "after": len(after), "after_all": len(after), "pink": 0},
        "sections": {
            "buy": [row(p, "장전픽", 2) for p in pre],
            "radar": [row(p, "핵심" if p.get("tier") == "core" else "추가", 3) for p in intra],
            "after": [row(p, "장후픽", 4) for p in after],
            "pink": [],
        },
        "items": [],
    }


def attach_stage(picks: list, doc: dict | None = None) -> dict:
    """픽 카드에 1~10단계 판정을 붙인다 — 가격·등락률·사유는 그대로 두고 단계만 더한다."""
    if not picks:
        return {}
    doc = doc if doc is not None else S10.load_day125()
    seen = {}
    for p in picks:
        code = str(p.get("code") or "")
        try:
            r = S10.judge_code(doc, code)
        except Exception:  # noqa: BLE001
            continue
        p["stage10"] = int(r.get("stage10") or 0)
        p["stage_txt"] = r.get("stage_txt") or ""
        p["stage_why"] = r.get("why") or ""
        p["dd"] = r.get("dd")
        p["val20"] = r.get("val20")
        p["lu_ago"] = r.get("lu_ago")
        p["stage10_late"] = int(r.get("stage10_late") or 0)
        seen[code] = r
    return seen


def build_cwait(date: str, limit: int = 12) -> dict:
    """레이더 '9·10단계 재부각 대기' — 125봉 상한가 이력 종목 중 9·10단계."""
    try:
        doc = S10.load_day125()
        rows = S10.scan(doc, limit=limit, stages=(9, 10))
    except Exception as e:  # noqa: BLE001
        print(f"[warn] cwait: {e}", file=sys.stderr)
        return {"base_date": date, "count": 0, "stocks": []}
    # *****
    cal = NR.load("calendar.json", {}) or {}
    theme_of: dict = {}
    for m in cal.get("months") or []:
        for t in m.get("themes") or []:
            for s in t.get("stocks") or []:
                c = str(s.get("code") or "")
                if c and c not in theme_of:
                    theme_of[c] = str(t.get("name") or "")
    stocks = []
    for r in rows:
        stocks.append({
            "code": r.get("code"), "name": r.get("name"),
            "stage": int(r.get("stage10") or 0), "stage_txt": r.get("stage_txt") or "",
            "state": "대기", "theme": theme_of.get(str(r.get("code") or ""), ""),
            "dd": r.get("dd"), "val20": r.get("val20"), "lu_ago": r.get("lu_ago"),
            "anchor_date": r.get("anchor_date") or "", "why": r.get("why") or "",
            "t": "C",
        })
    return {"base_date": date, "count": len(stocks), "stocks": stocks,
            "note": "125봉 상한가 이력 종목 중 9·10단계 — 하락 멈춤·재출발 대기(매수 아님)"}


def build(date: str, book: dict) -> dict:
    rec = today_record(book, date)
    pre = [pick_card(p) for p in (rec.get("premarket") or []) if p.get("code")]
    intra = [pick_card(p) for p in (rec.get("intraday") or []) if p.get("code")]
    after = [pick_card(p) for p in (rec.get("aftermarket") or []) if p.get("code")]
    for i, p in enumerate(intra, 1):        # *****
        if not p.get("tier"):
            p["tier"] = "core" if i <= 5 else "extra"
    for p in pre:
        p["_leg"] = "premarket"
    for p in intra:
        p["_leg"] = "intraday"
    for p in after:
        p["_leg"] = "aftermarket"
    session = "장중" if any(p["status"] == "진행" for p in pre + intra + after) else "장마감"
    # *****
    attach_stage(pre + intra + after)
    radar = build_radar(date, pre, intra, after, session)
    radar["cwait"] = build_cwait(date)
    return {
        "hotbar": build_hotbar(date, pre, intra, after, session),
        "hotbar_monthly": build_hotbar_monthly(date, pre, intra, after, session),
        "radar": radar,
        "popup": build_popup(date, pre, intra, after, session),
        "counts": {"premarket": len(pre), "intraday": len(intra), "aftermarket": len(after),
                   "cwait": (radar.get("cwait") or {}).get("count", 0)},
    }


def secret_code(explicit: str = "") -> str:
    code = (explicit or os.environ.get("PICKS_PW") or "").strip()
    if code:
        return code
    try:
        with open(CODE_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:  # noqa: BLE001
        return ""


def write_all(book: dict, date: str, code: str = "", data_dir: str = DATA,
              plain_dir: str = PLAIN_DIR) -> dict:
    """네 벌을 평문(private-plain)과 잠근 파일(data)로 같이 쓴다. 만든 개수를 돌려준다."""
    docs = build(date, book)
    counts = docs.pop("counts")
    for name in ("hotbar", "hotbar_monthly", "radar", "popup"):
        write_json(os.path.join(plain_dir, f"{name}.json"), docs[name])
        if code:
            write_json(os.path.join(data_dir, f"{name}.json"), seal(docs[name], code))
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description="오늘 픽 보드(실전·레이더·종합 안내) 다시 만들기")
    ap.add_argument("--date", default="", help="기준 날짜(YYYY-MM-DD) — 기본은 오늘(KST)")
    ap.add_argument("--code", default="", help="비밀코드(기본: PICKS_PW 환경변수 · private-plain/.picks_code)")
    ap.add_argument("--book", default=BOOK, help="평문 장부 경로")
    ap.add_argument("--data", default=DATA, help="잠근 파일을 쓸 data 디렉터리")
    ap.add_argument("--plain", default=PLAIN_DIR, help="평문을 쓸 디렉터리")
    ap.add_argument("--dry-run", action="store_true", help="저장하지 않고 개수만 본다")
    args = ap.parse_args()

    date = args.date or now_kst().strftime("%Y-%m-%d")
    book = read_json(args.book, {})
    if not isinstance(book, dict) or not book.get("months"):
        raise SystemExit(f"평문 장부가 없습니다: {args.book}")
    docs = build(date, book)
    counts = docs["counts"]
    print(f"[board] {date} 장전 {counts['premarket']} · 장중 {counts['intraday']}"
          + (f" · 9·10단계 대기 {counts['cwait']}" if counts.get("cwait") is not None else ""))
    for t in docs["radar"]["tiers"]:
        print(f"   테마 {t['theme']:<24} {len(t['stocks'])}종목")
    if args.dry_run:
        print("[dry-run] 저장하지 않았습니다")
        return
    code = secret_code(args.code)
    if not code:
        raise SystemExit("비밀코드가 없습니다 — --code · PICKS_PW · private-plain/.picks_code 중 하나가 필요합니다")
    write_all(book, date, code, data_dir=args.data, plain_dir=args.plain)
    print(f"[ok] {args.plain}/hotbar.json · hotbar_monthly.json · radar.json · popup.json")
    print(f"[ok] {args.data}/hotbar.json · hotbar_monthly.json · radar.json · popup.json (잠금 완료)")


if __name__ == "__main__":
    main()
