#!/usr/bin/env python3
"""*****"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nr_data as NR  # noqa: E402
# 평문은 저장소 밖(private-plain/data)에서만 다룬다.
DATA = NR.ensure_plain_dir()
PLAIN_DIRS = tuple(d for d in (os.environ.get("NEWSRADAR_PLAIN_DIR", ""),
                               os.path.join(SITE, "private-plain"),
                               os.path.join(os.path.dirname(SITE), "private-plain")) if d)
OUT_MASTER = os.path.join(DATA, "master_themes.json")
CAL_PATH = os.path.join(DATA, "calendar.json")
KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"}

ROLE = {1: "대장주", 2: "부대장주", 3: "3등주"}

# 손으로 적은 개명·약칭표 — 마스터 목록의 이름 → 지금 쓰는 종목명/코드
#   (2026-11-26 확인: 네이버 증권 기준. 이름이 바뀐 회사만 적는다)
RENAME = {
    "LIG넥스원": ("LIG디펜스앤에어로스페이스", "079550"),
    "한글과컴퓨터": ("한컴", "030520"),
    "동양철관": ("KBI동양철관", "008970"),
    "HD현대건설기계": ("HD건설기계", "267270"),
    "덕신EPC": ("덕신이피씨", "090410"),
    "씨어스테크놀로지": ("씨어스", "458870"),
    "윈스": ("윈스테크넷", "136540"),
    "TPC": ("TPC로보틱스", "048770"),
    "모비스": ("현대모비스", "012330"),
    "SPC삼립": ("삼립", "005610"),
}
# 자동완성이 다른 회사를 먼저 주는 이름 — 코드를 직접 적는다
FORCE_CODE = {
    "SFA": "036540",        # SFA반도체
    "S-Oil": "010950",
    "JYP Ent.": "035900",
}

# 테마 이름만으로는 달력 테마를 못 찾는 것 — 같이 볼 말
EXTRA_KEYWORDS = {
    "소캠": ["SOCAMM", "소캠"],
    "일수출규제": ["수출규제"],
    "증권토큰증권STO": ["STO", "토큰증권"],
    "밸류업저PBR": ["저PBR", "밸류업", "PBR"],
    "정책원전밸류업": ["원전", "밸류업"],
    "퓨리오사AI": ["퓨리오사", "NPU"],
    "위성통신스타링크": ["스타링크", "위성"],
    "지역화폐": ["지역화폐", "민주당"],
    "정책기본소득지역화폐": ["지역화폐", "기본소득"],
    "정책한강개발": ["한강"],
    "공조냉동클린룸": ["클린룸", "냉동", "공조"],
    "액침냉각": ["냉각", "액침"],
    "니켈특수합금": ["니켈", "특수합금"],
    "전자파": ["전자파", "차폐"],
    "무선충전": ["무선충전"],
    "카메라모듈": ["카메라모듈", "카메라"],
    "갤럭시부품": ["갤럭시"],
    "아이폰": ["아이폰", "애플"],
    "폴더블폰": ["폴더블"],
    "플렉서블디스플레이": ["플렉서블", "디스플레이"],
    "OLED": ["OLED", "디스플레이"],
    "메타버스XR": ["메타버스", "XR"],
    "버추얼IP": ["버추얼", "IP"],
    "드라마영상콘텐츠": ["드라마", "콘텐츠"],
    "웹툰웹소설": ["웹툰", "웹소설"],
    "웹툰플랫폼": ["웹툰"],
    "K푸드라면": ["라면", "K-푸드", "푸드"],
    "K푸드김스낵": ["스낵", "K-푸드"],
    "면세점백화점": ["면세", "백화점"],
    "카지노호텔": ["카지노"],
    "여행항공": ["여행", "항공"],
    "편의점가성비소비": ["편의점", "가성비"],
    "저출산엔젤산업": ["저출산", "유아"],
    "고령화실버산업": ["고령화", "실버"],
    "교육일자리": ["교육"],
    "미세먼지황사": ["미세먼지", "황사"],
    "태풍장마": ["태풍", "장마"],
    "폭염제습기": ["폭염", "제습"],
    "한파도시가스": ["한파", "도시가스"],
    "폐기물환경": ["폐기물", "환경"],
    "제지포장재": ["제지", "포장재"],
    "밀가루제분": ["제분", "밀가루"],
    "설탕제당": ["제당", "설탕"],
    "육계수산": ["육계", "수산"],
    "사료비료": ["사료", "비료"],
    "타이어": ["타이어"],
    "패션의류": ["패션", "의류"],
    "화장품ODM": ["ODM", "화장품"],
    "화장품": ["화장품"],
    "K-뷰티": ["화장품", "뷰티"],
    "스마트시티": ["스마트시티", "유신"],
    "모듈러주택": ["모듈러"],
    "네옴시티": ["네옴"],
    "건설재건": ["건설"],
    "건설기계": ["건설기계"],
    "우크라이나재건": ["우크라이나", "재건"],
    "남북경협철도": ["남북", "철도"],
    "GTX": ["GTX"],
    "해저터널": ["터널"],
    "해운물류": ["해운", "물류"],
    "물류택배": ["택배", "물류"],
    "철강": ["철강"],
    "시멘트레미콘": ["시멘트", "레미콘"],
    "원전해체": ["원전", "해체"],
    "핵융합에너지": ["핵융합"],
    "연료전지": ["연료전지", "수소"],
    "수소": ["수소"],
    "우주데이터센터": ["우주", "데이터센터"],
    "우주태양광": ["우주", "태양광"],
    "니켈": ["니켈"],
    "희토류": ["희토류"],
    "초전도체": ["초전도"],
    "맥신": ["맥신"],
    "탄소배출권": ["탄소", "배출권"],
    "정유유가": ["정유", "유가"],
    "셰일가스": ["셰일", "가스"],
    "가스": ["가스"],
    "풍력": ["풍력"],
    "태양광": ["태양광"],
    "페로브스카이트태양광": ["페로브스카이트", "태양광"],
    "5G": ["5G"],
    "통신장비": ["통신장비", "통신"],
    "전력설비": ["전력설비", "전력기기"],
    "전선": ["전선"],
    "구리비철": ["구리", "비철"],
    "초고압변압기": ["변압기"],
    "원전": ["원전", "SMR"],
    "방위산업": ["방산", "방위"],
    "드론": ["드론"],
    "UAM": ["UAM"],
    "조선": ["조선"],
    "조선기자재": ["조선기자재", "조선"],
    "피팅밸브": ["밸브", "피팅"],
    "알래스카LNG": ["알래스카", "LNG"],
    "스테이블코인": ["스테이블코인"],
    "전자결제": ["결제", "핀테크"],
    "지주사자사주": ["자사주", "지주"],
    "창투사벤처캐피탈": ["벤처", "창투"],
    "금융자동화": ["금융자동화", "ATM"],
    "생성형AI": ["생성형", "LLM", "AI"],
    "AI에이전트": ["에이전트", "AI"],
    "클라우드": ["클라우드"],
    "사이버보안": ["보안", "해킹"],
    "정보보안": ["보안"],
    "양자암호": ["양자"],
    "디지털헬스케어": ["디지털헬스", "헬스케어"],
    "의료AI": ["의료", "AI"],
    "미용의료기기": ["미용", "의료기기"],
    "보톡스필러": ["보톡스", "필러"],
    "비만치료제": ["비만", "GLP-1"],
    "유전자치료제": ["유전자"],
    "바이오시밀러": ["바이오시밀러"],
    "제약바이오CDMO": ["CDMO"],
    "면역항암제": ["항암", "면역"],
    "치매뇌질환": ["치매", "뇌"],
    "줄기세포": ["줄기세포"],
    "임플란트치과": ["임플란트", "치과"],
    "탈모치료": ["탈모"],
    "백신방역": ["백신", "방역"],
    "진단키트": ["진단키트"],
    "동물백신구제역": ["구제역", "동물"],
    "전고체배터리": ["전고체"],
    "나트륨이온배터리": ["나트륨"],
    "2차전지": ["2차전지", "이차전지"],
    "LFP배터리": ["LFP"],
    "ESS": ["ESS"],
    "리튬": ["리튬"],
    "리튬광물": ["리튬"],
    "탄소나노튜브": ["나노튜브", "CNT"],
    "배터리장비": ["배터리", "장비"],
    "폐배터리리사이클링": ["폐배터리", "리사이클"],
    "HBM": ["HBM"],
    "유리기판": ["유리기판"],
    "CXL": ["CXL"],
    "온디바이스AI": ["온디바이스"],
    "시스템반도체": ["시스템반도체"],
    "반도체장비": ["반도체 장비", "장비"],
    "반도체검사": ["반도체", "검사"],
    "반도체소재": ["반도체", "소재"],
    "반도체기판": ["기판"],
    "뉴로모픽반도체": ["뉴로모픽"],
    "광통신": ["광통신", "광"],
    "전력반도체": ["전력반도체", "SiC"],
    "데이터센터": ["데이터센터"],
    "휴머노이드": ["휴머노이드", "로봇"],
    "협동로봇": ["협동로봇", "로봇"],
    "산업용로봇": ["산업용로봇", "로봇"],
    "로봇감속기": ["감속기", "로봇"],
    "3D프린터": ["3D프린터", "3D"],
    "자율주행": ["자율주행"],
    "자동차전장": ["전장", "자동차"],
    "완성차": ["완성차", "자동차"],
}

# 달력 테마 이름에 거의 항상 들어가는 일반어 — 이 말만으로 잇지 않는다
WEAK = {"반도체", "장비", "소재", "검사", "기판", "환경", "물류", "가스", "철강", "보안", "조선",
        "교육", "결제", "AI", "로봇", "자동차", "항공", "여행", "화장품", "의류", "유가", "수소"}
# *****
CATCH_ALL = re.compile(r"^(개별|재료 미확인|동전주)")


def plain_path(name: str) -> str:
    for d in PLAIN_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return ""


def jload(name: str) -> dict:
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def write_json(path: str, doc) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    os.replace(tmp, path)


def parse_master(path: str) -> list[tuple[str, list[str]]]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue
            name, rest = line.split(":", 1)
            stocks = [s.strip() for s in rest.split(",") if s.strip()]
            out.append((name.strip(), stocks[:3]))
    return out


def known_names() -> dict:
    """이미 아는 종목 이름 → 코드 (125봉 자료 · 달력 · 공개 이름표)."""
    known: dict = {}
    d = jload("day125.json")
    for nm, c in (d.get("names") or {}).items():
        if nm and c:
            known[str(nm).strip()] = str(c)
    cal = jload("calendar.json")
    for m in cal.get("months") or []:
        for t in m.get("themes") or []:
            for s in t.get("stocks") or []:
                if s.get("name") and s.get("code"):
                    known.setdefault(str(s["name"]).strip(), str(s["code"]))
            for k in ("leader", "rep"):
                if t.get(k) and t[k].get("name") and t[k].get("code"):
                    known.setdefault(str(t[k]["name"]).strip(), str(t[k]["code"]))
    for nm, (now, code) in RENAME.items():
        known.setdefault(nm, code)
        known.setdefault(now, code)
    for nm, code in FORCE_CODE.items():
        known[nm] = code
    return known


def naver_lookup(names: list[str]) -> dict:
    def one(nm):
        want = RENAME.get(nm, (nm, ""))[0]
        url = "https://ac.stock.naver.com/ac?q=%s&target=stock" % urllib.parse.quote(want)
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=8) as r:
                j = json.loads(r.read().decode("utf-8", "replace"))
            for it in (j.get("items") or []):
                code, name = str(it.get("code") or ""), str(it.get("name") or "").strip()
                if name == want and code.isdigit() and len(code) == 6:
                    return nm, code
        except Exception:  # noqa: BLE001
            pass
        return nm, ""

    with ThreadPoolExecutor(max_workers=4) as ex:
        return dict(ex.map(one, names))


_ASCII = re.compile(r"^[A-Za-z0-9&.\- ]+$")


def kw_hit(kw: str, text: str) -> bool:
    """키워드가 글 안에 있는가 — 띄어쓰기는 무시하고, 영문·숫자는 낱말 경계까지 본다(IP 가 IPO 에 걸리지 않게)."""
    if not kw:
        return False
    kw, text = kw.replace(" ", ""), text.replace(" ", "")
    if _ASCII.match(kw):
        return re.search(r"(?<![A-Za-z0-9])" + re.escape(kw) + r"(?![A-Za-z0-9])", text) is not None
    return kw in text


def split_keywords(name: str) -> list[str]:
    parts = [p for p in re.split(r"[·\s/,\-()]+", name) if len(p) >= 2]
    out = []
    for p in parts:
        if p not in out:
            out.append(p)
    for extra in EXTRA_KEYWORDS.get(name, []):
        if extra not in out:
            out.append(extra)
    return out


def match_themes(master: list, cal: dict) -> tuple[dict, dict]:
    """마스터 테마 → 달력 테마 점수. (마스터별 연결, 달력테마별 최선 마스터)"""
    ct: dict = {}
    for m in cal.get("months") or []:
        for t in m.get("themes") or []:
            nm = str(t.get("name") or "").strip()
            if not nm or CATCH_ALL.match(nm):
                continue
            rec = ct.setdefault(nm, {"codes": set(), "months": set(), "count": 0, "lu": set()})
            for s in t.get("stocks") or []:
                c = str(s.get("code") or "").strip()
                if c:
                    rec["codes"].add(c)
                    for dt in (s.get("dates") or []):
                        rec["lu"].add((c, str(dt)))
            rec["months"].add(str(m.get("month") or ""))
            rec["count"] += int(t.get("count") or len(t.get("stocks") or []))
    by_master: dict = {}
    by_cal: dict = {}
    for mt in master:
        mc = {s["code"] for s in mt["stocks"] if s.get("code")}
        kws = mt["keywords"]
        rows = []
        for cn, rec in ct.items():
            ov = len(mc & rec["codes"])
            hits = [k for k in kws if kw_hit(k, cn)]
            strong_hits = [k for k in hits if k not in WEAK]
            score = 3 * len(strong_hits) + len(hits) + (2 if ov >= 2 else (1 if ov == 1 else 0))
            if not strong_hits and ov < 2:
                continue                      # 일반어만 걸리거나 종목 1개 겹침 — 잇지 않는다
            rows.append({"name": cn, "score": score, "overlap": ov, "hits": hits})
        rows.sort(key=lambda r: (-r["score"], -r["overlap"], r["name"]))
        keep = [r for r in rows if r["score"] >= max(3, (rows[0]["score"] - 2 if rows else 3))][:4]
        by_master[mt["name"]] = keep
        for r in keep:
            rec = by_cal.setdefault(r["name"], {"masters": [], "best": None})
            rec["masters"].append({"name": mt["name"], "score": r["score"]})
            if rec["best"] is None or r["score"] > rec["best"]["score"]:
                rec["best"] = {"name": mt["name"], "score": r["score"]}
    for nm, rec in ct.items():
        rec["lu_n"] = len(rec["lu"])
    return by_master, by_cal


def main() -> None:
    ap = argparse.ArgumentParser(description="마스터 테마 153개를 테마달력·사전에 반영")
    ap.add_argument("--input", default=plain_path("master_themes_input.txt"),
                    help="마스터 테마 평문 목록(기본: private-plain/master_themes_input.txt)")
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 비교 수치만")
    ap.add_argument("--no-net", action="store_true", help="네이버 자동완성 조회를 하지 않는다")
    args = ap.parse_args()
    if not args.input or not os.path.exists(args.input):
        raise SystemExit("마스터 테마 목록이 없습니다: %s" % args.input)

    raw = parse_master(args.input)
    known = known_names()
    need = sorted({s for _n, ss in raw for s in ss if s not in known})
    got = {} if args.no_net else naver_lookup(need)
    known.update({k: v for k, v in got.items() if v})

    master, unresolved = [], []
    for name, ss in raw:
        stocks = []
        for i, nm in enumerate(ss, 1):
            code = known.get(nm, "")
            real = RENAME.get(nm, (nm, ""))[0]
            stocks.append({"rank": i, "role": ROLE.get(i, ""), "name": nm,
                           "code": code, "stock": real if code else nm})
            if not code:
                unresolved.append({"theme": name, "name": nm})
        master.append({"name": name, "stocks": stocks, "keywords": split_keywords(name)})

    cal = jload("calendar.json")
    by_master, by_cal = match_themes(master, cal)

    # 종목 → 테마 역색인
    code_index: dict = {}
    name_index: dict = {}
    for mt in master:
        for s in mt["stocks"]:
            if s["code"]:
                code_index.setdefault(s["code"], [])
                if mt["name"] not in code_index[s["code"]]:
                    code_index[s["code"]].append(mt["name"])
            name_index.setdefault(s.get("stock") or s["name"], [])
            if mt["name"] not in name_index[s.get("stock") or s["name"]]:
                name_index[s.get("stock") or s["name"]].append(mt["name"])

    ct_all = {}
    for m in cal.get("months") or []:
        for t in m.get("themes") or []:
            nm = str(t.get("name") or "").strip()
            if not nm:
                continue
            rec = ct_all.setdefault(nm, {"months": set(), "count": 0})
            rec["months"].add(str(m.get("month") or ""))
            rec["count"] += int(t.get("count") or 0)

    for mt in master:
        links = by_master.get(mt["name"], [])
        mt["cal_themes"] = [{"name": r["name"], "months": sorted(ct_all.get(r["name"], {}).get("months", []))[:6],
                             "count": ct_all.get(r["name"], {}).get("count", 0),
                             "score": r["score"], "overlap": r["overlap"]} for r in links]
        mt["cal_months"] = sorted({mm for r in links for mm in ct_all.get(r["name"], {}).get("months", [])})
        mt["cal_upper"] = sum(ct_all.get(r["name"], {}).get("count", 0) for r in links)

    stamp = datetime.now(KST)
    doc = {
        "generated_at": stamp.isoformat(timespec="seconds"),
        "generated_at_kst": stamp.strftime("%Y.%m.%d %H:%M"),
        "source": "마스터 테마 목록(153테마) — 테마마다 대장주·부대장주·3등주",
        "theme_total": len(master),
        "stock_total": sum(len(m["stocks"]) for m in master),
        "stock_unique": len(name_index),
        "code_total": len(code_index),
        "unresolved_total": len(unresolved),
        "unresolved": unresolved,
        "linked_theme_total": sum(1 for m in master if m["cal_themes"]),
        "themes": master,
        "code_index": code_index,
        "name_index": name_index,
    }

    linked_cal = len(by_cal)
    print("[master] 테마 %d · 종목 %d(고유 %d) · 코드 해석 %d · 못 찾은 이름 %d"
          % (doc["theme_total"], doc["stock_total"], doc["stock_unique"],
             doc["code_total"], len(unresolved)), file=sys.stderr)
    print("[master] 달력 테마 %d개 중 %d개에 대장주·부대장주·3등주를 붙였다"
          % (len(ct_all), linked_cal), file=sys.stderr)
    if unresolved:
        print("[master] 못 찾은 이름: " + ", ".join(sorted({u["name"] for u in unresolved})), file=sys.stderr)

    if args.dry_run:
        for mt in master[:200]:
            if mt["cal_themes"]:
                print("  %-24s → %s" % (mt["name"], mt["cal_themes"][0]["name"]))
        print("[dry-run] 저장하지 않았습니다")
        return

    write_json(OUT_MASTER, doc)

    # *****
    meta = {mt["name"]: mt for mt in master}
    touched = 0
    for m in cal.get("months") or []:
        for t in m.get("themes") or []:
            nm = str(t.get("name") or "").strip()
            rec = by_cal.get(nm)
            if not rec or not rec.get("best"):
                t.pop("master", None)
                t.pop("masters", None)
                continue
            best = meta[rec["best"]["name"]]
            t["master"] = {
                "name": best["name"],
                "leader": next(({"name": s["stock"], "code": s["code"]} for s in best["stocks"] if s["rank"] == 1), None),
                "sub": next(({"name": s["stock"], "code": s["code"]} for s in best["stocks"] if s["rank"] == 2), None),
                "third": next(({"name": s["stock"], "code": s["code"]} for s in best["stocks"] if s["rank"] == 3), None),
                "score": rec["best"]["score"],
            }
            others = [x["name"] for x in sorted(rec["masters"], key=lambda x: -x["score"]) if x["name"] != best["name"]]
            if others:
                t["masters"] = others[:3]
            else:
                t.pop("masters", None)
            touched += 1
    cal["master_theme_total"] = len(master)
    cal["master_stock_total"] = doc["stock_total"]
    cal["master_linked_themes"] = linked_cal
    cal["master_applied_at"] = stamp.strftime("%Y.%m.%d %H:%M")
    write_json(CAL_PATH, cal)
    print("[master] %s · %s (달력 테마 %d건에 master 메타)" % (OUT_MASTER, CAL_PATH, touched), file=sys.stderr)
    NR.seal_all()   # data/*.json 전체를 잠근다(평문은 private-plain/data)


if __name__ == "__main__":
    main()
