#!/usr/bin/env python3
"""핫바 네 번째 칸 **10단계** 자료 생성기 — 10년 전수조사(stage10_core) 기준 그대로.

  결과: projects/stock-news-radar/data/hotbar_monthly.json  (AES-256-GCM · 비밀코드는 이 파일에만)
  기록: brain/cache/stage10_watchlist.json  (올라온 종목을 매도까지 따라가는 장부 · 공개 안 함)

  실행: python3 scripts/build_hotbar_buy.py            # 만들기 + 요약 인쇄
        python3 scripts/build_hotbar_buy.py --dry      # 파일 쓰지 않고 요약만
        python3 scripts/build_hotbar_buy.py --no-fetch # 오늘 봉을 새로 받지 않고 캐시만으로

무인 실행(뉴스레이더 지정시간: 장전·장중 30분·장후 1시간)에서 10~20초 안에 끝나도록 만들었다.
  · 10년 일봉(brain/cache/hotbar_parts, 하루 한 번만 읽는 원본)은 최근 470봉만 잘라 쓴다.
  · 오늘 봉은 후보 종목만 네이버 일봉에서 새로 받는다(16갈래 동시 · 종목당 0.1초 안팎).

무엇을 담나 (푸른하늘님 2026-11-20 지시)
  조건 — 주식은 뉴스가 전부고 테마로 만들어진다. 당일 억지로 맞지 않는 것은 올리지 않는다.
    기준) 앞 125일봉 횡보 뒤 첫 상한가(또는 60~124봉 사이 2·3차 상한가) = 닻.
    1) 4단계·5단계 (4→5 황금자리) — 유형 A(첫 상한가) / B(연속 2·3차)
       · 2번 기준선(1번 봉 시가) 사수 + 상자 안 2회 이상 왕복 횡보
       · 최근 1~2일 안에 거래량이 앞 5봉 평균의 0.7배 이하로 마른 음봉  → 4단계 매수 자리
       · 또는 그 음봉 바로 뒤 오늘 상자 윗선을 넘은 5단계 돌파 당일
    2) 9단계 하락 멈춤 — 유형 C(재출발 자리)
       · 분출 고점에서 -25% 이상 빠진 자리
       · 최소 15봉 가격 폭 20% 안에서 멈춤 + 거래량이 분출 구간의 0.5배 이하로 마름
    테마) theme_db 테마명·이슈요약을 붙인다. 테마 DB에 없는 종목은 올리지 않는다(잡주 배제).
    앞/뒤) 주봉 240선·월봉 120선으로 앞쪽/뒷쪽 배지.
    기준선) **그림 기준선** — ① 상한가 → ② 하락 음봉 → ③ 반등 양봉이 나온 뒤 ② 저점에 긋는다
           (2026-11-21 지시). ③이 없으면 긋지 않고 선을 미루고, ④ 그 줄까지 내려오면 '4번 추가매수'.
    3번 첫 거래 판정) A/B/C/D — 월봉 첫 거래량 터짐·3번 크기·지수 꺾임으로 가른다(10년 전수조사 §4-5).
           D(3번 작음 = 사지 않는 자리)는 (매수) 목록에 올리지 않고 뺀다(2026-11-21 지시).
    첫 단추) 테마 크기(같은 테마에서 최근 1주 안에 상한가 낸 종목 수 · 나 포함) ·
           일봉 240선 위/아래(상한가 전날 종가) · 첫 거래량(상한가 봉 거래량 ÷ 앞 125봉 최대)
           — 1단계 첫 단추 그대로 10단계 카드에도 보인다(2026-11-21 지시).
  매매 추적 — 오늘 올라온 종목은 그날 사라지지 않는다.
    (매수) → (돌파·보유) → (분출·보유) → (매도)[8단계 물량 정리 · 목표 +20~30% 뒤 윗꼬리/음봉 꺾임]
    또는 (손절·매도)[기준선 이탈]. 매도 판정 뒤 3거래일은 화면에 남기고 그 다음 정리한다.
"""
from __future__ import annotations

import argparse
import base64
import glob
import gzip
import hashlib
import json
import os
import secrets
import statistics as st
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "brain", "tools"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import stage10_core as S            # noqa: E402
import pink_arrow as PINK           # noqa: E402  분홍 ↑(후보 G) — 차트·10단계 카드에만
import news_theme_link as NL         # noqa: E402  오늘 뉴스 ↔ 105테마 DB 연결(뉴스 부각 배지)
import pink_export as PINKX          # noqa: E402  오늘 분홍↑ 종목 명단 → brain/cache(공개 저장소 밖)
import stock_risk as RISK            # noqa: E402  재무·공시 위험 플래그 — 18-7(2026-11-24 보완 1번)
import season_prestudy as SEA        # noqa: E402  12·1월 반복 테마 사전조사(2026-11-25 전수조사)
import theme_trace as TRACE           # noqa: E402  ⏱ 매달 상한가 테마 · 시간 차이별 10단계 추적(2026-11-25)

DB = os.path.join(ROOT, "scheduled-actions", "📊-건전테마-재부각-레이더", "theme_db.json")
OUT = os.path.join(ROOT, "projects", "stock-news-radar", "data", "hotbar_monthly.json")
# 오늘 분홍↑ 종목의 평문 명단 — 공개 일봉 125봉 자료(build_day125.py)가 이 종목 봉까지 받게 한다.
#   잠긴 hotbar_monthly.json 을 풀지 않고도 알 수 있게, 공개 저장소 밖(brain/cache)에만 적는다.
PINK_TODAY = os.path.join(ROOT, "brain", "cache", "pink_today_pick.json")
WATCH = os.path.join(ROOT, "brain", "cache", "stage10_watchlist.json")
# 유형 C(9단계 하락 멈춤·10단계 재출발 대기) — 2026-11-24 지시로 실전 주 추적에서 떼어
#   🔒 레이더 '9·10단계 재부각 대기' 구역으로 넘긴다(build_radar_news.py 가 radar.json 에 싣는다).
CWAIT = os.path.join(ROOT, "brain", "cache", "radar_c_wait.json")
# 10단계 카드의 요약(평문) — 공개 저장소 밖. 형광↑ 3칸 종합 팝업(build_hotbar_radar.py)이
#   **10단계 숫자를 그대로 받아 쓰기 위해** 읽는다(2026-11-24 — 팝업 stage10 번호 오기 수정).
#   잠긴 hotbar_monthly.json 을 풀지 않고도 같은 숫자를 쓰게 하려고 여기에 한 벌 적어 둔다.
MONTHLY_PLAIN = os.path.join(ROOT, "brain", "cache", "monthly_plain.json")
POOL_CACHE = os.path.join(ROOT, "brain", "cache", "stage10_pool.json.gz")
# 2026-11-25 — 장중 OOM(exit_code 137) 원인 제거: 32MB stage10_pool.json.gz 를 통째로 풀면
#   880종목 × 10년 봉(약 881MB)이 메모리에 올라온다. 이제 필요한 것만 얇게 담은 캐시를 읽는다.
#     · 최근 700일 봉(1~10단계 470 + 차트 170봉·448선 620 여유)
#     · 주봉·월봉 종가 흐름(240주선·120개월선) — 10년 일봉을 다시 풀지 않고 선을 긋는다
#     · 주봉 240선·월봉 120선 값(앞/뒷쪽 판정)
#   실측: 읽기 0.9초 · 메모리 295MB (예전 5.9초 · 881MB).
LIGHT_CACHE = os.path.join(ROOT, "brain", "cache", "stage10_light.json.gz")
LIGHT_BARS = 700          # 종목마다 담는 최근 일봉 수
LIGHT_WEEKS = 292         # 주봉 240선 + 차트 52주 — 담아 두는 주봉 종가 수
LIGHT_MONTHS = 150        # 월봉 120선 + 차트 30개월
LONG_LINES: dict = {}     # code -> {w240, m120, ...}  (얇은 캐시에서 읽은 장기선)
WEEK_CLOSES: dict = {}    # code -> [[주키, 종가], ...] 오래된 순
MONTH_CLOSES: dict = {}   # code -> [[달키, 종가], ...]
# 10년 원본(hotbar_parts)에 없어 1~10단계를 못 재던 테마 종목 — 네이버 일봉 470봉을 하루 한 번만
#   받아 두고 쓴다(2026-11-25 보완: 테마달력 종목이 1~10단계 밖으로 새지 않게).
EXTRA_BARS = os.path.join(ROOT, "brain", "cache", "theme_extra_bars.json.gz")
EXTRA_COUNT = 470
DELTA_DIR = os.path.join(ROOT, "brain", "cache")
# 다가오는 창구 일정 — 레이더가 이미 읽는 공개 일정표(data/schedule.json). 카드마다 테마·종목에
#   걸리는 창구(11/30 금융보안, 12/6 휴머노이드, 12/12 전기본·ASH, 12/23 마이크론, 1/6 CES)를 붙인다.
SCHED = os.path.join(ROOT, "projects", "stock-news-radar", "data", "schedule.json")
# 테마별 대장주 — 90개 테마 대장주 전수조사(brain/theme_leaders.json) + theme_db '대장주'.
#   2026-11-25 지시 "대장.실체 우선이지!" — 카드에 👑를 달고 정렬에서 대장을 위로 올린다.
LEADERS = os.path.join(ROOT, "brain", "theme_leaders.json")
WINDOWS: list = []          # main() 이 채운다 — [{date,dtext,label,short,keys}]
LEADER_OF: dict = {}        # 테마명 → {code,name,근거}

HOTBAR_PW = os.environ.get("HOTBAR_PW") or "<YOUR_PRIVATE_PASSWORD>"     # 2026-11-21 지시로 변경(공개 저장소엔 올리지 않는다)
PBKDF2_ITER = 100000
KST = timezone(timedelta(hours=9))

WIN = 470                 # 종목마다 쓰는 최근 일봉 수(닻 250 + 그 앞 125 + 앞뒤 여유)
KEEP_DAYS = 45            # 오늘 봉 파일에서 되살릴 최근 달력일
VAL_MIN = 3.0             # 3봉 평균 거래대금 하한(억) — 체결이 되는 종목만
CH_MAX = 170              # 차트 창(오늘부터 170봉) — 38봉 확대 + 이평선 60봉 앞

# ---- 4→5 황금자리 (4단계 음봉 / 5단계 돌파 당일)
VOL4_MAX = 0.70           # 4단계 음봉 거래량 ≤ 앞 5봉 평균의 0.7배
SW_MIN = 2                # 상자 안 왕복 횟수 2회 이상 (2~3회 횡보)
BOX_MAX_W = 0.70          # 상자 폭 70% 이내 — 넓으면 상자가 아니다
LU_DAYS_MAX = 90          # 1번 상한가로부터 90봉 안
BRK_VOL4_MAX = 0.70       # 5단계 돌파 당일 — 돌파 바로 앞 음봉이 마른 음봉이어야

# ---- 9단계 하락 멈춤 (유형 C)
C_DD = -0.28              # 분출 고점 대비 -28% 이상(전수조사·스캐너 기준)
C_RNG15 = 0.18            # 15봉 가격 폭 18% 안(전수조사·스캐너 기준)
C_VOL = 0.50              # 거래량이 분출 구간의 0.5배 이하
C_VOL_MIN = 0.03          # 거래량이 완전히 0이 된 종목(관심 소멸)은 재출발 불가 — 뺀다

# ---- 매매 추적
BASE_STOP = 0.95          # 기준선 -5% 이탈 = 손절
LINE_TOUCH = 1.03         # 새 ②③ 뒤 기준선 위 3% 안까지 내려오면 4번(④ 줄 자리)
PAUSE_STOP = 0.97         # 유형 C 멈춤 상자 아래 -3% 이탈 = 손절
PAUSE_STOP_AFTER = 0.90   # 유형 C 재출발 뒤 — 재출발 봉 종가 -10% 이탈 = 손절
TARGET1 = 0.20            # 목표 1차 +20%
TARGET2 = 0.30            # 목표 2차 +30%
SOLD_KEEP = 3             # 매도 판정 뒤 화면에 남기는 거래일
MAX_HOLD_DAYS = 15        # 등록 후 15거래일이면 추적 종료

# 2026-11-25 지시 — 화면의 '유형 A/B/C' 꼬리표는 걷어내고 **1~10단계 숫자 하나**로 통일한다.
#   자료 안의 t(A/B/C)는 장부·레이더 대기실 구분에만 쓰고, 화면에는 내보내지 않는다.
TYPE_DEF = {}
STATE_DEF = {
    "매수": "4단계 음봉·9단계 멈춤 — 지금 사는 자리",
    "9단계 매수": "9단계 멈춤 — 윗선 돌파(재출발)를 기다리는 사는 자리",   # 2026-11-21: '매수대기'를 결정문으로
    "관망": "지수 약세 날 — 지수와 같이 밀려 매수 자격을 못 채운 자리(보지 않고 기다림)",
    "돌파·보유": "5단계 윗선 돌파 — 들고 가는 자리",
    "분출·보유": "6~7단계 분출 — 들고 가는 자리",
    "매도": "8단계 물량 정리 · 목표 +20~30% 뒤 윗꼬리/음봉 꺾임 — 파는 자리",
    "손절·매도": "기준선(2번 기준선) 이탈 — 손절",
}


# ---------------------------------------------------------------- 유틸
def load_windows(today: str) -> list:
    """오늘 이후 창구 일정 — data/schedule.json(레이더와 같은 표)."""
    try:
        with open(SCHED, encoding="utf-8") as f:
            ev = (json.load(f) or {}).get("events") or []
    except Exception:
        return []
    out = [e for e in ev if str(e.get("date") or "") >= today]
    out.sort(key=lambda e: str(e.get("date") or ""))
    return out


def window_for(texts, limit: int = 2) -> list:
    """이 테마·종목에 걸리는 다가오는 창구 — 일정표 keys 가 글자에 있으면 붙인다."""
    blob = " ".join(str(t or "") for t in texts).lower()
    out = []
    for e in WINDOWS:
        if any(str(k or "").lower() in blob for k in (e.get("keys") or []) if k):
            out.append({"date": e.get("date") or "", "dtext": e.get("dtext") or "",
                        "label": e.get("label") or "", "short": e.get("short") or ""})
            if len(out) >= limit:
                break
    return out


def load_leaders() -> dict:
    """테마명 → 대장주 {code,name,근거} — brain/theme_leaders.json 먼저, 없으면 theme_db '대장주'."""
    out = {}
    try:
        with open(LEADERS, encoding="utf-8") as f:
            for name, v in (json.load(f) or {}).items():
                c = str((v or {}).get("code") or "")
                if name and c:
                    out[name.strip()] = {"code": c, "name": (v or {}).get("name") or "", "근거": ""}
    except Exception:
        pass
    try:
        with open(DB, encoding="utf-8") as f:
            for t in (json.load(f) or {}).get("목록") or []:
                name = (t.get("테마") or "").strip()
                ld = t.get("대장주") or {}
                if name and ld.get("종목코드"):
                    out[name] = {"code": str(ld.get("종목코드")), "name": ld.get("종목명") or "",
                                 "근거": ld.get("근거") or out.get(name, {}).get("근거") or ""}
    except Exception:
        pass
    return out


def kst_now():
    return datetime.now(KST)


def seal(payload: dict, pw: str) -> dict:
    """브라우저 Web Crypto 가 그대로 풀 수 있는 형태(AES-256-GCM · PBKDF2-SHA256 10만회)."""
    from Crypto.Cipher import AES
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    key = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, PBKDF2_ITER, dklen=32)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ct, tag = AES.new(key, AES.MODE_GCM, nonce=iv).encrypt_and_digest(raw)
    b64 = lambda x: base64.b64encode(x).decode("ascii")
    return {"enc": 1, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct + tag)}


def newest_delta():
    """오늘(또는 가장 최근) 봉 파일 — jsonl.gz 우선, 없으면 json.gz."""
    files = sorted(glob.glob(os.path.join(DELTA_DIR, "hotbar_delta_*.jsonl.gz")))
    if files:
        return files[-1]
    files = sorted(glob.glob(os.path.join(DELTA_DIR, "hotbar_delta_*.json.gz")))
    return files[-1] if files else None


def load_delta(keep_from: str):
    """code -> 최근 봉(keep_from 이후)만. 파일 전체(2년)를 메모리에 쌓지 않는다."""
    path = newest_delta()
    out = {}
    if not path:
        return out
    if path.endswith(".jsonl.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                try:
                    code, rows = json.loads(line)
                except Exception:
                    continue
                keep = [r for r in rows if r[0] >= keep_from and min(r[1:5]) > 0]
                if keep:
                    out[str(code)] = keep
    else:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            d = json.load(f)
        for code, rows in (d.items() if isinstance(d, dict) else []):
            keep = [r for r in rows if r[0] >= keep_from and min(r[1:5]) > 0]
            if keep:
                out[str(code)] = keep
    return out


def fetch_bars(code: str, count: int = 8):
    """네이버 일봉 — 마지막 봉이 오늘(장중이면 진행 중인 봉)이다."""
    url = ("https://fchart.stock.naver.com/sise.nhn?symbol=%s&timeframe=day&count=%d&requestType=0"
           % (code, count))
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw = resp.read().decode("euc-kr", errors="replace")
            root = ET.fromstring(raw)
            rows = []
            for item in root.findall(".//item"):
                p = item.attrib.get("data", "").split("|")
                if len(p) < 6 or "null" in p[1:5]:
                    continue
                d = p[0]
                rows.append(["%s-%s-%s" % (d[:4], d[4:6], d[6:8]),
                             float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5])])
            rows = [r for r in rows if min(r[1:5]) > 0]
            if rows:
                return rows
        except Exception:
            time.sleep(0.2)
    return []


def fetch_many(codes, workers=24, count=8):
    out = {}
    if not codes:
        return out
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for code, rows in zip(codes, ex.map(lambda x: fetch_bars(x, count), codes)):
            if rows:
                out[code] = rows
    return out


# ---------------------------------------------------------------- 시장 지수 · 업종지수
SECTOR_CACHE = os.path.join(ROOT, "brain", "cache", "sector_index.json")
SECTOR_TOP = 12           # 업종지수를 만들 때 쓰는 시총 상위 종목 수
SECTOR_BARS = 46          # 업종지수 계산에 쓰는 일봉 수(20일선 + 앞 구간)
IND_DAYS = 30             # 종목→업종 분류는 30일에 한 번만 다시 본다
WEAK_DAY = -2.0           # 당일 지수 -2.0% 이하 = 급락일
ELITE_GAP = 2.5           # 지수보다 2.5%p 이상 덜 빠지면 '버팀'
ELITE_BASE_MARGIN = 1.05  # 2번 기준선보다 +5% 위


def fetch_index_daily(symbol: str, count: int = 60):
    """코스피·코스닥 지수 일봉 [(날짜, 종가, 고가, 저가), ...]"""
    url = ("https://fchart.stock.naver.com/sise.nhn?symbol=%s&timeframe=day&count=%d&requestType=0"
           % (symbol, count))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("euc-kr", errors="replace")
        root = ET.fromstring(raw)
        out = []
        for item in root.findall(".//item"):
            p = item.attrib.get("data", "").split("|")
            if len(p) < 6 or "null" in p[1:5]:
                continue
            d = p[0]
            out.append(["%s-%s-%s" % (d[:4], d[4:6], d[6:8]),
                        float(p[4]), float(p[2]), float(p[3])])
        return sorted(out, key=lambda r: r[0])
    except Exception:
        return []


def index_state(rows):
    """지수 한 줄 — 당일 등락률, 5일선·20일선, 약세 여부 판정."""
    if len(rows) < 21:
        return None
    cl = [r[1] for r in rows]
    ma5 = st.mean(cl[-5:])
    ma20 = st.mean(cl[-20:])
    chg = (cl[-1] / cl[-2] - 1) * 100 if cl[-2] else 0.0
    weak = (chg <= WEAK_DAY) or (ma5 < ma20)
    return {"close": round(cl[-1], 2), "chg": round(chg, 2),
            "ma5": round(ma5, 2), "ma20": round(ma20, 2), "weak": weak}


def market_doc():
    """코스피·코스닥 — 당일 급락(-2.0% 이하) 또는 5일선<20일선이면 '지수 약세'."""
    out = {}
    for sym, key, name in (("KOSPI", "kospi", "코스피"), ("KOSDAQ", "kosdaq", "코스닥")):
        s = index_state(fetch_index_daily(sym))
        if s:
            s["name"] = name
            out[key] = s
    weak = any(v.get("weak") for v in out.values())
    label = " · ".join("%s %+.2f%%" % (v["name"], v["chg"]) for v in out.values())
    why = []
    for v in out.values():
        if v["chg"] <= WEAK_DAY:
            why.append("%s %+.1f%% 급락" % (v["name"], v["chg"]))
        elif v["ma5"] < v["ma20"]:
            why.append("%s 5일선<20일선" % v["name"])
    return {"kospi": out.get("kospi"), "kosdaq": out.get("kosdaq"),
            "weak": weak, "label": label, "why": " · ".join(why)}


def load_sector_cache():
    """업종 캐시 — 예전 판(강세)으로 저장된 값도 지금 이름(호재)으로 읽는다."""
    try:
        c = json.load(open(SECTOR_CACHE, encoding="utf-8"))
    except Exception:
        return {"date": None, "sectors": {}, "industry": {}}
    for v in (c.get("sectors") or {}).values():
        if isinstance(v, dict) and v.get("state") == "강세":
            v["state"] = "호재"
    return c


def save_sector_cache(c):
    try:
        os.makedirs(os.path.dirname(SECTOR_CACHE), exist_ok=True)
        tmp = SECTOR_CACHE + ".tmp"
        json.dump(c, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, SECTOR_CACHE)
    except Exception:
        pass


def stock_industry(code: str, cache: dict, today: str):
    """종목 → 네이버 업종(업종코드·업종명·시장). 30일 캐시."""
    ent = (cache.get("industry") or {}).get(code)
    if ent and ent.get("name") and ent.get("date"):
        d0 = datetime.strptime(ent["date"], "%Y-%m-%d")
        d1 = datetime.strptime(today, "%Y-%m-%d")
        if (d1 - d0).days < IND_DAYS:
            return ent
    try:
        req = urllib.request.Request("https://m.stock.naver.com/api/stock/%s/integration" % code,
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            j = json.loads(resp.read().decode("utf-8", "replace"))
        req2 = urllib.request.Request("https://m.stock.naver.com/api/stock/%s/basic" % code,
                                      headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req2, timeout=8) as resp2:
            b = json.loads(resp2.read().decode("utf-8", "replace"))
        ic = str(j.get("industryCode") or (j.get("industryCompareInfo") or {}) or "")
        name = ""
        if ic:
            name = sector_name(ic)
        ent = {"code": ic, "name": name, "market": b.get("stockExchangeName") or "",
               "date": today}
    except Exception:
        ent = {"code": "", "name": "", "market": "", "date": today}
    cache.setdefault("industry", {})[code] = ent
    return ent


_SECTOR_NAMES = {}


def sector_name(sector_code: str):
    """업종코드 → 업종명 (한 번만 조회)."""
    if sector_code in _SECTOR_NAMES:
        return _SECTOR_NAMES[sector_code]
    name = ""
    try:
        url = ("https://m.stock.naver.com/front-api/domestic/sector/item/list?sectorCode=%s"
               "&sectorType=upjong&sectorSortType=MARKET_VALUE&size=1" % sector_code)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            j = json.loads(resp.read().decode("utf-8", "replace"))
        name = ((j.get("result") or {}).get("sectorInfo") or {}).get("sectorName") or ""
    except Exception:
        name = ""
    _SECTOR_NAMES[sector_code] = name
    return name


def sector_members(sector_code: str, size: int = SECTOR_TOP):
    """업종 구성종목 — 시가총액 상위 (코드, 시총)."""
    url = ("https://m.stock.naver.com/front-api/domestic/sector/item/list?sectorCode=%s"
           "&sectorType=upjong&sectorSortType=MARKET_VALUE&size=%d" % (sector_code, max(size, 1)))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            j = json.loads(resp.read().decode("utf-8", "replace"))
        items = (j.get("result") or {}).get("items") or []
        out = []
        for s in items[:size]:
            try:
                mv = float(s.get("marketValue") or 0)
            except Exception:
                mv = 0.0
            out.append((str(s.get("itemCode")), mv))
        return out
    except Exception:
        return []


def sector_doc(sector_code: str, today: str) -> dict | None:
    """업종지수의 지금 흐름 — 구성종목 일봉(시총 가중)으로 만든 업종 평균지수를 재서
    호재(5일선>20일선 또는 20일선 위 상승) / 바닥(20일선 아래에서 하락 멈춘 횡보) /
    약세(20일선 아래에서 저점을 깨며 하락)로 나눈다. 화면 색은 한국식 — 호재 빨강 · 바닥 노랑 · 약세 파랑."""
    members = sector_members(sector_code)
    if not members:
        return None
    codes = [c for c, _ in members]
    bars = fetch_many(codes, workers=12, count=SECTOR_BARS)
    rets = {}          # 날짜 -> [(가중치, 등락률)]
    weights = {c: (mv or 1.0) for c, mv in members}
    for c in codes:
        rows = clean(bars.get(c) or [])
        if len(rows) < 22:
            continue
        rows = rows[-SECTOR_BARS:]
        for i in range(1, len(rows)):
            p = rows[i - 1][4]
            if p <= 0:
                continue
            rets.setdefault(rows[i][0], []).append((weights.get(c, 1.0), rows[i][4] / p - 1))
    dates = sorted(rets)
    if len(dates) < 21:
        return None
    idx, level = [], 100.0
    for d in dates:
        wsum = sum(w for w, _ in rets[d]) or 1.0
        r = sum(w * x for w, x in rets[d]) / wsum
        level *= (1 + r)
        idx.append(level)
    cl = idx
    ma5, ma20 = st.mean(cl[-5:]), st.mean(cl[-20:])
    slope20 = (st.mean(cl[-20:]) / st.mean(cl[-25:-5]) - 1) * 100 if len(cl) >= 25 else 0.0
    chg = (cl[-1] / cl[-2] - 1) * 100 if len(cl) > 1 else 0.0
    low5, low15 = min(cl[-5:]), min(cl[-15:])
    rng15 = (max(cl[-15:]) / min(cl[-15:]) - 1) * 100
    name = sector_name(sector_code)
    if cl[-1] >= ma20 and ma5 > ma20:
        state, why = "호재", "5일선>20일선 · 20일선 위 상승"
    elif cl[-1] >= ma20:
        state, why = "바닥", "20일선 막 회복 · 5일선이 아직 아래"
    elif (low5 > low15 * 1.001 and rng15 <= 12.0 and chg > -3.0 and slope20 > -1.5):
        state, why = "바닥", "20일선 아래에서 15봉 폭 %.1f%% 횡보 · 오늘 %+.1f%% 버팀" % (rng15, chg)
    elif low5 <= low15 * 0.9995 or slope20 <= -1.0:
        state, why = "약세", "20일선 아래에서 저점 갱신 · 20일선 %.1f%% 하락" % slope20
    else:
        state, why = "약세", "20일선 아래 · 15봉 폭 %.1f%%로 흔들림 · 오늘 %+.1f%%" % (rng15, chg)
    return {"code": sector_code, "name": name, "state": state, "why": why, "chg": round(chg, 2),
            "ma5": round(ma5, 1), "ma20": round(ma20, 1), "slope20": round(slope20, 2),
            "rng15": round(rng15, 1), "n": len([c for c in codes if bars.get(c)]), "date": today}


def _ctx(code, base, side, price, prev, ind, sec, mkt, side_why=""):
    """한 종목의 '지수 약세 날 매수 자격' — 지수 대비 낙폭·앞쪽·기준선 여유·업종 상태."""
    mkey = "kospi" if ((ind or {}).get("market") or "").upper() == "KOSPI" else "kosdaq"
    idx = mkt.get(mkey) or {}
    chg = (price / prev - 1) * 100 if prev else 0.0
    idx_chg = float(idx.get("chg") or 0.0)
    sstate = (sec or {}).get("state") or ""
    sname = (sec or {}).get("name") or "업종 미상"
    sector_label = "%s %s" % (sname, sstate or "-")
    ahead = side == "앞쪽"
    margin = bool(base) and price >= base * ELITE_BASE_MARGIN
    gap = chg - idx_chg
    cond1 = (gap >= ELITE_GAP) and ahead and margin              # 지수보다 강하게 버틴 놈
    cond2 = (sstate in ("호재", "강세", "바닥") and bool(base) and price >= base and gap >= 0)  # 업종이 버티는 대장
    if cond1:
        note = "지수(%+.1f%%)보다 덜 빠짐(%+.1f%%) · 앞쪽 · 기준선 +%.0f%% 위" % (
            idx_chg, chg, (price / base - 1) * 100 if base else 0)
    elif cond2:
        note = "업종 %s가 버팀 · 기준선 사수 · 지수보다 덜 빠짐(%+.1f%%)" % (sstate, chg)
    elif not ahead:
        note = "뒷쪽(%s)이라 지수와 같이 밀림(%+.1f%%, 지수 %+.1f%%)" % (side_why or "장기선 위", chg, idx_chg)
    elif not base:
        note = "기준선이 없어 여유를 못 잼(%+.1f%%)" % chg
    elif gap < ELITE_GAP:
        note = "지수와 같이 꺾여 밀림(%+.1f%% vs 지수 %+.1f%%)" % (chg, idx_chg)
    else:
        note = "기준선 여유 부족(+%.0f%%, +5%% 필요)" % ((price / base - 1) * 100)
    return {"code": code, "chg": round(chg, 2), "idx_chg": round(idx_chg, 2), "side": side,
            "sector": sec, "sector_label": sector_label, "elite": bool(cond1 or cond2), "note": note}


def clean(rows):
    """값이 0인 봉(거래정지·자료 오류)은 버리고 날짜 순으로."""
    rows = [r for r in rows if min(r[1:5]) > 0]
    rows.sort(key=lambda r: r[0])
    return rows


def merge_with_fresh(rows, fresh):
    """오늘 봉 하나만 새 값으로 갈아 끼운다(과거 봉은 10년 캐시 그대로)."""
    if not fresh:
        return rows
    rows = list(rows)
    last = rows[-1][0] if rows else ""
    for r in fresh:
        if r[0] > last:
            rows.append(r)
        elif r[0] == last:
            rows[-1] = r
    return rows


# ---------------------------------------------------------------- 테마
def parts_sig():
    """10년 원본이 바뀌었는지 — 파일 크기·시각으로 알아본다(원본은 거의 안 바뀐다).

    2026-11-25 — 테마 DB 서명은 뺐다. 테마가 추가될 때마다 10년 원본을 다시 풀면
    장중에 메모리가 터진다(theme_db 는 30분마다 바뀐다). 새로 들어온 테마 종목은
    아래 extra_bars 가 네이버 일봉으로 채운다.
    """
    fs = sorted(glob.glob(os.path.join(ROOT, "brain", "cache", "hotbar_parts", "part_*.json.gz")))
    return "|".join("%s:%d:%d" % (os.path.basename(f), os.path.getsize(f), int(os.path.getmtime(f)))
                    for f in fs)


def _light_read(sig: str, themes: dict) -> dict | None:
    """얇은 캐시 읽기 — 서명이 같을 때만. 없으면 None(만들어야 한다)."""
    if not os.path.exists(LIGHT_CACHE):
        return None
    try:
        out = {}
        with gzip.open(LIGHT_CACHE, "rt", encoding="utf-8") as f:
            head = json.loads(f.readline() or "{}")
            if head.get("sig") != sig:
                return None
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                c = str(rec[0])
                if c not in themes:
                    continue
                out[c] = (rec[1], rec[2])
                WEEK_CLOSES[c] = rec[3]
                MONTH_CLOSES[c] = rec[4]
                ln = rec[5] or [None, None, None, None]
                LONG_LINES[c] = {"w240": ln[0], "m120": ln[1],
                                 "w240_full": ln[2], "m120_full": ln[3]}
        return out or None
    except Exception:
        return None


def _light_build(sig: str, themes: dict) -> dict:
    """10년 원본(8조각 gz)에서 종목별로 필요한 것만 골라 한 조각씩 쓰고 버린다.

    조각 하나(약 400MB)만 들고 돌기 때문에 전체를 메모리에 올리지 않는다.
    """
    import gc
    tmp = LIGHT_CACHE + ".tmp"
    os.makedirs(os.path.dirname(LIGHT_CACHE), exist_ok=True)
    n = 0
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=1) as f:
        f.write(json.dumps({"sig": sig, "v": 1}, ensure_ascii=False) + "\n")
        # 한 조각만 들고 돈다 — iter_parts 는 앞 조각을 붙들고 있어 피크가 2배가 된다
        for _p in sorted(glob.glob(os.path.join(ROOT, "brain", "cache", "hotbar_parts", "part_*.json.gz"))):
            with gzip.open(_p, "rt", encoding="utf-8") as fh:
                d = json.load(fh)
            daily = d.get("daily") or {}
            names = d.get("names") or {}
            for c, rows in daily.items():
                if c not in themes:
                    continue
                nm = names.get(c)
                if not nm or S.excluded_name(nm):
                    continue
                r = clean(rows)
                if len(r) < 140:
                    continue
                wk = S.bar_groups(r, S.week_key)
                mo = S.bar_groups(r, S.month_key)
                ll = S.long_lines(r, wk, mo, len(r) - 1)
                rec = [c, nm, r[-LIGHT_BARS:],
                       [[b[0], round(b[4], 1)] for b in wk[-LIGHT_WEEKS:]],
                       [[b[0], round(b[4], 1)] for b in mo[-LIGHT_MONTHS:]],
                       [ll.get("w240"), ll.get("m120"), ll.get("w240_full"), ll.get("m120_full")]]
                f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
                n += 1
            del daily, names, d
            gc.collect()
    os.replace(tmp, LIGHT_CACHE)
    print("10년 원본 → 얇은 캐시 %d종목 (%.1fMB) 새로 만듦" % (n, os.path.getsize(LIGHT_CACHE) / 1e6), flush=True)
    return _light_read(sig, themes) or {}


def theme_bars(themes):
    """테마 DB 종목의 일봉 — 얇은 캐시(최근 700봉 + 장기선)만 읽는다.

    예전에는 32MB stage10_pool.json.gz(880종목 × 10년 봉)를 통째로 풀어 881MB를 썼다.
    이제 295MB · 0.9초. 장기선(주봉 240·월봉 120)은 캐시에 미리 재 둔 값을 쓴다.
    """
    sig = parts_sig()
    got = _light_read(sig, themes)
    if got is None:
        got = _light_build(sig, themes)
    return got


def load_themes():
    """code -> [{name, summary, flow, pos, last}] (최근 상한가가 늦은 테마를 앞에)"""
    db = json.load(open(DB, encoding="utf-8"))
    out = {}
    for t in db.get("목록") or []:
        name = (t.get("테마") or "").strip()
        if not name or "미확인" in name:
            continue
        for key in ("상한가", "대표종목"):
            for s in t.get(key) or []:
                c = str(s.get("종목코드") or "").strip()
                if not c:
                    continue
                ds = [d for d in (s.get("상한가일") or []) if d]
                last = max(ds) if ds else ""
                ent = out.setdefault(c, [])
                if any(x["name"] == name for x in ent):
                    continue
                ent.append({"name": name, "summary": (t.get("이슈요약") or "").strip(),
                            "flow": (t.get("흐름단계") or "").strip(),
                            "pos": (t.get("현재위치") or "").strip(), "last": last,
                            "kind": (t.get("테마구분") or "").strip(),
                            "dates": ds, "lu_theme": key == "상한가"})
    for c, ent in out.items():
        ent.sort(key=lambda x: (x["last"], x["lu_theme"]), reverse=True)
    return out


# ---------------------------------------------------------------- 진단
def pick_anchor(rows, luf, need=60):
    """오늘 기준 닻 — 최근 250봉 안, 앞 need봉 무상한가인 마지막 상한가."""
    n = len(rows)
    for i in range(n - 2, max(need, n - 250) - 1, -1):
        if not luf[i]:
            continue
        prev = [x for x in range(max(0, i - 125), i) if luf[x]]
        if prev and i - max(prev) < need:
            continue
        return i
    return None


def swing_count(rows, q, end):
    return S.count_swings(rows[q:end]) if end > q else 0


def latest_hotbar_pair(rows, i0):
    """가장 최근의 '②하락 음봉 → ③ 윗꼬리 긴 양봉(핫바)' 짝 — 2026-11-21 지시.

    한싹(1번 11-03)처럼 1번 상한가 직후의 첫 눌림(2,650원)만 기준선으로 고정하지 않는다.
    상승 파동 고점(①) 뒤에 **앞 3봉보다 낮은 저점까지 민 하락 음봉(②)**이 멈서고 바로
    **몸통 크고 아랫꼬리 작고 윗꼬리 긴 양봉(③)**이 나오면, 기준선은 그 ②③ 아래
    (min(② 음봉 종가, ③ 양봉 저점))로 갱신한다 — 한싹 11-17 → 11-18 → 약 3,464원.

    돌려주는 값: {"b2": ②idx, "b3": ③idx, "line": 기준선} 또는 None.
    """
    n = len(rows)
    for i in range(n - 1, max(i0, 1) + 2, -1):          # ③ 후보 — 최근 봉부터
        o3, h3, l3, c3 = rows[i][1], rows[i][2], rows[i][3], rows[i][4]
        if not o3 or c3 <= o3:
            continue
        body = (c3 - o3) / o3
        up = (h3 - c3) / c3 if c3 else 0
        down = (o3 - l3) / c3 if c3 else 1
        if body < 0.03 or up < 0.05 or up < body or down > body * 0.6:
            continue                                     # 핫바 양봉만(긴 윗꼬리·큰 몸통·작은 아랫꼬리)
        for j in range(i - 1, max(i0, i - 4), -1):       # ② 후보 — 바로 앞 1~3봉
            if rows[j][4] >= rows[j][1]:
                continue
            lo = rows[j][3]
            prev = [r[3] for r in rows[max(i0, j - 3):j]]
            if not prev or lo >= min(prev):
                continue                                 # 앞 3봉보다 낮은 저점까지 민 음봉만
            if j + 1 < n and rows[j + 1][3] < lo:
                continue                                 # 그 자리에서 멈춘 저점(다음 봉이 더 낮으면 아직 내려오는 중)
            return {"b2": j, "b3": i, "line": min(rows[j][4], l3)}
    return None


def stock_names():
    """theme_db 상한가·대표종목의 종목코드 → 종목명 (10년 원본에 없는 종목 이름을 채운다)."""
    out = {}
    try:
        db = json.load(open(DB, encoding="utf-8"))
        for t in db.get("목록") or []:
            for key in ("상한가", "대표종목"):
                for s in t.get(key) or []:
                    c = str(s.get("종목코드") or "").strip()
                    n = (s.get("종목명") or "").strip()
                    if c and n and c not in out:
                        out[c] = n
    except Exception:
        pass
    return out


def extra_bars(codes, today, no_fetch=False):
    """10년 원본에 없는 테마 종목의 일봉(470봉) — 오늘 받아 둔 캐시가 있으면 그대로 쓴다.

    theme_db 에는 있는데 10년 원본(hotbar_parts)에는 없는 종목이 200여 개 있다. 그 종목들은
    단계를 잴 봉이 없어 화면(테마달력)에는 서고 1~10단계에는 못 서는 구멍이 됐다(2026-11-25).
    하루 한 번만 네이버에서 받아 두고, 다음 지정시간부터는 캐시만 읽는다(30분 갱신을 느리게 하지 않게).
    """
    cache = {}
    try:
        with gzip.open(EXTRA_BARS, "rt", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("date") == today:
            cache = d.get("stocks") or {}
    except Exception:
        cache = {}
    need = [c for c in codes if c not in cache]
    if need and not no_fetch:
        got = fetch_many(need, workers=16, count=EXTRA_COUNT)
        for c, rows in got.items():
            cache[c] = [r for r in rows if min(r[1:5]) > 0]
        try:
            with gzip.open(EXTRA_BARS, "wt", encoding="utf-8", compresslevel=1) as f:
                json.dump({"date": today, "stocks": cache}, f, ensure_ascii=False)
        except Exception as e:  # noqa: BLE001
            print("⚠ 테마 종목 일봉 캐시를 쓰지 못했습니다:", e, flush=True)
    return {c: v for c, v in cache.items() if len(v) >= 140}


def analyze(rows):
    """한 종목 — 닻·1~10단계·4→5/9단계 자리·앞뒤를 한 번에 잰다."""
    n = len(rows)
    if n < 140:
        return None
    t = n - 1
    luf = S.lu_flags(rows)
    w2 = wave2_of(rows)        # 1파 vs 2파 거래량 — 세력 보유/털기 (2026-11-25 지시)
    i0 = pick_anchor(rows, luf)
    if i0 is None:
        return None
    prev_lu = max((x for x in range(i0) if luf[x]), default=None)
    gap = i0 - prev_lu if prev_lu is not None else i0
    lu_open = rows[i0][1]                   # 1번 봉 시가(참고값) — 가격 기준선이 아니다
    sp = S.stage_path(rows, i0, luf)
    if sp is None:
        return None
    # 그림 기준선(2026-11-21 지시) — ② 눌림 저점. ③ 반등 양봉이 실제로 나온 뒤에야 선을 긋는다.
    q0, d3 = sp.get("q"), sp.get("h_days_3")
    x3 = (q0 + d3) if (q0 is not None and d3) else None
    line2 = rows[q0][3] if q0 is not None else None
    # 2026-11-21 추가 지시 — 상승 파동 뒤 더 높은 자리에서 다시 ②하락 음봉 → ③ 윗꼬리 긴 양봉이
    #   나오면 기준선을 그 ②③ 아래(min(② 종가, ③ 저점))로 갱신한다(한싹 11-17 → 11-18 → 약 3,464원).
    pair = latest_hotbar_pair(rows, i0)
    if pair and (x3 is None or pair["b3"] > x3):
        if any(rows[k][4] > rows[pair["b3"]][2] for k in range(pair["b3"] + 1, n)):
            pair = None                     # ③ 뒤에 그 고점을 넘겼으면 이미 다음 단계 자리
    # 2026-11-25 — 새 ②③ 줄 아래로 이미 무붑진 종목은 '4단계(사는 자리)'가 아니다.
    #   제주은행(1번 01-27, 125봉 밖)처럼 오래된 상한가 뒤 한참 지나 나온 ②③을 4단계로 읽어
    #   "오늘 사는 자리"로 올리던 오류를 막는다 — 줄을 깨면 단계 계산(stage_path)에 맡긴다.
    if pair and rows[n - 1][4] < pair["line"] * 0.97:
        pair = None
    if pair:
        q0, x3, line2 = pair["b2"], pair["b3"], pair["line"]
    base = line2 if x3 is not None else None
    pair_info = {"b2": rows[pair["b2"]][0], "b3": rows[pair["b3"]][0]} if pair else None
    o = {"i0": i0, "d0": rows[i0][0], "base": base, "lu_open": lu_open, "gap": gap,
         "q": q0, "x3": x3, "line2": line2, "pair": pair_info,
         "d3_date": rows[x3][0] if x3 is not None else None,
         "t": "A" if gap >= 125 else "B", "cand": None}
    q, b, p1 = sp.get("q"), sp.get("b"), sp.get("p1")
    d = {"stage": 1, "label": "1단계(길목)", "box_hi": None, "box_lo": None, "sw": None,
         "vol4": None, "y4": None, "hold4": None}
    if pair:
        # 새 ②③ 그림 — ③ 뒤 줄에 닿았으면 4번(④ 할 자리), 아직 안 내려왔으면 3번(③ 핫바 뒤)
        post = list(range(x3 + 1, n))
        touch = next((i for i in post if rows[i][3] <= base * LINE_TOUCH), None)
        y4 = next((i for i in reversed(post) if rows[i][4] < rows[i][1]), None)
        if touch is None:
            d.update({"stage": 3, "label": "3단계(③ 핫바 뒤)",
                      "from_hi": (rows[n - 1][4] / max(r[2] for r in rows[x3:n]) - 1)})
        else:
            vol4 = hold4 = None
            if y4 is not None and y4 > x3:
                pv = st.mean([r[5] for r in rows[max(0, y4 - 5):y4]]) or rows[y4][5]
                vol4 = round(rows[y4][5] / pv, 2) if pv else None
                hold4 = rows[y4][3] >= base * 0.95
            d.update({"stage": 4, "label": "4단계(④ 줄 자리)", "vol4": vol4, "y4": y4,
                      "hold4": hold4, "box_hi": max(r[2] for r in rows[x3:n]),
                      "box_lo": min(r[3] for r in rows[x3:n]), "sw": 0,
                      "from_hi": (rows[n - 1][4] / max(r[2] for r in rows[x3:n]) - 1)})
            if vol4 is not None and vol4 <= VOL4_MAX and hold4:
                d["cand"] = "A4"
    elif b is None:
        if q is None:
            d.update({"stage": 2 if t > p1 else 1, "label": "2단계(눌림 없음)"})
        elif t <= q + 2:
            d.update({"stage": 2, "label": "2단계(핫바)"})
        else:
            box_hi, box_lo = sp.get("box_hi"), sp.get("box_lo")
            sw = sp.get("swings")
            bwd = (box_hi / box_lo - 1) if box_lo else None
            y = t if rows[t][4] < rows[t][1] else (t - 1 if rows[t - 1][4] < rows[t - 1][1] else None)
            vol4 = hold4 = None
            if y is not None and y > q + 1:
                pv = st.mean([r[5] for r in rows[max(0, y - 5):y]]) or rows[y][5]
                vol4 = round(rows[y][5] / pv, 2) if pv else None
                hold4 = rows[y][3] >= (base or lu_open) * 0.95
            d.update({"stage": 3, "label": "3단계(상자)", "box_hi": box_hi, "box_lo": box_lo,
                      "sw": sw, "box_w": bwd, "vol4": vol4, "y4": y, "hold4": hold4,
                      "from_hi": (rows[t][4] / box_hi - 1) if box_hi else None,
                      "base_hold": sp.get("base_hold")})
            if (vol4 is not None and vol4 <= VOL4_MAX and hold4
                    and sw is not None and sw >= SW_MIN
                    and bwd is not None and bwd <= BOX_MAX_W
                    and d["from_hi"] is not None and -0.35 <= d["from_hi"] <= 0.0
                    and x3 is not None and x3 < y):        # ③ 반등 양봉이 나온 뒤의 음봉만
                d.update({"stage": 4, "label": "4단계(음봉·매수 자리) ", "cand": "A4"})
    else:
        y4 = next((x for x in range(b - 1, max(q if q is not None else 0, b - 11), -1)
                   if rows[x][4] < rows[x][1]), None)
        vol4 = hold4 = None
        if y4 is not None:
            pv = st.mean([r[5] for r in rows[max(0, y4 - 5):y4]]) or rows[y4][5]
            vol4 = round(rows[y4][5] / pv, 2) if pv else None
            hold4 = rows[y4][3] >= (base or lu_open) * 0.95
        box_hi, box_lo = sp.get("box_hi"), sp.get("box_lo")
        sw = sp.get("swings")
        bwd = (box_hi / box_lo - 1) if box_lo else None
        d.update({"stage": 5 if t <= b else 6, "box_hi": box_hi, "box_lo": box_lo,
                  "sw": sw, "box_w": bwd, "vol4": vol4, "y4": y4, "hold4": hold4,
                  "b": b})
        if t <= b:
            d["label"] = "5단계(돌파 당일)"
            if (b == t and y4 is not None and vol4 is not None and vol4 <= BRK_VOL4_MAX
                    and hold4 and sw is not None and sw >= SW_MIN
                    and bwd is not None and bwd <= BOX_MAX_W):
                d["cand"] = "A5"
        else:
            p6, top = sp.get("p6"), sp.get("top")
            if p6 is not None and t <= p6:
                d.update({"stage": 6, "label": "6단계(분출)"})
            elif top is not None and t <= top + 3:
                d.update({"stage": 7, "label": "7단계(숨쉬는)"})
            elif top is not None:
                dd = rows[t][4] / rows[top][2] - 1
                w = rows[max(0, t - 14):t + 1]
                rng = (max(r[2] for r in w) / min(r[3] for r in w) - 1) if len(w) == 15 else 9
                run = st.mean([r[5] for r in rows[b:top + 1]]) or 1
                volx = st.mean([r[5] for r in w]) / run
                paused = bool(dd <= -0.25 and rng <= C_RNG15)
                # 2026-11-25 지시 — 1파보다 큰 거래량으로 2파를 털고 내려온 자리는 '하락 멈춤(9단계)'이
                #   아니라 **8단계 매도**로 본다. 거래량이 줄며 가볍게 간 자리만 9단계(쉬는 자리)로 남긴다.
                dump2 = bool(w2 and w2.get("kind") == "털기" and w2.get("top_i") is not None
                             and abs(int(w2["top_i"]) - int(top)) <= 1)
                if paused and dump2:
                    paused = False
                d.update({"stage": 9 if paused else 8,
                          "label": "9단계(하락 멈춤)" if paused
                                   else ("8단계(2파 털기·매도)" if dump2 else "8단계(내려오는 중)"),
                          "dd": round(dd, 4), "rng15": round(rng, 4), "volx9": round(volx, 2),
                          "top": top, "pause_low": min(r[3] for r in w)})
                if dump2:
                    d["w2_dump"] = True
    o.update(d)
    # 단계는 여기서 한 번 적는다 — 예전에는 이 줄이 유형 C 판정 **뒤**에 있어서,
    #   유형 C로 9단계를 적어도 d["stage"](8)가 다시 덮어썼다(2026-11-25 수정).
    o["stage"] = d["stage"]
    # ---- 2026-11-25 — 125봉(6개월) 밖으로 오래된 상한가: 돌파 없이 무너진 자리는 3·4단계가 아니라 9·10단계다
    #   제주은행(1번 2026-01-27)처럼 상자 돌파 없이 60봉 넘게 흘러 2번 저점 아래로 내려간 종목을
    #   '4단계(사는 자리)'로 오판하던 것을 바로잡는다.
    if d["stage"] == 3 and b is None and q is not None and (t - q) >= 60:
        low2 = sp.get("low2")
        if low2 and rows[t][4] <= low2 * 0.85:
            w = rows[max(0, t - 14):t + 1]
            rng = (max(r[2] for r in w) / min(r[3] for r in w) - 1) if len(w) == 15 else 9
            run_vol = st.mean([r[5] for r in rows[i0:p1 + 1]]) or 1
            calm = (st.mean([r[5] for r in w]) / run_vol) <= C_VOL
            paused = (rng <= C_RNG15 and calm)
            d.update({"stage": 9 if paused else 10,
                      "label": "9단계(하락 멈춤)" if paused else "10단계(오래된 상한가·폐기)",
                      "old_lu": True, "rng15": round(rng, 4),
                      "pause_low": min(r[3] for r in w)})
            o["stage"] = d["stage"]
            o["label"] = d["label"]
            if paused:
                o["pause_hi"], o["pause_lo"] = max(r[2] for r in w), min(r[3] for r in w)
    # ---- 유형 C — 분출 뒤 -25% + 15봉 폭 20% + 거래량 0.5배
    #   2026-11-25 — 2파 대량분출(털기)로 내려온 자리는 유형 C(9단계 재출발·매수)로 올리지 않는다.
    if (d.get("cand") is None and d.get("top") is not None and d.get("dd") is not None
            and not (w2 and w2.get("kind") == "털기" and w2.get("top_i") is not None
                     and abs(int(w2["top_i"]) - int(d["top"])) <= 1)):
        if (d["dd"] <= C_DD and d.get("rng15", 9) <= C_RNG15
                and C_VOL_MIN <= (d.get("volx9") or 0) <= C_VOL):
            w = rows[max(0, t - 14):t + 1]
            o["cand"] = "C"
            o["t"] = "C"
            o["pause_hi"], o["pause_lo"] = max(r[2] for r in w), min(r[3] for r in w)
            o["stage"], o["label"] = 9, "9단계(하락 멈춤 · 매수)"
            o["base"] = None          # 유형 C는 2번 기준선이 아니라 멈춤 상자로 본다
    # ---- ④ 자리의 속도·형태 (2026-11-24 지시 — '빠른 ④' · '고가 위 ④' 배지)
    #   ④ = ③(반등 양봉) 뒤 ② 기준선까지 다시 내려온 첫 봉.
    #   속도 = 상한가일(i0) → ④ 거래일 수. 10~25일 안이 1순위, 25일 넘으면 한 단계 낮춘다.
    #   형태 = B형(상한가 봉 고가 위를 먼저 찍고 내려온 ④, +20% 62.5%) vs A형(바로 온 ④, 55.0%).
    if base and x3 is not None and n - 1 > x3:
        d4 = next((k for k in range(x3 + 1, n) if rows[k][3] <= base * LINE_TOUCH), None)
        if d4 is not None:
            o["d4_date"] = rows[d4][0]
            o["d4_days"] = d4 - i0
            o["d4_type"] = "B" if any(rows[k][2] > rows[i0][2] for k in range(i0 + 1, d4 + 1)) else "A"
    o["w2"] = w2              # 2파 거래량 신호 — 카드 배지 (2026-11-25 지시)
    return o


# ---------------------------------------------------------------- 3번 첫 거래 판정 (2026-11-21 지시)
#   brain/integrated_response_10stage_study.md §4-5 그대로 — 3번 날에 눈으로 볼 수 있는 세 가지로 A/B/C/D.
#     A = 월봉 첫 거래량 터짐 + 3번 큼 + 지수 위·꺾임 아님
#     B = 월봉 첫 거래량 터짐 + 3번 큼 (지수가 꺾이는 날)
#     C = 3번 큼 · 월봉 아직
#     D = 3번 작음(보통·약함) — 사지 않는 자리
#   화면에는 글자만 보인다(가격·% 없음).
SIZE3_BIG = 0.10      # 3번 크기 = 3번 종가 / 2번 저점 - 1. 10% 이상 = 큼
SIZE3_MID = 0.03      # 3% 이상 = 보통, 그 아래 = 약함


def month_vols(rows):
    """일봉 → 달별 거래량 합(완성 봉) [ [YYYY-MM, 거래량, 끝idx, 시작idx], ... ]"""
    out = []
    for i, r in enumerate(rows):
        k = r[0][:7]
        if out and out[-1][0] == k:
            out[-1][1] += r[5]
            out[-1][2] = i
        else:
            out.append([k, r[5], i, i])
    return out


def first_month_vol(rows, x3):
    """3번 날까지 그 달 누적 거래량 >= 앞 6개월 완성 봉 최대 → '터짐', 아니면 '아직'.

    10년 전수조사에서 실제로 갈린 축 — 사는 날 보이는 값만 쓴다(미래 봉 없음).
    """
    if x3 is None or x3 >= len(rows):
        return None
    k = rows[x3][0][:7]
    start = next((i for i, r in enumerate(rows) if r[0][:7] == k), None)
    ms = month_vols(rows)
    j = next((n for n, m in enumerate(ms) if m[0] == k), None)
    if start is None or j is None:
        return None
    prev = ms[max(0, j - 6):j]
    if len(prev) < 2:
        return None
    cum = sum(r[5] for r in rows[start:x3 + 1])
    return "터짐" if cum >= max(m[1] for m in prev) else "아직"


def week_vols(rows):
    """일봉 → 주(월~금)별 거래량 합 [ [ISO주, 거래량, 끝idx, 시작idx], ... ]"""
    out = []
    for i, r in enumerate(rows):
        k = S.week_key(r[0])
        if out and out[-1][0] == k:
            out[-1][1] += r[5]
            out[-1][2] = i
        else:
            out.append([k, r[5], i, i])
    return out


def first_week_vol(rows, x3):
    """주봉 첫 거래량 — 3번 날까지 그 주 누적 거래량 >= 앞 48주 완성 봉 최대 → '터짐', 아니면 '아직'.

    예전 '주봉' 칸이 보던 48주 최대 돌파를 테마 추적(10단계) 판정에 함께 싣는다(2026-11-23 지시 #12042).
    사는 날 보이는 값만 쓴다 — 3번 봉 이후 봉은 보지 않는다.
    """
    if x3 is None or x3 >= len(rows):
        return None
    k = S.week_key(rows[x3][0])
    start = next((i for i, r in enumerate(rows) if S.week_key(r[0]) == k), None)
    ws = week_vols(rows)
    j = next((n for n, w in enumerate(ws) if w[0] == k), None)
    if start is None or j is None:
        return None
    prev = ws[max(0, j - 48):j]
    if len(prev) < 8:
        return None
    cum = sum(r[5] for r in rows[start:x3 + 1])
    return "터짐" if cum >= max(w[1] for w in prev) else "아직"


def ma240_side(rows, i0):
    """일봉 240선 위/아래 — 상한가 전날 종가로 잰다(전수조사와 같은 잣대)."""
    j = (i0 or 0) - 1
    if j + 1 < 240:
        return None
    ma = st.mean([r[4] for r in rows[j + 1 - 240:j + 1]])
    return "위" if ma and rows[j][4] > ma else "아래"


def index_bent(mkt):
    """지수 '위·꺾임'(20일선 위인데 20일선이 꺾여 내려오는 중)인가 — 전수조사에서 제일 위험한 국면."""
    for k in ("kospi", "kosdaq"):
        d = (mkt or {}).get(k) or {}
        c, ma20, ma5 = d.get("close"), d.get("ma20"), d.get("ma5")
        if c and ma20 and ma5 and c > ma20 and ma20 < ma5:
            return True
    return False


def size3_of(rows, q, x3):
    """3번 크기 — 3번 종가가 2번 저점 위에서 얼마나 올라섰나(글자로만)."""
    if q is None or x3 is None or x3 >= len(rows):
        return None, None
    low2 = rows[q][3]
    if not low2:
        return None, None
    v = rows[x3][4] / low2 - 1
    return ("큼" if v >= SIZE3_BIG else ("보통" if v >= SIZE3_MID else "약함")), v


def first_vol_ratio(rows, i0):
    """첫 거래량 — 상한가 봉 거래량 ÷ 앞 125봉 최대(1.0배 넘으면 그 구간 첫 거래량)."""
    if i0 is None or i0 < 1 or i0 >= len(rows):
        return None
    prior = [r[5] for r in rows[max(0, i0 - 125):i0]]
    if len(prior) < 60 or not max(prior):
        return None
    return round(rows[i0][5] / max(prior), 1)


def first_trade_judge(rows, a, mkt):
    """3번 첫 거래 판정 — {"grade","size","ma240","wvol","bent","v1"} (가격·%는 담지 않는다).

    2026-11-21 지시: '대기' 같은 꼬리말은 두지 않는다 — A/B/C만 판정이고, D는 사지 않는 자리다.
    3번이 아직 없으면 판정 없음(None)으로 둔다.
    """
    out = {"grade": None, "size": None, "ma240": None, "wvol": None, "vw": None,
           "bent": index_bent(mkt), "v1": None}
    if not a:
        return out
    q, x3 = a.get("q"), a.get("x3")
    out["ma240"] = ma240_side(rows, a.get("i0"))
    out["v1"] = first_vol_ratio(rows, a.get("i0"))          # 첫 단추 — 상한가 첫 거래량
    out["wvol"] = first_month_vol(rows, x3)          # 월봉 12개월(앞 6개월 최대) 첫 거래량
    out["vw"] = first_week_vol(rows, x3)             # 주봉 48주 최대 첫 거래량
    out["size"], v = size3_of(rows, q, x3)
    if a.get("t") == "C" or x3 is None:
        out["size"] = None        # 3번이 아직 없는 자리 — 판정 없음
        return out
    if v is None or v < SIZE3_BIG:
        out["grade"] = "D"         # 3번이 작은 자리 — 사지 않는다(매수 목록에서 뺀다)
    elif out["wvol"] == "터짐":
        out["grade"] = "A" if not out["bent"] else "B"
    else:
        out["grade"] = "C"
    return out


def full_rows(code, pool, latest, fresh):
    """앞/뒤(주봉 240선·월봉 120선)를 재려면 장기 이력이 필요하다 —
    2026-11-25부터는 10년 봉을 다 들고 있지 않고, 얇은 캐시의 최근 700봉에 오늘 봉만 덮는다.
    장기선 자체는 LONG_LINES(캐시에 미리 잰 값)를 쓴다."""
    nm, rows0, th = pool[code]
    rows = merge_with_fresh(rows0, latest.get(code))
    return merge_with_fresh(rows, clean(fresh.get(code) or []))


def lu_index(pool, latest, fresh, themes=None):
    """종목코드 → 최근 상한가 날짜 집합 — 테마 크기(동반 상한가)를 재는 재료.

    우리 일봉(+28.5%)에서 잡은 날과 테마 DB 상한가일을 합친다 — DB가 그 테마의 동반 상한가를
    더 넓게 기록해 둔 경우(장중 상한가·호가 차이)를 놓치지 않기 위해서다.
    """
    out = {}
    for c, (nm, rows0, th) in pool.items():
        rows = merge_with_fresh(clean(rows0[-140:]), latest.get(c))
        rows = merge_with_fresh(rows, clean(fresh.get(c) or []))
        dates = set()
        if rows:
            luf = S.lu_flags(rows)
            dates = {rows[i][0] for i in range(len(rows)) if luf[i]}
        for t in (themes or {}).get(c) or ():
            dates |= {d for d in (t.get("dates") or []) if d}
        if dates:
            out[c] = dates
    return out


def theme_size(lu, members, code, date0, days=7):
    """테마 크기 — 같은 테마에서 상한가 날짜가 date0 앞 7일 안인 종목 수(나 포함)."""
    if not date0:
        return None
    cut = (datetime.fromisoformat(str(date0)[:10]) - timedelta(days=days)).isoformat()[:10]
    n = 1
    for c in members or ():
        if c == code:
            continue
        if any(cut <= d <= date0 for d in lu.get(c, ())):
            n += 1
    return n


def wave_over(rows) -> tuple[bool, str]:
    """최근 125봉 안에 **큰 상한가 파동이 한 번 크게 생겼다가 끝나고 꺾여 내려온 자리**인가.

    2026-11-25 푸른하늘님 손그림 기준:
      · 앞쪽 = 앞에 큰 파동 없이 깊은 바닥에서 막 첫 상한가가 나온 초입, 또는 한싹(430690)처럼
        첫 상한가 뒤 기준선·추세를 깨지 않고 버티며 횡보·반등하는 자리.
      · 뒤쪽 = 인디에프·에스피소프트·SGA솔루션즈처럼 125봉 안에 큰 파동/고점이 생겼다가
        그 파동이 끝나 고점 대비 20% 이상 밀리고 20일선까지 깨고 내려온 자리.
    그래서 '60일선 위'만으로 자르지 않는다 — 그렇게 하면 깊은 바닥에서 막 출발한
    진짜 앞쪽(첫 상한가)까지 잘려 나간다.
    """
    n = len(rows)
    if n < 30:
        return False, ""
    win = rows[-125:]
    first = None
    for i in range(1, len(win)):
        if win[i - 1][4] and win[i][4] / win[i - 1][4] - 1 >= 0.15:      # 급등(상한가·15%+) 봉
            first = i
            break
    if first is None:
        return False, ""
    peak_i = max(range(first, len(win)), key=lambda i: win[i][2])
    peak = win[peak_i][2]
    c = rows[-1][4]
    if not peak:
        return False, ""
    drop = c / peak - 1
    dcl = [r[4] for r in rows]
    ma20 = st.mean(dcl[-20:]) if len(dcl) >= 20 else None
    ma60 = st.mean(dcl[-60:]) if len(dcl) >= 60 else None
    broken = bool((ma20 and c < ma20) or (ma20 and ma60 and ma20 < ma60))
    # 2026-11-25 지시 — 고점 대비 -50% 이상 빠져 출발선까지 반납한 자리는 **확실히 뒷쪽**
    #   (인디에프 = 4,970원 고점 → -59.8%). 반대로 큰 테마 초입에서 -30~-45%만 식혔다가
    #   새 상한가(2차 핫바)가 붙어 그 봉 시가·출발선을 지키는 자리는 버리지 않는다(pullback_entry).
    if drop <= -0.50:
        return True, "125봉 파동 고점(%.0f) 뒤 %+.0f%% · 출발선까지 반납" % (peak, drop * 100)
    if pullback_entry(rows)[0]:
        return False, ""                     # 큰 테마 초입 -40% 조정 뒤 2차 핫바 사수
    if drop <= -0.20 and broken and (len(win) - 1 - peak_i) >= 3:
        return True, "125봉 안 파동 고점(%.0f) 뒤 %+.0f%% · 추세 이탈" % (peak, drop * 100)
    return False, ""


# ---------------------------------------------------------------- 2파 거래량 · 초입 -40% 조정 (2026-11-25 지시)
#   "핫바 이후 상승이 상한가면 아래 거래량 크기로 일단 보자" — 1파 최대 vs 2파 최대.
#   "첫상한가 일때 몰라. 재료 파악이 상당히 중요하고 지속적으로 추적" — 그래서 이 신호는
#   담 판정이 아니라 '세력이 아직 물량을 쥐고 있나(보유) / 털었나(털기)'만 말한다.
SURGE_WAVE = 0.15     # 급등 봉 — 파동의 씨앗(상한가·15%+)
WAVE_GAP = 5          # 5거래일 안에 붙은 급등 봉은 같은 파동
WAVE_TAIL = 3         # 파동 끝 뒤 3봉까지 그 파동의 거래량으로 본다(윗꼬리·물량 터진 날)
WAVE_RECENT = 30      # 마지막 파동이 이만큼 지났으면 카드에 달지 않는다
WAVE_KEEP = 0.85      # 2파 최대 거래량 ≤ 1파 × 0.85 → '가벼움(보유)'
WAVE_DUMP = 1.02      # 2파 최대 거래량 ≥ 1파 × 1.02 → '대량분출(털기)' — 1.00 근처는 '비슷'
PULL_MIN, PULL_MAX = -0.45, -0.20   # 큰 테마 초입 조정 — 약 -40% 내외(-20~-45%)
PULL_RECENT = 40      # 2차 핫바가 이 안에 붙어 있어야 '초입 진행'으로 본다


def _wave_groups(rows, win=250, luf=None):
    """최근 win봉의 급등 봉을 5봉 간격으로 묶어 '파동'으로 만든다.

    luf(상한가 플래그)를 주면 **진짜 상한가 봉**만 씨앗으로 쓴다 — 15%짜리 잡음 봉이
    '1파'로 둔갑해 엉뚝한 배수를 만들지 않게 한다(2026-11-25 한싹 8/4 +15.9% 30만주 사례).
    """
    n = len(rows)
    s = max(1, n - win)
    if luf is not None:
        seeds = [i for i in range(s, n) if luf[i]]
    else:
        seeds = [i for i in range(s, n)
                 if rows[i - 1][4] and rows[i][4] / rows[i - 1][4] - 1 >= SURGE_WAVE]
    groups: list[list[int]] = []
    for i in seeds:
        if groups and i - groups[-1][-1] <= WAVE_GAP:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def _wave_vol(rows, g):
    """한 파동의 최대 거래량 봉 — 파동 앞 1봉 ~ 끝 뒤 3봉(WAVE_TAIL)."""
    a, b = max(0, g[0] - 1), min(len(rows), g[-1] + 1 + WAVE_TAIL)
    seg = list(range(a, b))
    k = max(seg, key=lambda i: rows[i][5])
    top = max(seg, key=lambda i: rows[i][2])
    return {"i": k, "v": rows[k][5], "top_i": top, "hi": rows[top][2]}


def wave2_of(rows, luf=None):
    """핫바 이후 2파 거래량 크기 — **바로 앞 파동** 최대 vs 2파 최대 (2026-11-25 지시).

    · 2파 거래량 < 1파(줄면서 가볍게 상승)  → 세력이 아직 물량을 쥐고 있다 '보유'
    · 2파 거래량 ≥ 1파(대량 분출 + 윗꼬리)   → 세력이 털어낸 자리 '털기'  (8단계 매도 쪽)
    3파가 와도 같은 잣대(이번 파동 vs 앞 파동)로 잰다. 2파 상한가 봉 시가를 5% 이상 깬
    '보유' 신호는 이미 무효라 카드에 달지 않는다(털기 경고는 그대로 남긴다).
    """
    n = len(rows)
    if n < 40:
        return None
    luf = luf or S.lu_flags(rows)
    groups = _wave_groups(rows, 125, luf)          # 상한가 파동만 · 최근 125봉 안
    if len(groups) < 2:
        return None
    g1, g2 = groups[-2], groups[-1]
    if n - 1 - g2[-1] > WAVE_RECENT:
        return None
    w1, w2 = _wave_vol(rows, g1), _wave_vol(rows, g2)
    if not w1["v"] or not w2["v"]:
        return None
    ratio = w2["v"] / w1["v"]
    bar = rows[w2["i"]]
    tail = bool(bar[4] and (bar[2] - bar[4]) / bar[4] >= 0.03)      # 윗꼬리 3% 이상
    kind = "털기" if ratio >= WAVE_DUMP else ("보유" if ratio <= WAVE_KEEP else "비슷")
    broken = bool(rows[g2[0]][1] and rows[-1][4] < rows[g2[0]][1] * 0.95)
    if broken and kind == "보유":
        return None                                         # 줄이 끊긴 '보유'는 신호가 아니다
    return {"ratio": round(ratio, 2), "kind": kind, "tail": tail, "broken": broken,
            "v1": int(w1["v"]), "v2": int(w2["v"]),
            "d1": rows[g1[-1]][0], "d2": rows[g2[-1]][0],
            "i2": w2["i"], "top_i": w2["top_i"], "hi2": w2["hi"],
            "txt": "1파(%s) 최대 %s → 2파(%s) 최대 %s (%.2f배)%s" % (
                rows[g1[-1]][0][5:].replace("-", "."), fmt(w1["v"]),
                rows[g2[-1]][0][5:].replace("-", "."), fmt(w2["v"]), ratio,
                " · 윗꼬리" if tail else "")}


def pullback_entry(rows):
    """큰 테마 초입 '-40% 내외' 조정 뒤 2차 핫바가 기준선을 지키는 자리인가 (2026-11-25 지시).

    · 고점 대비 -30~-45%(-20~-45% 문턱)만 식히고 출발선은 안 반납
    · 조정 뒤 새 상한가(2차 핫바)가 최근 40봉 안에 붙어 그 봉 시가를 지킴
    인디에프처럼 -50% 이상 밀려 출발선까지 다 반납한 자리는 걸리지 않는다(뒷쪽 유지).
    """
    n = len(rows)
    if n < 60:
        return False, ""
    win = rows[-125:]
    first = next((i for i in range(1, len(win))
                  if win[i - 1][4] and win[i][4] / win[i - 1][4] - 1 >= SURGE_WAVE), None)
    if first is None:
        return False, ""
    peak_i = max(range(first, len(win)), key=lambda i: win[i][2])
    peak, c = win[peak_i][2], rows[-1][4]
    if not peak or not c:
        return False, ""
    drop = c / peak - 1
    if not (PULL_MIN <= drop <= PULL_MAX):
        return False, ""
    off = n - len(win)
    luf = S.lu_flags(rows)
    lus = [i for i in range(max(1, off), n) if luf[i] and i > off + peak_i]
    if not lus or (n - 1 - lus[-1]) > PULL_RECENT:
        return False, ""                                     # 조정 뒤 새 상한가가 없다
    last_lu = lus[-1]
    launch = win[max(0, first - 1)][4]                        # 출발선 = 1파 직전 종가
    if launch and c <= launch * 1.10:
        return False, ""                                     # 출발선까지 반납 — 초입 아님
    if c < rows[last_lu][1] * 0.95:
        return False, ""                                     # 2차 핫바 봉 시가를 깼다
    return True, "큰 테마 초입 %+.0f%% 조정 뒤 %s 2차 핫바 · 시가 사수" % (
        drop * 100, rows[last_lu][0][5:].replace("-", "."))


def side_of(rows, code=None):
    """앞쪽/뒷쪽 — 주봉 240선·월봉 120선(얇은 캐시 값) + 20/60일선.

    code 를 주면 캐시에 미리 재 둔 장기선으로 오늘 종가 기준 앞/뒤를 다시 잰다.
    (캐시가 없는 종목만 예전처럼 봉에서 직접 선을 긋는다)
    """
    ln = LONG_LINES.get(str(code)) if code else None
    if ln and (ln.get("w240") or ln.get("m120")):
        return long_side(rows, ln)
    wk = S.bar_groups(rows, S.week_key)
    mo = S.bar_groups(rows, S.month_key)
    out = S.long_lines(rows, wk, mo, len(rows) - 1)
    # 2026-11-25 — 봉에서 직접 잰 종목(얇은 캐시 밖)에도 같은 파동·초입 규칙을 적용한다.
    over, over_why = wave_over(rows)
    early, early_why = pullback_entry(rows)
    c = rows[-1][4]
    above = any(c > v for v in (out.get("w240"), out.get("m120")) if v)
    if over:
        out["side"], out["why"] = "뒷쪽", over_why
    elif early:
        out["side"], out["why"] = "초입", early_why
    return out


def long_side(rows, ln):
    """캐시해 둔 주봉 240선·월봉 120선 값으로 오늘 종가 기준 '앞쪽/뒷쪽'을 잰다.

    stage10_core.long_lines 의 뒷부분과 같은 규칙 — 오늘 종가·20/60일선만 봉에서 다시 본다.
    """
    out = {"w240": ln.get("w240"), "m120": ln.get("m120"), "ma20": None, "ma60": None,
           "dist_w240": None, "dist_m120": None, "side": None, "why": None,
           "w240_full": ln.get("w240_full"), "m120_full": ln.get("m120_full")}
    n = len(rows)
    if n >= 20:
        out["ma20"] = st.mean([r[4] for r in rows[-20:]])
    if n >= 60:
        out["ma60"] = st.mean([r[4] for r in rows[-60:]])
    c = rows[-1][4]
    if out["w240"]:
        out["dist_w240"] = round(c / out["w240"] - 1, 4)
    if out["m120"]:
        out["dist_m120"] = round(c / out["m120"] - 1, 4)
    long_ok = [v for v in (out["w240"], out["m120"]) if v]
    if not long_ok:
        return out
    below = all(c < v for v in long_ok)
    above = any(c > v for v in long_ok)
    ma_ok = (out["ma20"] and out["ma60"] and out["ma20"] >= out["ma60"])
    # 2026-11-25 지시 — 이미 큰 파동이 끝나 꺾여 내려온 자리는 장기선·20/60일선과 상관없이 '뒷쪽'.
    #   단, 큰 테마 초입에서 -40% 내외만 조정하고 2차 핫바가 기준선을 지키는 자리는 '초입'으로
    #   따로 세워 **버리지 않는다**(인디에프처럼 -50% 이상 반납한 자리는 그대로 뒷쪽).
    over, over_why = wave_over(rows)
    early, early_why = pullback_entry(rows)
    if over:
        out["side"] = "뒷쪽"
        out["why"] = over_why
    elif early:
        out["side"] = "초입"
        out["why"] = early_why
    elif above:
        out["side"] = "뒷쪽"
        out["why"] = "장기선 위"
    elif out["ma20"] and out["ma60"] and out["ma20"] < out["ma60"]:
        out["side"] = "뒷쪽"
        out["why"] = "20선<60선"
    elif below and ma_ok:
        out["side"] = "앞쪽"
    else:
        out["side"] = "중간"
    return out


# ---------------------------------------------------------------- 장부(매매 추적)
def load_watch():
    try:
        return json.load(open(WATCH, encoding="utf-8"))
    except Exception:
        return {"updated": None, "items": {}}


def save_watch(w):
    os.makedirs(os.path.dirname(WATCH), exist_ok=True)
    tmp = WATCH + ".tmp"
    json.dump(w, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, WATCH)


def trade_state(item, rows, st_now, base, pause_low):
    """지금 (상태, 이유, 매도정보) — 매수·보유·매도·손절을 봉으로 판정한다."""
    t = len(rows) - 1
    close, op, hi, lo = rows[t][4], rows[t][1], rows[t][2], rows[t][3]
    prev_c = rows[t - 1][4] if t > 0 else close
    stg = st_now.get("stage") or 0
    entry = item.get("entry_price") or close
    gain = close / entry - 1 if entry else 0
    ctype = item.get("type") or "A"
    # ---- 손절 — 기준선(2번 기준선) 이탈. 유형 C 는 재출발 뒤 재출발 봉 -10% 로 따라 올린다
    if ctype == "C" and item.get("restart_price"):
        stop = max(pause_low * PAUSE_STOP, item["restart_price"] * PAUSE_STOP_AFTER)
    else:
        stop = (pause_low * PAUSE_STOP) if ctype == "C" else (base * BASE_STOP)
    if stop and close < stop:
        return "손절·매도", "기준선 %s원 이탈(종가 %s원)" % (fmt(stop), fmt(close)), "stop"
    # ---- 유형 C — 재출발 전에는 9단계 매수(사는 자리), 멈춤 상자 위선을 넘으면 보유
    if ctype == "C":
        if not item.get("restart") and st_now.get("pause_hi") and close > st_now["pause_hi"]:
            item["restart"] = rows[t][0]
            item["restart_price"] = close
        if not item.get("restart"):
            return "9단계 매수", "멈춤 상자 %s~%s원 — 윗선 돌파가 재출발 신호" % (
                fmt(pause_low), fmt(st_now.get("pause_hi") or 0)), None
        if gain >= TARGET1 and reversal(rows):
            return "매도", "재출발 뒤 +%.1f%% · %s" % (gain * 100, reversal(rows)), "target"
        if stg == 10:
            return "매도", "10단계 스윙·폐기", "stage"
        return "분출·보유", "재출발 뒤 +%.1f%% — 들고 가는 자리" % (gain * 100), None
    # ---- A/B — 8단계면 물량 정리, 목표 +20~30% 뒤 꺾임이면 매도
    if stg >= 8:
        return "매도", "8단계 물량 정리(분출 고점 뒤)", "stage"
    if gain >= TARGET2:
        return "매도", "목표 +%.1f%% 달성 — 물량 정리" % (gain * 100), "target"
    if gain >= TARGET1:
        rev = reversal(rows)
        if rev:
            return "매도", "목표 +%.1f%% 뒤 %s" % (gain * 100, rev), "target"
    if stg >= 6:
        return "분출·보유", "%d단계 분출 — %+.1f%%" % (stg, gain * 100), None
    if stg == 5:
        return "돌파·보유", "5단계 돌파 유지 — %+.1f%%" % (gain * 100), None
    if stg <= 3:
        return "매수", "3번 핫바 뒤 — 4번(줄) 자리는 아직", None
    return "매수", "4단계 자리 유지 — %+.1f%%" % (gain * 100), None


def reversal(rows):
    """꺾임 — 윗꼬리(고가 대비 3% 이상 밀림) 또는 음봉으로 전일 종가 아래 마감. 없으면 None."""
    t = len(rows) - 1
    op, hi, lo, close = rows[t][1], rows[t][2], rows[t][3], rows[t][4]
    prev_c = rows[t - 1][4] if t > 0 else close
    if hi and close and (hi - close) / close >= 0.03:
        return "윗꼬리 꺾임"
    if close < op and close < prev_c:
        return "음봉 꺾임"
    return None


def fmt(v):
    try:
        return format(int(round(float(v))), ",")
    except Exception:
        return "—"


def days_between(rows, d0, d1):
    """두 날짜 사이 거래일 수(봉 기준)."""
    if not d0 or not d1:
        return 0
    return sum(1 for r in rows if d0 < r[0] <= d1)


# ---------------------------------------------------------------- 본체
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="파일 쓰지 않고 요약만")
    ap.add_argument("--no-fetch", action="store_true", help="오늘 봉을 새로 받지 않는다")
    ap.add_argument("--max", type=int, default=0, help="한 번에 보일 최대 종목(0=제한 없음)")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--no-risk", action="store_true",
                    help="재무·공시 위험 플래그(18-7)를 재지 않는다 — 시험용")
    args = ap.parse_args()
    t_start = time.time()

    now = kst_now()
    keep_from = (now.date() - timedelta(days=KEEP_DAYS)).isoformat()
    latest = load_delta(keep_from)
    market_last = max((r[-1][0] for r in latest.values() if r), default=None)
    if not market_last:
        print("⚠ 오늘 봉(brain/cache/hotbar_delta_*.jsonl.gz)이 없습니다 — 먼저 시세를 받아 주세요")
        return 1
    themes = load_themes()
    watch = load_watch()
    items = watch.setdefault("items", {})
    global WINDOWS, LEADER_OF
    WINDOWS = load_windows(market_last)          # 다가오는 창구 일정(레이더와 같은 표)
    LEADER_OF = load_leaders()                   # 테마별 대장주 — 👑 표시·정렬
    print("창구 일정 %d건 · 테마 대장주 %d테마" % (len(WINDOWS), len(LEADER_OF)), flush=True)

    # ---- 1) 10년 일봉에서 후보만 추린다(최근 470봉만 잘라 쓴다)
    pool = {}      # code -> (name, rows, theme)
    for c, (nm, rows) in theme_bars(themes).items():
        if c not in latest and len(rows) < 200:          # 오늘 봉도 없고 이력도 짧다
            continue
        pool[c] = (nm, rows, themes[c])
    # 10년 원본에 없는 테마 종목 — 받아 둔 일봉으로 채운다(1~10단계 밖으로 새지 않게)
    extra_n = 0
    try:
        miss_codes = [c for c in themes if c not in pool]
        if miss_codes:
            got = extra_bars(miss_codes, market_last, no_fetch=args.no_fetch)
            nmap = stock_names()
            for c, rows in got.items():
                pool[c] = (nmap.get(c) or c, rows, themes[c])
                extra_n += 1
            if extra_n:
                print("10년 원본에 없던 테마 종목 %d개 → 일봉 캐시로 단계 계산" % extra_n, flush=True)
    except Exception as e:  # noqa: BLE001
        print("⚠ 10년 원본 밖 테마 종목을 건너뜁니다:", e, flush=True)
    scanned = len(pool)
    if not pool:
        print("⚠ 살릴 후보가 없습니다")
        return 1

    # 후보를 좁힌다 — 오늘 봉이 있고, 거래대금이 되고, 최근 250봉에 상한가(닻)가 있는 종목
    short = []
    t_pre = time.time()
    for c, (nm, rows, th) in pool.items():
        tail = clean(rows[-WIN:])
        rows2 = merge_with_fresh(tail, latest.get(c))
        if len(rows2) < 140 or rows2[-1][0] != market_last:
            continue
        if S.val3(rows2, len(rows2) - 1) / 1e8 < VAL_MIN:
            continue
        luf = S.lu_flags(rows2)
        if pick_anchor(rows2, luf) is None:
            continue
        short.append(c)
    print("10년 일봉 %d종목 → 닻 있는 후보 %d종목 (%.1fs)"
          % (scanned, len(short), time.time() - t_pre), flush=True)

    # ---- 2) 후보 가운데 '오늘 자리'가 될 수 있는 종목만 시세를 새로 받는다
    need = set()
    pre = {}
    for c in short:
        nm, rows, th = pool[c]
        rows2 = merge_with_fresh(clean(rows[-WIN:]), latest.get(c))
        a = analyze(rows2)
        if a is None:
            continue
        pre[c] = a
        stg = a.get("stage") or 0
        if a.get("cand") or stg in (3, 4, 5) or stg in (8, 9) or stg in (6, 7):
            need.add(c)
    for c in list(items):                              # 장부 종목은 언제나 새 시세로
        if c in pool:
            need.add(c)
    fresh = {} if args.no_fetch else fetch_many(sorted(need))
    # 오늘 봉을 새로 받았으면 기준일도 오늘로 — 오늘 받은 시세가 캐시(delta)보다 최신이다
    if fresh:
        market_last = max([market_last] + [r[-1][0] for r in fresh.values() if r])
    print("새 시세 %d/%d종목 (%.1fs) · 기준일 %s" % (len(fresh), len(need), time.time() - t_pre,
                                                   market_last), flush=True)

    # ---- 3) 새 시세로 다시 재고, 조건에 맞는 종목을 뽑는다
    picks, seen = [], {}
    for c in sorted(pre):
        nm, rows, th = pool[c]
        rows2 = merge_with_fresh(clean(rows[-WIN:]), latest.get(c))
        rows3 = merge_with_fresh(rows2, clean(fresh.get(c) or []))
        a = analyze(rows3) if fresh.get(c) else pre[c]
        if a is None:
            continue
        if a.get("cand") is None:
            continue
        ll = side_of(full_rows(c, pool, latest, fresh), c)
        if a["cand"] == "C":
            entry_price = rows3[-1][4]
        else:
            entry_price = rows3[-1][4]
        picks.append({
            "code": c, "name": nm, "theme": th[0], "themes": [x["name"] for x in th][:3],
            "a": a, "rows": rows3, "side": ll.get("side"), "side_why": ll.get("why"),
            "dist_w240": ll.get("dist_w240"),
            "dist_m120": ll.get("dist_m120"), "price": rows3[-1][4],
            "prev": rows3[-2][4] if len(rows3) > 1 else rows3[-1][4],
            "entry_price": entry_price, "date": rows3[-1][0],
            "val3": round(S.val3(rows3, len(rows3) - 1) / 1e8, 1),
            "v1": v1_ratio(rows3, a["i0"]),
        })

    # ---- 4) 장부 갱신 — 오늘 새로 뜬 종목 등록, 기존 종목은 보유/매도까지 따라간다
    today = market_last
    added = []
    for p in picks:
        c = p["code"]
        if c in items:
            continue
        items[c] = {
            "code": c, "name": p["name"], "type": p["a"]["t"], "cand": p["a"]["cand"],
            "theme": p["theme"]["name"], "entry_date": today,
            "entry_price": int(round(p["entry_price"])),
            "base": int(round(p["a"]["base"])) if p["a"].get("base") else None,            "pause_low": int(round(p["a"].get("pause_lo") or 0)) or None,
            "stage0": p["a"]["stage"], "sw": p["a"].get("sw"),
            "first_seen": today, "status": "holding", "sold": None,
        }
        added.append(c)

    # ---- 4-1) 시장 지수·업종지수 — 지수가 약세인 날 종목을 정예로 줄인다
    mkt = market_doc()
    scache = load_sector_cache()
    view_codes = sorted(set([p["code"] for p in picks]) | set(items))
    ind_of = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for c, v in zip(view_codes, ex.map(lambda x: stock_industry(x, scache, today), view_codes)):
            ind_of[c] = v
    scache["date"] = today
    secs = {}
    ics = sorted({(v or {}).get("code") for v in ind_of.values() if (v or {}).get("code")})
    need_ic = []
    for ic in ics:
        cached = (scache.get("sectors") or {}).get(ic)
        if cached and cached.get("date") == today:
            secs[ic] = cached
        else:
            need_ic.append(ic)
    if need_ic:                      # 업종이 여럿이면 동시에 잰다(속도)
        with ThreadPoolExecutor(max_workers=6) as ex:
            for ic, s in zip(need_ic, ex.map(lambda x: sector_doc(x, today), need_ic)):
                if s:
                    secs[ic] = s
                    scache.setdefault("sectors", {})[ic] = s
    save_sector_cache(scache)
    print("지수 %s · 업종 %d개 (%s)" % (mkt["label"] + (" → 약세" if mkt["weak"] else " → 보통"),
                                    len(secs), " ".join("%s %s" % (v["name"], v["state"])
                                                        for v in list(secs.values())[:6])), flush=True)

    # ---- 4-2) 첫 단추 — 3번 판정 D(사지 않는 자리)는 (매수)로 올리지 않고 빼고, 테마 크기를 잰다
    #      (2026-11-21 지시: "D는 사지 않는 자리이므로 (매수) 상태에 올리지 않고 제외한다")
    #      이미 장부에 올라간 보유·매도 종목은 실제 자리이므로 건드리지 않는다 — 오늘 새로 뜬 자리만 걷어낸다.
    members = {}
    for c, lst in themes.items():
        for t in lst:
            members.setdefault(t["name"], set()).add(c)
    lu = lu_index(pool, latest, fresh, themes)
    kept, dropped_d = [], []
    for p in picks:
        c = p["code"]
        j = first_trade_judge(p["rows"], p["a"], mkt)
        if j.get("grade") == "D":
            if c in added:                     # 오늘 새로 등록된 자리만 되돌린다
                items.pop(c, None)
                added.remove(c)
            dropped_d.append("%s(%s)" % (p["name"], p["theme"]["name"][:10]))
            continue
        p["t_n"] = theme_size(lu, members.get(p["theme"]["name"]), c, p["a"].get("d0"))
        kept.append(p)
    picks = kept
    if dropped_d:
        print("3번 D(사지 않는 자리) 제외 %d종목 — %s" % (len(dropped_d), " ".join(dropped_d)), flush=True)

    # 종목마다 '지수 약세 날 매수 자격'을 미리 잰다
    ctx = {}
    for p in picks:
        ic = (ind_of.get(p["code"]) or {}).get("code")
        ctx[p["code"]] = _ctx(p["code"], p["a"].get("base"), p.get("side"), p["price"],
                              p.get("prev"), ind_of.get(p["code"]), secs.get(ic), mkt,
                              p.get("side_why") or "")

    # ---- 4-3) 재무·공시 위험 플래그 (2026-11-24 보완 1번 · 뇌 18-7)
    #   적자 · 차입금 급증 · 오버행 · 고유 악재 · 수주 공시 미확인 — 네이버 공개 자료로 종목당 3번,
    #   하루 한 번만 받아 캐시한다(brain/cache/stock_risk).
    #   지슨(11/24 -13.2%)처럼 적자·차입 부담이 있는 4단계가 '매수'·'적극매수'에 바로 오르지 않게
    #   매수 판정에서 '관망'(사유에 위험 명시)으로 낮춘다.
    reasons = {}
    for p in picks:
        th = p.get("theme") or {}
        reasons[p["code"]] = " ".join(str(th.get(k) or "") for k in ("name", "summary", "flow"))
    for c, it in items.items():
        reasons.setdefault(c, "%s %s" % (it.get("theme") or "", it.get("why") or ""))
    risks = {} if args.no_risk else RISK.load(sorted(set([p["code"] for p in picks]) | set(items)),
                                             today, reasons)
    if risks:
        n_d = ["%s(%s)" % ((items.get(c) or {}).get("name") or c, risks[c].get("txt") or "")
               for c in risks if c in items and risks[c].get("level") == "위험"]
        n_w = sum(1 for r in risks.values() if r.get("level") == "주의")
        print("재무·공시 위험 %d종목%s%s" % (len(n_d), (" — " + " · ".join(n_d[:6])) if n_d else "",
                                          (" · 주의 %d" % n_w) if n_w else ""), flush=True)

    tracked = []
    for c, it in list(items.items()):
        rows = None
        if c in pool:
            nm, rows0, th = pool[c]
            rows = merge_with_fresh(clean(rows0[-WIN:]), latest.get(c))
            rows = merge_with_fresh(rows, clean(fresh.get(c) or []))
        elif c in fresh:
            rows = clean(fresh[c])[-WIN:]
        if not rows:
            continue
        a = analyze(rows)
        # 기준선 = 그림 기준선(② 눌림 저점) — 분석값을 먼저 쓴다(장부에 첫 가격이 남아 있어도 그림을 따른다)
        base = (a or {}).get("base") or it.get("base") or 0
        if (a or {}).get("base"):
            it["base"] = int(round(a["base"]))
        pause_low = it.get("pause_low") or 0
        if a and it.get("type") == "C" and a.get("pause_lo"):
            pause_low = min(pause_low or 9e18, a["pause_lo"])
        # 봉 기준 거래일 계산
        it["days"] = days_between(rows, it.get("entry_date"), today)
        close = rows[-1][4]
        st_now = a or {"stage": it.get("stage0")}
        rk = risks.get(c) or {}
        if it.get("status") == "sold":
            it["gone_days"] = days_between(rows, (it.get("sold") or {}).get("date"), today)
            if it["gone_days"] >= SOLD_KEEP:
                items.pop(c, None)
                continue
            state, why = "매도" if (it["sold"] or {}).get("kind") == "target" else (
                "매도" if (it["sold"] or {}).get("kind") == "stage" else "손절·매도"), \
                (it["sold"] or {}).get("reason") or ""
            # 매도 뒤에도 최신 등락만 갱신
            it["last_close"] = int(round(close))
            it["last_gain"] = round(close / (it.get("entry_price") or close) - 1, 4)
        else:
            state, why, kind = trade_state(it, rows, st_now, base, pause_low)
            # 재무·공시 위험(18-7) — 위험이면 사는 자리에서 내린다. 사유에 무엇이 걸렸는지 그대로 적는다.
            if state in ("매수", "9단계 매수") and rk.get("level") == "위험":
                state, why = "관망", "재무·공시 위험 — %s" % (rk.get("txt") or "악재 확인")
            elif state in ("매수", "9단계 매수") and rk.get("level") == "주의" and rk.get("txt"):
                why = "%s · 주의: %s" % (why, rk["txt"])
            it["last_close"] = int(round(close))
            if state in ("매도", "손절·매도") and not it.get("sold"):
                it.update({"status": "sold", "sold": {
                    "date": today, "price": int(round(close)), "kind": kind, "reason": why,
                    "gain": round(close / (it.get("entry_price") or close) - 1, 4)}})
                it["gone_days"] = 0
            else:
                if it.get("days", 0) >= MAX_HOLD_DAYS and not it.get("sold"):
                    it.update({"status": "sold", "sold": {
                        "date": today, "price": int(round(close)), "kind": "timeout",
                        "reason": "%d거래일 경과 — 추적 종료" % it["days"],
                        "gain": round(close / (it.get("entry_price") or close) - 1, 4)}})
                    it["gone_days"] = 0
        cx = ctx.get(c)
        if cx is None and rows:
            ic = (ind_of.get(c) or {}).get("code")
            ll = None
            try:
                ll = side_of(full_rows(c, pool, latest, fresh), c) if c in pool else side_of(rows, c)
            except Exception:
                ll = None
            cx = _ctx(c, (a or {}).get("base") or it.get("base"), (ll or {}).get("side"), close,
                      rows[-2][4] if len(rows) > 1 else close, ind_of.get(c), secs.get(ic), mkt,
                      (ll or {}).get("why") or "")
            ctx[c] = cx
        # 지수 약세 날 — 지수와 같이 꺾여 밀린 종목은 (매수)로 올리지 않고 (관망)으로 낮춘다
        if state in ("매수", "9단계 매수") and mkt["weak"] and cx and not cx["elite"]:
            state, why = "관망", "지수 약세(%s) · %s — %s" % (mkt["label"], cx["sector_label"],
                                                          cx["note"])
            if rk.get("flags"):        # 재무·공시 위험은 지수 사유에 밀리지 않게 짧게 같이 적는다
                why += " · %s(%s)" % ("위험" if rk.get("level") == "위험" else "주의",
                                       "·".join(rk["flags"]))
        it["state"] = state
        it["why"] = why
        if rk:
            it["risk"] = {"level": rk.get("level"), "score": rk.get("score"),
                          "flags": rk.get("flags") or [], "txt": rk.get("txt") or ""}
        it["stage_now"] = (a or {}).get("stage") or it.get("stage0")
        it["label_now"] = (a or {}).get("label")
        tracked.append((it, a, rows, th if c in pool else None))

    # ---- 5) 화면 자료 — 테마별로 묶고, 새 자리 + 장부 종목을 함께 싣는다
    rows_of, theme_of, side_of_c, price_of = {}, {}, {}, {}
    for c in items:
        if c in pool:
            nm, rows0, th = pool[c]
            rows = merge_with_fresh(clean(rows0[-WIN:]), latest.get(c))
            rows = merge_with_fresh(rows, clean(fresh.get(c) or []))
            rows_of[c], theme_of[c] = rows, th[0]
    out_rows = {}
    for c, it in list(items.items()):
        rows = rows_of.get(c)
        if rows is None and c in fresh:
            rows = clean(fresh[c])[-WIN:]
        if not rows:
            continue
        out_rows[c] = rows
        price_of[c] = rows[-1][4]

    # 새 시세를 못 받은 종목(장부에만 있고 parts 에도 없는 경우)은 뺀다
    for c in list(items):
        if c not in out_rows:
            items.pop(c, None)

    chart_rows = {}
    stock_doc = []
    for p in picks:
        c = p["code"]
        it = items.get(c) or {}
        chart_rows[c] = p["rows"]
        d = make_stock(c, p["name"], p["a"], p["rows"], p["theme"], p["side"],
                       p["dist_w240"], p["dist_m120"], it, p["val3"], p["v1"])
        d["state"] = it.get("state") or d["state"]
        d["fresh"] = c in added
        d["t_n"] = p.get("t_n") or theme_size(lu, members.get((p["theme"] or {}).get("name")), c,
                                            (p["a"] or {}).get("d0"))
        _attach_ctx(d, ctx.get(c))
        _judge_alert(d, p["rows"], p["a"], mkt)
        stock_doc.append(d)
    for c, it in items.items():
        if c in {x["code"] for x in stock_doc}:
            continue
        rows = out_rows[c]
        a = analyze(rows) or {"t": it.get("type") or "A", "stage": it.get("stage0") or 4,
                              "base": it.get("base") or rows[-1][4], "d0": None, "sw": it.get("sw")}
        th = theme_of.get(c) or {"name": it.get("theme") or "", "summary": "", "flow": "", "pos": "",
                                 "last": ""}
        ll = side_of(full_rows(c, pool, latest, fresh), c) if c in pool else side_of(rows, c)
        chart_rows[c] = rows
        d = make_stock(c, it.get("name") or c, a, rows, th, ll.get("side"),
                       ll.get("dist_w240"), ll.get("dist_m120"), it,
                       round(S.val3(rows, len(rows) - 1) / 1e8, 1), None)
        d["state"] = it.get("state") or d["state"]
        d["fresh"] = False
        d["t_n"] = theme_size(lu, members.get((th or {}).get("name")), c, (a or {}).get("d0") or it.get("d0"))
        _attach_ctx(d, ctx.get(c))
        _judge_alert(d, rows, a, mkt)
        stock_doc.append(d)

    # ---- 정렬: 새 자리(매수) → 관망 → 보유 → 매도/손절, 그 안에서 유형 A·B·C, 점수
    #      D(3번 작음 = 사지 않는 자리)는 화면에서도 뺀다 — (매수)로 올리지 않는다(2026-11-21 지시).
    #      장부(items)에는 남겨 두므로 다음 날 3번 판정이 A/B/C로 바뀌면 다시 나타난다.
    # 4·5·9·10단계 = 테마 추적의 주 추적 대상 (2026-11-23 지시 #12076). 2·3·6~8단계는 흐름 참고로 뒤에 둔다.
    for d in stock_doc:
        d["track"] = (d.get("stage") in (4, 5, 9, 10))
    stock_doc = [d for d in stock_doc if not (((d.get("judge") or {}).get("grade") == "D"
                                              and d.get("state") in ("매수", "9단계 매수", "관망")))]
    order_state = {"매수": 0, "9단계 매수": 1, "관망": 2, "돌파·보유": 3, "분출·보유": 4,
                   "매도": 5, "손절·매도": 6}

    def _prio(d):
        """전수조사 검증 기준 우선순위(2026-11-24) — 같은 자리·같은 유형이면
        빠른 ④(25거래일 안) · 고가 위 ④(B형) · 깊이(1년 고점 -50%↓) · 무리 테마(동반 상한가) ·
        오늘/최근 형광↑가 붙은 종목을 위로 올린다(§4·§5·§8 근거).
        거래대금은 판단 기준이 아니라 마지막 동점 처리에만 쓴다."""
        s = 0
        if d.get("fast4"):
            s += 2
        if d.get("over4"):
            s += 2
        if (d.get("dd") is not None) and d["dd"] <= -0.5:
            s += 1
        if ((d.get("theme") or {}).get("kind") == "동반테마") or (d.get("t_n") or 1) >= 2:
            s += 1
        if d.get("pink_arrow_date"):
            s += 1
        # 2026-11-25 "대장.실체 우선이지!" — 같은 자리·유형이면 대장주를 먼저,
        #   실체(재무·공시 정상)를 위로, 실체 위험은 뒤로 민다(위험은 이미 관망으로 내려가 있다).
        if (d.get("leader") or {}).get("on"):
            s += 2
        _lv = (d.get("substance") or {}).get("level") or ""
        if _lv == "정상":
            s += 1
        elif _lv == "위험":
            s -= 1
        return -s

    stock_doc.sort(key=lambda d: (order_state.get(d["state"], 9), {"A": 0, "B": 1, "C": 2}.get(d["t"], 9),
                                  _prio(d), -(d.get("val3") or 0)))

    # ---- 4-3-1) 테마 흐름 — 테마달력에 살아남은 테마 상한가 종목을 1~10단계 안에 빠짐없이 배치
    #   (2026-11-25 지시: "앱이 시작이 뉴스 테마달력 레이더 실전 이렇게 연결 구조야돼.
    #    테마가 1-10단계를 벗어나면 안되겠지")
    #   예전에는 cand 타점(3·4·5·9)에 걸린 20여 종목만 싣고, 나머지 테마 상한가 종목은 화면에서 버렸다.
    #   이제 닻(상한가)이 있는 테마 종목 전부를 단계별로 실어
    #     1~8단계 → 실전 '테마 추적'에 테마별 묶음으로 (위의 매수 타점·장부 종목 아래 흐름으로)
    #     9단계(하락 멈춤·재출발 대기) → 🔒 레이더 '9·10단계 재부각 대기'로
    #   넘긴다. 매수 타점(cand)·장부 종목은 위에서 이미 stock_doc 에 있으므로 겹치지 않게 뺀다.
    #   2026-11-25 보완 — 매수 타점 후보(VAL_MIN 3억)에서 걸러진 얇은 테마 종목도 달력에는 서므로
    #   흐름에 싣되, **알짜 위주로 1차 거름**한다(2026-11-25 지시 #5):
    #     대장·부대장(👑) + 최근 상한가 종목은 무조건 남기고, 나머지는 테마당 5종목까지만(거래대금 순).
    #     오늘 새 뉴스로 상한가가 터진 건전 종목은 '최근 상한가'라 자동으로 들어온다 — 문은 열려 있다.
    FLOW_PER_THEME = 5
    FRESH_LU_BARS = 14        # 최근 14거래일(3주) 안 상한가 — 무조건 남긴다
    have = {str(d.get("code")) for d in stock_doc}
    flow, flow_wait = [], []
    for c in sorted(pool):
        if str(c) in have:
            continue
        nm, rows0, th = pool[c]
        rows3 = merge_with_fresh(rows0[-WIN:], latest.get(c))
        if fresh.get(c):
            rows3 = merge_with_fresh(rows3, clean(fresh.get(c) or []))
        a = pre[c] if (c in pre and not fresh.get(c)) else analyze(rows3)
        if not a:
            continue
        stg = int(a.get("stage") or 0)
        if stg <= 0 or stg > 10:
            continue
        close, prev = rows3[-1][4], (rows3[-2][4] if len(rows3) > 1 else rows3[-1][4])
        tname = (th[0].get("name") if th else "") or ""
        ld = LEADER_OF.get(tname) or {}
        item = {"code": c, "name": nm, "theme": tname, "theme_short": short_name(tname),
                "stage": stg, "stage_txt": stage_txt(stg, a.get("cand")),
                "t": a.get("t") or "A", "flow": 1,
                "now": int(round(close)),
                "chg": round((close / prev - 1) * 100, 2) if prev else 0.0,
                "d0": a.get("d0"), "dd": a.get("dd"),
                "w2": a.get("w2"),
                "lu_days": (len(rows3) - 1 - a["i0"]) if a.get("i0") is not None else None,
                "val3": round(S.val3(rows3, len(rows3) - 1) / 1e8, 1),
                "keep": bool((ld and str(ld.get("code")) == str(c))
                             or ((len(rows3) - 1 - a["i0"]) <= FRESH_LU_BARS
                                 if a.get("i0") is not None else False)),
                "leader": ({"on": str(ld.get("code")) == str(c), "name": ld.get("name") or ""} if ld else None)}
        (flow_wait if stg >= 9 else flow).append(item)
    # 테마당 알짜만 — 대장·최근 상한가(14거래일 안)는 무조건 남기고, 나머지는 거래대금 큰 순으로 채운다
    def _trim_flow(items):
        by = {}
        for x in items:
            by.setdefault(x.get("theme_short") or x.get("theme") or "", []).append(x)
        keep = []
        for _t, arr in by.items():
            always = [x for x in arr if x.get("keep")]
            rest = sorted([x for x in arr if not x.get("keep")], key=lambda x: -(x.get("val3") or 0))
            keep.extend(always + rest[:max(0, FLOW_PER_THEME - len(always))])
        return keep
    _n0 = len(flow) + len(flow_wait)
    flow, flow_wait = _trim_flow(flow), _trim_flow(flow_wait)
    flow.sort(key=lambda x: (x["stage"], x.get("theme_short") or "", x["name"]))
    flow_wait.sort(key=lambda x: (x.get("theme_short") or "", x["name"]))
    print("테마 흐름 알짜 거름 — 테마당 %d종목 · %d → %d종목"
          % (FLOW_PER_THEME, _n0, len(flow) + len(flow_wait)), flush=True)

    # ---- 4-4) 역할 분담 (2026-11-24 지시) — 유형 C(9단계 하락 멈춤·10단계 재출발 대기)는
    #   실전 '테마 추적'의 주 추적에서 떼어 🔒 레이더 '9·10단계 재부각 대기' 구역으로 넘긴다.
    #   레이더 = 상한가 전 바닥 + 9·10단계 재출발 대기 / 실전 = 1~8단계 A·B 타점.
    #   장부(매매 추적·매도 판정)에는 그대로 두고, 화면에 놓는 자리만 바꾼다.
    cwait_doc = [{"code": d["code"], "name": d["name"], "t": "C",
                  "stage": d.get("stage"), "stage_txt": d.get("stage_txt") or "",
                  "state": d.get("state") or "", "theme": ((d.get("theme") or {}).get("name") or ""),
                  "why": d.get("why") or "", "now": d.get("now"), "chg": d.get("chg"),
                  "risk": d.get("risk"),
                  "dd": d.get("dd"), "base": d.get("base"), "box_hi": d.get("box_hi"),
                  "box_lo": d.get("box_lo"), "d0": d.get("d0"), "lu_days": d.get("lu_days"),
                  "sd": d.get("sd") or {},
                  "leader": d.get("leader"), "substance": d.get("substance"),
                  "yhigh": d.get("yhigh"), "base_gap": d.get("base_gap"),
                  "prestudy": d.get("prestudy"), "elapsed": d.get("elapsed"),
                  "window": d.get("window")}
                 for d in stock_doc if d.get("t") == "C"]
    # 9단계 흐름 종목도 같은 대기실로 — 하락 멈춤·바닥 횡보가 레이더에서 빠지지 않게(2026-11-25)
    _cw_have = {str(x.get("code")) for x in cwait_doc}
    for x in flow_wait:
        if str(x["code"]) in _cw_have:
            continue
        cwait_doc.append({"code": x["code"], "name": x["name"], "t": x["t"], "stage": x["stage"],
                          "stage_txt": x["stage_txt"], "state": "대기", "theme": x["theme"],
                          "why": "", "now": x["now"], "chg": x["chg"], "risk": None,
                          "dd": x["dd"], "base": None, "box_hi": None, "box_lo": None,
                          "d0": x["d0"], "lu_days": x["lu_days"], "sd": {},
                          "leader": x["leader"], "substance": None, "flow": 1,
                          "val3": x.get("val3")})
    # 2026-11-25 — 125봉 밖 오래된 상한가까지 9·10단계로 정확히 잡으면서 대기 명단이 130여 종목으로 늘었다.
    #   레이더 맨 위에 줄줄이 세우면 오히려 안 보이므로, 9단계(하락 멈춤) → 최근 상한가 → 거래대금 순으로 40종목만.
    CWAIT_MAX = 40
    _cw0 = len(cwait_doc)
    cwait_doc.sort(key=lambda x: (0 if int(x.get("stage") or 0) == 9 else 1,
                                  x.get("lu_days") if x.get("lu_days") is not None else 9999,
                                  -(x.get("val3") or 0)))
    cwait_doc = cwait_doc[:CWAIT_MAX]
    if _cw0 > CWAIT_MAX:
        print("9·10단계 대기 명단 %d → %d종목(9단계·최근 상한가·거래대금 순)" % (_cw0, CWAIT_MAX), flush=True)
    if not args.dry:
        try:
            with open(CWAIT, "w", encoding="utf-8") as f:
                json.dump({"base_date": market_last, "generated_at": kst_now().isoformat(timespec="seconds"),
                           "note": "9·10단계 — 하락 멈춤·재출발 대기(레이더 대기실)",
                           "stocks": cwait_doc}, f, ensure_ascii=False, separators=(",", ":"))
        except Exception as e:  # noqa: BLE001
            print("⚠ 레이더 대기 명단을 쓰지 못했습니다:", e, flush=True)
    print("9·10단계 재부각 대기 %d종목(유형 C %d + 9단계 흐름 %d) → 🔒 레이더 대기실"
          % (len(cwait_doc), len([x for x in cwait_doc if not x.get("flow")]), len(flow_wait)), flush=True)
    print("테마 흐름 1~8단계 %d종목 → 실전 '테마 추적'에 테마별로 (cand 타점 %d종목은 위에서 이미)"
          % (len(flow), len(picks)), flush=True)

    groups = {}
    # ---- 4-3) 오늘 뉴스 부각 — 이 종목의 테마가 오늘 각 매체 메인이 부른 테마인지 (2026-11-22 지시)
    #      뉴스 → 테마 DB → 레이더 → 10단계까지 한 줄로 이어진다. 개인 룰·기준선은 붙이지 않는다.
    news_links, news_at, all_themes = {}, "", []
    try:
        news_doc = NL.load_news()
        news_at = news_doc.get("generated_at_kst") or ""
        all_themes = NL.load_themes_safe()
        news_links = NL.match(news_doc, all_themes)
    except Exception as e:  # noqa: BLE001
        print("⚠ 뉴스 연결을 건너뜁니다:", e, flush=True)
    news_by_code = NL.by_code(news_links, all_themes if news_links else None)
    for d in stock_doc:
        tn = ((d.get("theme") or {}).get("name") or "").strip()
        info = news_links.get(tn) or news_by_code.get(str(d.get("code")))
        d["news"] = None if not info else {
            "badge": "뉴스 부각", "issue": info["issue"],
            "presses": info.get("presses_max") or info.get("presses") or 1,
            "articles": info.get("articles") or 1, "kw": info.get("kw") or [],
            "theme_db": info.get("theme") or tn,
        }
    if news_links:
        print("뉴스 부각 테마 %d — %s" % (len(news_links), " · ".join(list(news_links)[:4])), flush=True)

    # 테마 '최근 상한가'는 theme_db의 그 테마 상한가 이력에서 잡는다(2026-11-25) —
    #   종목 카드의 '1번 상한가'와 섮이지 않게, ⏱ 시간 차이별 표와 같은 날짜를 쓴다.
    try:
        _tm = TRACE.theme_meta(TRACE.load_theme_db(DB), market_last)
    except Exception:  # noqa: BLE001
        _tm = {}
    for d in stock_doc:
        key = (d.get("theme") or {}).get("name") or "테마 미상"
        _se, _skw = SEA.match(key)
        _last = ((_tm.get(key) or {}).get("last")
                 or (d.get("theme") or {}).get("last") or "")     # 테마 최근 상한가 — 큐브가 식은 지 얼마나 됐나
        _lm, _dd = None, None
        if _last:
            try:
                _dd = (datetime.strptime(market_last, "%Y-%m-%d")
                       - datetime.strptime(str(_last)[:10], "%Y-%m-%d")).days
                _lm = round(_dd / 30.44, 1)
            except Exception:
                _lm = None
        g = groups.setdefault(key, {"name": key, "short": short_name(key),
                                    "summary": (d.get("theme") or {}).get("summary") or "",
                                    "flow": (d.get("theme") or {}).get("flow") or "",
                                    "pos": (d.get("theme") or {}).get("pos") or "",
                                    "kind": (d.get("theme") or {}).get("kind") or "",
                                    "last_lu": _last,
                                    "news": news_links.get(key),
                                    "prestudy": SEA.card(_se, _skw),
                                    "elapsed": SEA.time_brief(_lm, days=_dd, d0=str(_last)) if _lm is not None else None,
                                    "window": window_for([key]),
                                    "stocks": []})
        g["stocks"].append(d)
    theme_doc = list(groups.values())

    charts = {}
    pink_of = {}
    for c, rows in chart_rows.items():
        lo = max(0, len(rows) - CH_MAX)
        # 분홍 ↑(후보 G)는 448선이 필요하다 — 470봉으로는 뒤 20여 봉만 잴 수 있어
        #   테마 종목은 10년 원본까지 붙인 봉(full_rows)으로 재고, 차트(170봉) 안의 날짜만 담는다.
        src = rows
        if c in pool:
            try:
                src = full_rows(c, pool, latest, fresh)
            except Exception:
                src = rows
        # 2026-11-23 지시 #12104·#12128 — 차트 ▲도 '상한가 뒤 15거래일 이상 식은 자리'만.
        #   형광↑ 알림 팝업과 같은 기준이어야 차트에 뜬 화살이 팝업에서 빠지지 않는다.
        pink_of[c] = PINK.dates_cooled(src, since=rows[lo][0])
        charts[c] = {
            "d": [int(r[0][2:4] + r[0][5:7] + r[0][8:10]) for r in rows[lo:]],
            "b": [[int(round(r[1])), int(round(r[2])), int(round(r[3])), int(round(r[4])), int(r[5])]
                  for r in rows[lo:]],
            # 차트 안 주기 전환용 주봉 52주·월봉 30개월 실봉 (2026-11-23 지시 #12008)
            #   주봉 240주선·월봉 120개월선도 그 봉과 같은 자리 수로 함께 싣는다(하늘색 장기선)
            #   2026-11-25 — 10년 봉을 다 들고 있지 않으므로 캐시의 옛 주·월 종가를 이어 붙인다
            "w": bar_pack(src, S.week_key, 52, ma_n=240, hist=WEEK_CLOSES.get(c)),
            "m": bar_pack(src, S.month_key, 30, ma_n=120, hist=MONTH_CLOSES.get(c)),
        }
        # 일봉 240선 — 170봉 창의 봉마다 대응하는 값(앞 240봉이 모자란 구간은 None)
        charts[c]["ma240"] = ma_series([r[4] for r in rows], 240)[-len(rows[lo:]):]
    # 분홍 ↑ — 차트 위 화살표(170봉 안 날짜) + 10단계 카드 배지(최근 5거래일) + 테마 상한가 종목 수
    for d in stock_doc:
        c = str(d.get("code"))
        d["pink"] = pink_of.get(c, [])
        src = out_rows.get(c) or chart_rows.get(c) or []
        pdate, back, _pk_ago = PINK.recent_cooled(src, days=5)
        d["pink_arrow_date"] = pdate
        d["pink_arrow_days"] = back
        d["theme_n"] = len(members.get(((d.get("theme") or {}).get("name") or "").strip(), ()))
        # 테마 구분 — '동반테마' / '개별상한가'(단독 재료). 확정 알림 ④ 동반 요건 판정에 쓴다
        d["theme_kind"] = (d.get("theme") or {}).get("kind") or ""

    cnt_state = {}
    for d in stock_doc:
        cnt_state[d["state"]] = cnt_state.get(d["state"], 0) + 1
    cnt_type = {k: sum(1 for d in stock_doc if d["t"] == k) for k in ("A", "B", "C")}
    mins = now.hour * 60 + now.minute
    same_day = (today == now.date().isoformat())
    if same_day and 9 * 60 <= mins < 15 * 60 + 30:
        session = "장중"
    elif same_day and mins < 9 * 60:
        session = "장전"
    else:
        session = "장마감"
    # ---- ⏱ 매달 상한가 테마 · 시간 차이별 10단계 추적 (2026-11-25 지시)
    #   "상한가로 된 테마 매달테마 종목 10단계 추적이야" — 최근 상한가 D+ 로 칸을 가르고,
    #   그 테마에 지금 10단계로 걸린 종목(대장·실체·단계)을 한 큐브에 세운다. 레이더도 같은 표를 읽는다.
    try:
        trace_doc = TRACE.doc(TRACE.load_theme_db(DB), stock_doc, market_last,
                              news_themes=list(news_links))
        print("⏱ 매달 상한가 테마 표 — " + " · ".join(
            "%s %d테마/%d종목" % (b["label"], b["themes_n"], b["stocks_n"]) for b in trace_doc["buckets"]),
            flush=True)
    except Exception as e:  # noqa: BLE001
        trace_doc = None
        print("⚠ 시간 차이별 10단계 표를 만들지 못했습니다:", e, flush=True)
    doc = {
        "v": 2,
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_at_kst": now.strftime("%Y.%m.%d %H:%M"),
        "base_date": market_last,
        "base_date_text": "%s.%s.%s %s 기준" % (market_last[:4], market_last[5:7],
                                                market_last[8:10], session),
        "session": session,
        "state_defs": STATE_DEF,
        "rules": {
            "vol4": VOL4_MAX, "sw": SW_MIN, "box": BOX_MAX_W, "lu_days": LU_DAYS_MAX,
            "c_dd": C_DD, "c_rng": C_RNG15, "c_vol": C_VOL, "val": VAL_MIN,
        },
        "counts": {"stocks": len(stock_doc), "themes": len(theme_doc), "types": cnt_type,
                   "states": cnt_state, "new": len(added), "cwait": len(cwait_doc),
                   "flow": len(flow),
                   "g45": sum(1 for d in stock_doc if d["t"] in ("A", "B") and d["stage"] in (4, 5)),
                   "track": sum(1 for d in stock_doc if d.get("track")),
                   "scanned": scanned, "anchored": len(short), "picks": len(picks),
                   "watch": cnt_state.get("관망", 0),
                   "elite": sum(1 for d in stock_doc if d.get("elite"))},
        "market": {"kospi": mkt.get("kospi"), "kosdaq": mkt.get("kosdaq"),
                   "weak": mkt["weak"], "label": mkt["label"], "why": mkt.get("why")},
        "sectors": secs,
        "filter": {"weak_day": WEAK_DAY, "elite_gap": ELITE_GAP,
                   "base_margin": round((ELITE_BASE_MARGIN - 1) * 100)},
        "themes": theme_doc,
        "flow": flow,
        "charts": charts,
        "season": SEA.doc(),
        "trace": trace_doc,
        "windows": WINDOWS[:14],
        "news": {"updated_kst": news_at, "themes": len(news_links),
                 "badge": "뉴스 부각",
                 "items": [{"theme": k, "issue": v["issue"], "presses": v.get("presses_max") or v.get("presses"),
                            "articles": v.get("articles")} for k, v in news_links.items()]},
    }
    # 오늘 분홍↑ 종목 명단(평문) — 10단계 카드의 형광 날짜만 모아 brain/cache 에 적는다(2026-11-23).
    pink_items = [x for th in (doc.get("themes") or []) for x in (th.get("stocks") or [])]
    pink_n = PINKX.write(PINK_TODAY, market_last, PINKX.rows_of(pink_items, market_last,
                                                               "pink_arrow_date"))
    if pink_n > 0:
        print("오늘 분홍↑ 종목 명단 %d개 → %s" % (pink_n, PINK_TODAY), flush=True)
    raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    if not args.dry:
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(seal(doc, HOTBAR_PW), f, ensure_ascii=False, separators=(",", ":"))
        watch["updated"] = now.isoformat(timespec="seconds")
        watch["base_date"] = market_last
        save_watch(watch)
        # 형광↑ 3칸 종합 팝업이 쓸 10단계 요약(평문 · 저장소 밖) — stage10 번호를 여기서 그대로 받아 간다.
        try:
            plain = [{"code": d["code"], "name": d["name"], "stage": d.get("stage"),
                      "stage_txt": d.get("stage_txt") or "", "state": d.get("state") or "",
                      "t": d.get("t"), "alert": d.get("alert") or "", "why": d.get("why") or "",
                      "risk": d.get("risk"),
                      "fast4": bool(d.get("fast4")), "over4": bool(d.get("over4")), "d4": d.get("d4"),
                      "dd": d.get("dd"), "val3": d.get("val3"), "t_n": d.get("t_n"),
                      "theme": (d.get("theme") or {}).get("name") or "",
                      "theme_kind": d.get("theme_kind") or "",
                      "pink_arrow_date": d.get("pink_arrow_date")}
                     for d in stock_doc]
            with open(MONTHLY_PLAIN, "w", encoding="utf-8") as f:
                json.dump({"base_date": market_last, "generated_at": now.isoformat(timespec="seconds"),
                           "market_weak": bool(mkt.get("weak")), "stocks": plain},
                          f, ensure_ascii=False, separators=(",", ":"))
        except Exception as e:  # noqa: BLE001
            print("⚠ 10단계 요약(평문)을 쓰지 못했습니다:", e, flush=True)

    # ---- 요약
    print("기준일 %s(%s) · 후보 %d → 오늘 자리 %d · 화면 %d종목 · 새로 %d"
          % (market_last, session, len(short), len(picks), len(stock_doc), len(added)), flush=True)
    print("상태 — " + " · ".join("%s %d" % (k, v) for k, v in cnt_state.items()), flush=True)
    _stg = {}
    for d in stock_doc:
        _stg[d.get("stage")] = _stg.get(d.get("stage"), 0) + 1
    print("단계 — " + " · ".join("%s단계 %d" % (k, v) for k, v in sorted(_stg.items(),
          key=lambda x: (x[0] is None, x[0]))) + " · 4→5 %d" % doc["counts"]["g45"], flush=True)
    if not args.quiet:
        for g in theme_doc:
            print("\n== %s [%s] 최근상한가 %s" % (g["short"], g["flow"], g["last_lu"]), flush=True)
            for d in g["stocks"]:
                print("   %s %-12s [%s] %s %s %s %8s원 %+6.1f%% | %s"
                      % (d["code"], d["name"][:12], d["t"], d["state"], d["stage_txt"],
                         d.get("side") or "-", fmt(d["now"]), d["chg"], d["why"]), flush=True)
    print("\n자료 %.0fKB · %s" % (len(raw) / 1024, OUT), flush=True)
    print("걸린 시간 %.1f초" % (time.time() - t_start), flush=True)
    return 0


def ma_series(closes, n):
    """봉마다의 단순이동평균 배열 — 차트가 봉과 한 칸씩 맞춰 긋는 하늘색 장기선(2026-11-23 지시).

    앞 n-1봉은 그 선이 아직 없으므로 None. 길이는 봉 개수와 같다 — 봉 i 의 선 값 = series[i].
    """
    out, run = [], 0.0
    for i, v in enumerate(closes):
        run += float(v or 0)
        if i >= n:
            run -= float(closes[i - n] or 0)
        out.append(int(round(run / n)) if i >= n - 1 else None)
    return out


def bar_pack(rows, keyfn, n, ma_n=None, hist=None):
    """일봉 → 주봉·월봉 묶음(마지막 n개). 봉 날짜 = 그 주·달의 마지막 거래일(YYMMDD 정수).

    ma_n 을 주면 그 봉 수의 단순이동평균 배열도 함께 싣는다(주봉 240 · 월봉 120 — 하늘색 장기선).
    hist = 얇은 캐시에 담아 둔 [[키, 종가], ...] — 10년 일봉 없이도 240주선·120개월선을 긋는다.
    """
    try:
        allg = S.bar_groups(rows, keyfn)
    except Exception:
        return None
    g = allg[-n:]
    if not g:
        return None
    out = {"d": [int(rows[b[6]][0][2:4] + rows[b[6]][0][5:7] + rows[b[6]][0][8:10]) for b in g],
           "b": [[int(round(b[1])), int(round(b[2])), int(round(b[3])), int(round(b[4])), int(b[5])]
                 for b in g]}
    if ma_n:
        # 10년 봉 전체로 선을 재고 마지막 n개만 — 지금 가진 봉 + 캐시의 옛 봉 종가를 잇는다
        closes = [b[4] for b in allg]
        if hist:
            first = allg[0][0]
            closes = [c for k, c in hist if k < first] + closes
        out["ma"] = ma_series(closes, ma_n)[-len(g):]
    return out


def short_name(name):
    """테마 이름을 짧게 — ' — 부연' 과 '(괄호 설명)' 을 떼어 이름만."""
    return (name or '').split(' — ')[0].split(' (')[0].strip() or name or ''


def v1_ratio(rows, i0):
    pv = [r[5] for r in rows[max(0, i0 - 125):i0]]
    if not pv:
        return None
    return round(rows[i0][5] / (st.mean(pv) or 1), 1)


def make_stock(code, name, a, rows, theme, side, dw, dm, item, val3, v1):
    """화면 한 줄 — 지금 자리·유형·기준선/윗선·관점."""
    t = len(rows) - 1
    close, prev = rows[t][4], (rows[t - 1][4] if t else rows[t][4])
    stg = a.get("stage") or 0
    base = a.get("base") or 0
    box_hi = a.get("box_hi") or a.get("pause_hi")
    box_lo = a.get("box_lo") or a.get("pause_lo")
    sw = a.get("sw")
    state = "매수"
    why = ""
    if a.get("cand") == "A4":
        why = ("2~3회 횡보 %d회 뒤 마른 음봉(거래량 %s배) — 2번 줄 사수, 윗선 돌파가 신호"
               % (sw or 0, a.get("vol4")))
    elif a.get("cand") == "A5":
        why = "오늘 윗선 돌파 — 종가(시간외)만, 다음 날 추격 금지"
    elif a.get("cand") == "C":
        why = ("분출 뒤 빠진 자리에서 15봉 폭 좁게 멈춤·거래량 마름 — 윗선 돌파가 재출발")
        state = "9단계 매수"
    elif a.get("pair"):
        pr = a["pair"]
        why = ("② %s 눌림 → ③ %s 윗꼬리 핫바 — 줄 %s원 사수, 그 줄까지 다시 내려오면 4번"
               % (str(pr.get("b2") or "")[5:].replace("-", "."), str(pr.get("b3") or "")[5:].replace("-", "."),
                  fmt(base)))
    if item.get("state"):
        state = item["state"]
        if item["state"] == "관망" or (item.get("days") or 0) > 0 or item.get("status") == "sold":
            why = item.get("why") or why
    elif item.get("entry_date"):
        state = "매수"
    entry = item.get("entry_price") or close
    gain = close / entry - 1 if entry else 0
    sold = item.get("sold") or {}
    if item.get("status") == "sold" and sold:
        gain = sold.get("gain") if sold.get("gain") is not None else gain
    # ---- 참여자 차트 — 테마 큐브 · 👑 대장 · 실체 · 1년 고점 대비 · 기준선 위치 (2026-11-25 지시)
    #   "레이더는 뉴스! 그걸 만든 결과는 참여자 테마 — 테마로 갔던 것들이 차트로 각 포지션"
    #   "대장.실체 우선이지!" → 카드에 보이고, 정렬에서도 대장·실체 정상을 위로 올린다.
    tname = (theme or {}).get("name") or ""
    ld = LEADER_OF.get(tname) or {}
    leader = None
    if ld:
        leader = {"on": str(ld.get("code")) == str(code), "name": ld.get("name") or "",
                  "code": str(ld.get("code") or "")}
    rk = item.get("risk") or {}
    substance = {"level": rk.get("level") or "미확인", "txt": rk.get("txt") or ""} if rk else None
    hi1y = max((r[2] for r in rows[-250:]), default=0) or 0
    yhigh = round((close / hi1y - 1) * 100, 1) if hi1y else None      # 1년 고점 대비 %
    base_gap = round((close / base - 1) * 100, 1) if base else None    # 기준선 위/아래 %
    sea_e, sea_kw = SEA.match(tname)
    # 경과 시간 — 1번 상한가에서 오늘까지 몇 개월차인가가 다음 자리를 정한다(2026-11-25 지시)
    #   날짜 일정(창구)보다 이 축을 앞에 둔다. 10년: +30% 중간 3.0개월 · 재상한가 중간 7.3개월.
    elapsed = None
    _d0 = a.get("d0")
    if _d0:
        try:
            _cal = (datetime.strptime(str(rows[t][0]), "%Y-%m-%d")
                    - datetime.strptime(str(_d0), "%Y-%m-%d")).days
            elapsed = SEA.time_brief(_cal / 30.44, days=((t - a["i0"]) if a.get("i0") is not None else None),
                                     d0=str(_d0))
        except Exception:
            elapsed = None
    return {
        "code": code, "name": name, "t": a.get("t") or "A",
        "stage": stg, "stage_txt": stage_txt(stg, a.get("cand")),
        "state": state, "why": why,
        "side": side, "dist_w240": dw, "dist_m120": dm,
        "d0": a.get("d0"), "lu_days": (t - (a.get("i0") or t)) if a.get("i0") is not None else None,
        "sw": sw, "vol4": a.get("vol4"), "val3": val3, "v1": v1,
        "base": int(round(base)) if base else None,
        "lu_open": int(round(a.get("lu_open"))) if a.get("lu_open") else None,
        "d3": a.get("d3_date"),
        "box_hi": int(round(box_hi)) if box_hi else None,
        "box_lo": int(round(box_lo)) if box_lo else None,
        "now": int(round(close)), "chg": round((close / prev - 1) * 100, 2),
        "entry_date": item.get("entry_date"), "entry_price": item.get("entry_price"),
        "gain": round(gain * 100, 1),
        "days": item.get("days"), "gone_days": item.get("gone_days"),
        "sold": {k: sold.get(k) for k in ("date", "price", "kind", "reason", "gain")} if sold else None,
        "theme": {"name": (theme or {}).get("name") or "", "summary": (theme or {}).get("summary") or "",
                  "flow": (theme or {}).get("flow") or "", "pos": (theme or {}).get("pos") or "",
                  "kind": (theme or {}).get("kind") or "",
                  "last": (theme or {}).get("last") or ""},
        "dd": a.get("dd"), "rng15": a.get("rng15"), "volx9": a.get("volx9"),
        # 2파 거래량 크기 — '보유(가벼움)' / '털기(대량분출)' (2026-11-25 지시)
        "w2": a.get("w2"),
        # 재무·공시 위험 플래그(18-7 · 2026-11-24 보완 1번) — 화면에는 why 문장으로 이미 보인다
        "risk": item.get("risk"),
        # ④ 자리 — 빠른 ④(25거래일 안) · 고가 위 ④(B형). 카드 앞 배지로 올린다(2026-11-24 지시)
        "d4": ({"d": a.get("d4_date"), "days": a.get("d4_days"), "type": a.get("d4_type")}
               if a.get("d4_date") else None),
        "fast4": bool(a.get("d4_days") is not None and a.get("d4_days") <= 25),
        "over4": a.get("d4_type") == "B",
        "sd": {k: v for k, v in {"1": a.get("d0"), "3": a.get("d3_date")}.items() if v},
        # ---- 참여자 차트(대장·실체 우선) · 12·1월 사전조사 · 다가오는 창구 (2026-11-25 지시)
        "leader": leader, "substance": substance,
        "cube": {"name": tname, "short": (theme or {}).get("name") or "",
                 "kind": (theme or {}).get("kind") or ""},
        "yhigh": yhigh, "base_gap": base_gap,
        "prestudy": SEA.card(sea_e, sea_kw),
        "elapsed": elapsed,
        "window": window_for([tname, name]),
    }


def _attach_ctx(d, cx):
    """화면 한 줄에 업종 흐름·정예 자격을 붙인다."""
    if not cx:
        return
    sec = cx.get("sector") or {}
    d["sector"] = {"name": sec.get("name") or "", "state": sec.get("state") or "",
                   "chg": sec.get("chg"), "ma5": sec.get("ma5"), "ma20": sec.get("ma20"),
                   "slope20": sec.get("slope20"), "rng15": sec.get("rng15"),
                   "n": sec.get("n"), "why": sec.get("why") or ""}
    d["elite"] = bool(cx.get("elite"))
    d["idx_chg"] = cx.get("idx_chg")
    d["filter_note"] = cx.get("note") or ""


def stage_txt(stg, cand):
    return {1: "1단계", 2: "2단계", 3: "3단계", 4: "4단계", 5: "5단계", 6: "6단계",
            7: "7단계", 8: "8단계", 9: "9단계", 10: "10단계"}.get(stg, "-")


def _judge_alert(d, rows, a, mkt):
    """3번 첫 거래 판정 + 3번/4번 알림 분리 — 2026-11-21 푸른하늘님 지시.

    · 3번 알림에는 3번 크기(큼/보통/약함)를 함께 보인다.
    · 4번은 새 매수가 아니라 '추가 매수'로만 따로 부른다(3번에서 반, 4번에서 반).
    """
    d["judge"] = first_trade_judge(rows, a, mkt)
    alert = None
    t = len(rows) - 1
    x3 = (a or {}).get("x3")
    cand = (a or {}).get("cand")
    if d.get("state") in ("매수", "9단계 매수"):
        if cand == "A4":                       # 3번 뒤 2번 줄까지 내려온 마른 음봉 = 4번 추가 매수
            alert = "4번 추가매수"
        elif x3 is not None and 0 <= t - x3 <= 1 and (d.get("stage") or 0) == 3:
            alert = "3번 매수"                 # 오늘·어제 나온 3번(첫 거래 양봉)
    d["alert"] = alert
    return d


if __name__ == "__main__":
    sys.exit(main())
