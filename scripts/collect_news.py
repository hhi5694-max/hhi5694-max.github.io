#!/usr/bin/env python3
"""국내 증시 뉴스 수집기 — 네이버 뉴스 경제 섹션(증권/산업/금융/글로벌경제/경제일반)과
네이버 뉴스 메인(언론사별 많이 본 뉴스 1~5위)에서 기사를 모아, 같은 이슈를 여러 매체가
다룬 정도로 묶어 '오늘의 이슈 순위'를 만든다.

함께 만드는 것:
  · flash       — 네이버 금융 실시간 속보·증시 뉴스(최근 1시간, 최대 6건). 5분마다 갱신되는 속보 흐름으로,
    화면 뉴스 탭의 30%를 차지한다. 각 속보에는 증시 영향 여부 판별과 대장주 배지가 붙는다.
  · issues      — 같은 사건을 다룬 기사를 하나로 묶은 이슈 카드(대표 기사 + 관련 매체 링크).
    매체 수가 많을수록 상위 순위, [속보]·긴급 기사는 최근 3시간 안일 때만 최상단
    (아침 속보가 저녁까지 위에 붙박이로 남지 않게 시각을 함께 본다). 연예·가십·개인사 기사는 제외.
  · leaders     — 기사에 직접 언급된 상장사 + 공개 테마별 상한가 주도 대장주 배지
  · themes_rank — 테마별 이슈 수·최근 6시간 비중·대표 키워드·대장주와,
    공개 뉴스 패턴만으로 계산한 '단기 불씨 / 중기 흐름' 힌트와 그 근거 수치
  · upper_limits — 오늘(장 시작 전이면 직전 거래일) 상한가 종목과, 종목별로 '왜 상한가였는지'를
    당일 보도에서 찾은 이슈 요약·대표 기사·테마 키워드

외부 API 키 없이 표준 라이브러리만 사용한다 (GitHub Actions 러너에서 바로 실행 가능).
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# 같은 폴더의 상한가 순위 모듈 — 불건전 기업 제외 · 테마 묶음 · 125봉 바닥 첫 상한가 · 뉴스↔달력 연결
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import upper_rank  # noqa: E402

KST = timezone(timedelta(hours=9))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

# 섹션: (섹션 id, 이름, 가중치)
SECTIONS = [
    (258, "증권", 1.00),
    (261, "산업/재계", 0.90),
    (259, "금융", 0.85),
    (262, "글로벌 경제", 0.70),
    (263, "경제 일반", 0.75),
]

# 2026-11-22 지시 — 각 매체가 아침에 메인으로 미는 시사·정책 이슈를 테마와 잇는다.
#   정치(100)·사회(102)는 증시 기사가 아니므로 가중치를 낮게 두고, is_issue_relevant 로
#   정책·규제·시험/교육·외교·재난·산업에 닿는 것만 남긴다(사건사고·연예·가십은 뺀다).
CIVIC_SECTIONS = [
    (100, "정치", 0.62),
    (102, "사회", 0.55),
]

MAX_ARTICLES = 50          # 대시보드에 남길 최대 기사 수
ARTICLE_LIMIT = 35         # 원문 조회까지 할 후보 기사 수
ARTICLE_FETCH_WORKERS = 3  # 본문/시각 조회 동시 요청 수

# 네이버 차단 방지용 요청 간격(초). 동시 요청 수를 줄이는 것만으로는 부족해
# 요청 자체를 최소 간격으로 벌린다. 두 값 모두 '최소' 간격이고, 고정 패턴을 피하려고
# 위로만 조금(최대 JITTER) 흔든다.
SECTION_DELAY = 0.8        # 섹션·목록 요청(fetch_section, popularDay, FLASHNEWS 등) 사이 간격
ARTICLE_DELAY = 0.35       # 기사 원문 요청(fetch_article_detail 역할의 enrich)마다 대기
JITTER = 0.12              # 간격에 더하는 최대 여유(초)

# 실시간 속보(네이버 금융) — 화면 뉴스 탭의 절반(50%)을 차지하는 영역
FLASH_MAX = 3              # 화면에 올릴 속보 수 (2026-11-22 지시: 6 → 3, 인기·중요도 상위만)
FLASH_PAGE_SIZE = 20       # 한 번에 받아오는 속보 수 (API가 20까지만 받는다 — 30 이상은 400)
FLASH_PAGES = 2            # 최대 페이지 수
FLASH_FRESH_MIN = 60       # 이 시간 안에 나온 뉴스만 '실시간'으로 상단에 올린다
FLASH_GRACE_MIN = 90       # 이 시간을 넘기면 상단 속보에서 내리고 이슈 목록으로 넘긴다
FLASH_MIN_FRESH = 2        # 새벽처럼 새 뉴스가 적을 때 최소한 이만큼은 최신순으로 채운다

# --------------------------------------------------------------------------- 테마 사전
# (id, 화면 라벨, 색상, [(키워드, 가중치), ...])
THEMES = [
    ("semiconductor", "반도체·AI", "#5b8cff", [
        ("반도체", 3), ("HBM", 3), ("D램", 3), ("DRAM", 3), ("낸드", 3), ("파운드리", 3),
        ("웨이퍼", 3), ("소부장", 3), ("반도체 장비", 3), ("인공지능", 3), ("AI", 1),
        ("엔비디아", 3), ("GPU", 3), ("데이터센터", 2), ("온디바이스", 3), ("CCL", 3),
        ("기판", 2), ("삼성전자", 2), ("SK하이닉스", 3), ("한미반도체", 3), ("DB하이텍", 3),
        ("리노공업", 3), ("이오테크닉스", 3), ("HPSP", 3), ("주성엔지니어링", 3),
        ("챗GPT", 2), ("LLM", 3), ("클라우드", 1), ("메모리", 2), ("시스템반도체", 3),
    ]),
    ("robot", "로봇·자율주행", "#38d6a8", [
        ("로봇", 3), ("휴머노이드", 3), ("협동로봇", 3), ("자율주행", 3), ("모빌리티", 2),
        ("드론", 3), ("UAM", 3), ("피지컬 AI", 3), ("피지컬AI", 3), ("레인보우로보틱스", 3),
        ("웨어러블", 2), ("스마트팩토리", 2), ("자동화", 2),
    ]),
    ("defense", "방산·우주", "#f0a35e", [
        ("방산", 3), ("국방", 2), ("K방산", 3), ("미사일", 3), ("무기", 2), ("잠수함", 3),
        ("전투기", 3), ("우주", 2), ("위성", 3), ("발사체", 3), ("항공우주", 3),
        ("한화에어로스페이스", 3), ("LIG넥스원", 3), ("한국항공우주", 3), ("누리호", 3),
        ("스페이스X", 3), ("스타링크", 3), ("함정", 2), ("K9", 3), ("천궁", 3),
    ]),
    ("bio", "바이오·헬스케어", "#e564b8", [
        ("바이오", 3), ("제약", 2), ("신약", 3), ("임상", 3), ("FDA", 3), ("품목허가", 3),
        ("백신", 3), ("의료", 2), ("헬스케어", 2), ("비만치료", 3), ("CDMO", 3),
        ("위탁생산", 3), ("항암", 3), ("줄기세포", 3), ("유전자", 2), ("알테오젠", 3),
        ("셀트리온", 3), ("삼성바이오로직스", 3), ("기술수출", 2), ("신약 허가", 3),
    ]),
    ("battery", "2차전지·에너지", "#8bd450", [
        ("2차전지", 3), ("이차전지", 3), ("배터리", 3), ("리튬", 3), ("양극재", 3),
        ("음극재", 3), ("분리막", 3), ("전해질", 3), ("전기차", 3), ("충전", 1),
        ("태양광", 3), ("수소", 3), ("연료전지", 3), ("원전", 3), ("원자력", 3),
        ("전력", 2), ("송전", 3), ("변압기", 3), ("ESS", 3), ("에너지", 1), ("LNG", 3),
        ("유가", 2), ("정유", 3), ("SMR", 3), ("전력기기", 3), ("HD현대일렉트릭", 3),
        ("LS일렉트릭", 3), ("산일전기", 3),
    ]),
    ("policy", "정책·건설", "#c9a2ff", [
        ("정부", 1), ("정책", 2), ("국회", 2), ("법안", 3), ("규제", 2), ("건설", 3),
        ("재건축", 3), ("재개발", 3), ("부동산", 2), ("세제", 3), ("감세", 3),
        ("예산", 2), ("공공", 1), ("SOC", 3), ("인프라", 2), ("국토부", 2), ("금융위", 2),
        ("공정위", 2), ("대통령", 1), ("장관", 1), ("특별법", 3), ("지원책", 2), ("육성", 2),
    ]),
    ("geopolitics", "남북·지정학", "#ff8b8b", [
        ("남북", 3), ("북한", 3), ("개성", 3), ("경협", 3), ("금강산", 3), ("대북", 3),
        ("지정학", 3), ("관세", 3), ("무역", 2), ("트럼프", 2), ("미중", 3), ("중국", 1),
        ("일본", 1), ("수출규제", 3), ("제재", 2), ("러시아", 2), ("우크라이나", 2),
        ("중동", 3), ("이스라엘", 3), ("호르무즈", 3),
    ]),
    ("macro", "거시·환율·금리", "#7fd3e8", [
        ("환율", 3), ("원달러", 3), ("금리", 3), ("연준", 3), ("한은", 3),
        ("한국은행", 3), ("물가", 3), ("CPI", 3), ("국채", 3), ("달러", 2), ("코스피", 3),
        ("코스닥", 3), ("증시", 3), ("외국인", 2), ("공매도", 3), ("MSCI", 3), ("지수", 2),
        ("채권", 3), ("기준금리", 3), ("경기", 1), ("GDP", 3), ("무역수지", 3),
        ("나스닥", 2), ("다우", 2), ("FOMC", 3), ("국제유가", 3),
    ]),
    ("earnings", "실적·공시·수급", "#f5d06b", [
        ("실적", 3), ("영업이익", 3), ("매출", 2), ("상한가", 3), ("급등", 3), ("급락", 3),
        ("공시", 3), ("유상증자", 3), ("무상증자", 3), ("M&A", 3), ("인수", 2),
        ("합병", 3), ("IPO", 3), ("상장", 2), ("자사주", 3), ("배당", 3), ("목표주가", 3),
        ("수주", 3), ("공급계약", 3), ("특허", 2), ("지분", 2), ("최대주주", 3),
        ("특징주", 3), ("테마주", 3), ("투자경고", 3), ("거래정지", 3), ("감자", 3),
        ("어닝", 3), ("컨센서스", 3), ("주가", 2), ("주주", 2),
    ]),
    ("aisec", "AI·보안", "#6fd0ff", [
        ("보안", 3), ("해킹", 3), ("악성코드", 3), ("딥페이크", 3), ("랜섬웨어", 3),
        ("부정행위", 3), ("커닝", 3), ("탐지", 2), ("생체인식", 3), ("양자암호", 3),
        ("스마트안경", 3), ("피싱", 3), ("개인정보", 2), ("영상보안", 3), ("인증", 2),
        ("위조", 2), ("CCTV", 2), ("수능", 2), ("재난문자", 2), ("시험", 1),
        ("cheating", 3), ("CSAT", 2), ("exam", 1),
    ]),
    ("disaster", "재난·안전", "#ffb27a", [
        ("지진", 3), ("태풍", 3), ("호우", 3), ("폭설", 3), ("한파", 3), ("산불", 3),
        ("홍수", 3), ("가뭄", 3), ("대피", 3), ("기상청", 3), ("재난안전", 3), ("구조", 2),
    ]),
]
THEME_LABEL = {tid: label for tid, label, _c, _k in THEMES}
THEME_COLOR = {tid: color for tid, _l, color, _k in THEMES}
THEME_KWS = {tid: kws for tid, _l, _c, kws in THEMES}

# --------------------------------------------------------------------------- 흐름 힌트 사전
HOUR = timedelta(hours=1)

# 단기 집중·속보성 표현 (제목 기준)
BURST_WORDS = ("속보", "긴급", "급등", "급락", "폭등", "폭락", "쇼크", "붕괴", "상한가",
               "특징주", "패닉", "경고", "날벼락", "돌파", "폭발")
# 구조적 업황·정책 연속성 표현 (제목+요약 기준)
STRUCT_WORDS = ("업황", "정책", "규제", "장기", "구조", "사이클", "수출", "투자 확대", "지원",
                "육성", "공급망", "법안", "예산", "시행", "로드맵", "협약", "수주", "계약",
                "연속", "업계", "산업")
# 대표 키워드에서 빼는 너무 흔한 말
GENERIC_KEYWORDS = {"주가", "종목", "시장", "기업", "투자", "공시", "테마주", "특징주",
                    "급등", "급락", "상한가"}
# 같은 개념의 키워드가 둘 다 뽑히지 않도록 하나로 묶는다
KEYWORD_ALIAS = {"AI": "인공지능", "피지컬AI": "피지컬 AI", "2차전지": "이차전지"}

# 증시와 무관한 기사(부동산 시세·생활정보 등)를 거르기 위한 최소 관련도
MIN_RELEVANCE = 6

STOP_RE = re.compile(r"[\u200b\xa0]+")


# --------------------------------------------------------------------------- 유틸
# 요청 간격 장치 — 여러 스레드가 함께 쓰므로 잠금 하나로 줄을 세운다.
# kind="article"은 기사 원문(ARTICLE_DELAY), 그 밖의 목록·API 요청은 SECTION_DELAY.
_rate_lock = threading.Lock()
_rate_last = {"section": 0.0, "article": 0.0}
_rate_delay = {"article": ARTICLE_DELAY}


def _wait_turn(kind: str = "section") -> None:
    """이전 같은 종류 요청과 최소 간격이 벌어질 때까지 기다린다."""
    delay = _rate_delay.get(kind, SECTION_DELAY)
    with _rate_lock:
        now = time.monotonic()
        if _rate_last[kind]:
            wait = _rate_last[kind] + delay + random.uniform(0, JITTER) - now
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
        _rate_last[kind] = now


def fetch(url: str, encoding: str = "utf-8", timeout: int = 12, retries: int = 1,
          kind: str = "section") -> str:
    last = None
    for _ in range(retries + 1):
        try:
            _wait_turn(kind)
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode(encoding, "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"fetch failed: {url} ({last})")


def strip_tags(s: str) -> str:
    s = re.sub(r"<script.*?</script>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_lib.unescape(s)
    s = STOP_RE.sub(" ", s)
    return " ".join(s.split()).strip()


def sentences(text: str):
    parts = re.split(r"(?<=[.!?。])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def make_summary(text: str, limit: int = 165) -> str:
    """앞 1~2문장을 문장 경계에서 잘라 깔끔한 요약을 만든다."""
    text = " ".join(text.split())
    if not text:
        return ""
    out = ""
    for s in sentences(text):
        if out and len(out) + len(s) + 1 > limit:
            break
        out = (out + " " + s).strip()
        if len(out) >= limit * 0.55:
            break
        if len(out) >= limit:
            break
    if len(out) > limit:
        cut = out[:limit].rstrip()
        if " " in cut:
            cut = cut[: cut.rfind(" ")]
        out = cut.rstrip(" ,·-—") + "…"
    return out


CAPTION_HINT = ("하고 있다", "찍고 있다", "제공", "왼쪽부터", "사진=", "자료사진", "연합뉴스", "뉴시스")


def looks_like_caption(s: str) -> bool:
    if len(s) < 45 and any(h in s for h in CAPTION_HINT):
        return True
    return any(h in s for h in ("왼쪽부터", "사진=", "자료사진"))


# 다음 뉴스의 'n일 전' 표기를 시각으로 바꿀 때 쓰는 날짜 생성기
def _mk(y: int, m: int, d: int):
    try:
        return datetime(y, m, d, tzinfo=KST)
    except ValueError:
        return None


def parse_kr_time(s: str, now: datetime):
    """다음 뉴스의 '4시간 전' 같은 표기를 실제 시각으로 바꾼다."""
    s = (s or "").strip()
    if not s:
        return None
    m = re.match(r"(\d+)\s*분\s*전", s)
    if m:
        return now - timedelta(minutes=int(m.group(1)))
    m = re.match(r"(\d+)\s*시간\s*전", s)
    if m:
        return now - timedelta(hours=int(m.group(1)))
    m = re.match(r"(\d+)\s*일\s*전", s)
    if m:
        return now - timedelta(days=int(m.group(1)))
    if s.startswith("어제"):
        return now - timedelta(days=1)
    if s.startswith("오늘") or "방금" in s:
        return now
    m = re.search(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", s)
    if m:
        dt = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dt:
            return dt
    m = re.search(r"(\d{1,2})월\s*(\d{1,2})일", s)
    if m:
        dt = _mk(now.year, int(m.group(1)), int(m.group(2)))
        if dt and dt.date() > now.date():
            dt = _mk(now.year - 1, int(m.group(1)), int(m.group(2)))
        return dt
    return None


# --------------------------------------------------------------------------- 수집
ITEM_SPLIT = re.compile(r'<li class="sa_item')
URL_RE = re.compile(r'https://n\.news\.naver\.com/mnews/article/(\d+)/(\d+)')
TITLE_RE = re.compile(r'<strong class="sa_text_strong">(.*?)</strong>', re.S)
LEDE_RE = re.compile(r'<div class="sa_text_lede">(.*?)</div>', re.S)
PRESS_RE = re.compile(r'<div class="sa_text_press">(.*?)</div>', re.S)


def parse_section(section_id: int, name: str, weight: float):
    url = f"https://news.naver.com/breakingnews/section/101/{section_id}"
    try:
        page = fetch(url)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] section {name} failed: {e}", file=sys.stderr)
        return []
    out = []
    for chunk in ITEM_SPLIT.split(page)[1:]:
        m_url = URL_RE.search(chunk)
        m_title = TITLE_RE.search(chunk)
        if not (m_url and m_title):
            continue
        title = strip_tags(m_title.group(1))
        if not title or len(title) < 6:
            continue
        m_lede = LEDE_RE.search(chunk)
        m_press = PRESS_RE.search(chunk)
        aid = f"{m_url.group(1)}/{m_url.group(2)}"
        out.append({
            "id": aid,
            "title": title,
            "lede": strip_tags(m_lede.group(1)) if m_lede else "",
            "press": strip_tags(m_press.group(1)) if m_press else "",
            "url": f"https://n.news.naver.com/mnews/article/{aid}",
            "section": name,
            "weight": weight,
        })
    print(f"[info] section {name}: {len(out)} items", file=sys.stderr)
    return out


# --------------------------------------------------------------------------- 네이버 뉴스 메인 랭킹
MAIN_RANKING_URL = "https://news.naver.com/main/ranking/popularDay.naver"
MAIN_SECTION = "네이버 메인"

MAIN_BOX = '<div class="rankingnews_box">'
MAIN_NAME_RE = re.compile(r'<strong class="rankingnews_name">([^<]+)</strong>')
MAIN_PRESS_RE = re.compile(r'media\.naver\.com/press/(\d+)/ranking')
MAIN_LI_RE = re.compile(r'<li>(.*?)</li>', re.S)
MAIN_HREF_RE = re.compile(r'href="(https://n\.news\.naver\.com/article/(\d+)/(\d+))[^"]*"')
MAIN_TITLE_RE = re.compile(r'class="list_title[^"]*"[^>]*>(.*?)</a>', re.S)
MAIN_RANKNUM_RE = re.compile(r'<em class="list_ranking_num">(\d+)')
MAIN_TIME_RE = re.compile(r'<span class="list_time[^"]*">([^<]+)</span>')


def parse_main_ranking(now: datetime | None = None):
    """네이버 뉴스 메인 '언론사별 많이 본 뉴스' 1~5위(약 80개 매체)를 읽는다.

    페이지가 euc-kr(cp949)로 내려오므로 해당 인코딩으로 디코드한다.
    """
    now = now or datetime.now(KST)
    try:
        page = fetch(MAIN_RANKING_URL, encoding="cp949", timeout=20)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] main ranking failed: {e}", file=sys.stderr)
        return []

    out = []
    for box in page.split(MAIN_BOX)[1:]:
        m_name = MAIN_NAME_RE.search(box)
        if not m_name:
            continue
        press = strip_tags(m_name.group(1))
        m_pid = MAIN_PRESS_RE.search(box)
        pid = m_pid.group(1) if m_pid else ""
        try:
            ul = box.split('<ul class="rankingnews_list">')[1].split("</ul>")[0]
        except IndexError:
            continue
        for li in MAIN_LI_RE.findall(ul):
            m_href = MAIN_HREF_RE.search(li)
            m_title = MAIN_TITLE_RE.search(li)
            if not (m_href and m_title):
                continue
            title = " ".join(strip_tags(m_title.group(1)).split())
            if not title or len(title) < 6:
                continue
            m_rank = MAIN_RANKNUM_RE.search(li)
            m_time = MAIN_TIME_RE.search(li)
            item = {
                "id": f"{m_href.group(2)}/{m_href.group(3)}",
                "title": title,
                "lede": "",
                "press": press,
                "press_id": pid,
                "url": m_href.group(1),
                "section": MAIN_SECTION,
                "weight": 0.95,
                "source": "main",
                "main_rank": int(m_rank.group(1)) if m_rank else 99,
            }
            if m_time:
                dt = parse_kr_time(html_lib.unescape(m_time.group(1)), now)
                if dt:
                    item["time"] = dt.isoformat()
            out.append(item)
    print(f"[info] main ranking: {len(out)} items / "
          f"{len({x['press'] for x in out})} presses", file=sys.stderr)
    return out


# --------------------------------------------------------------------------- YTN
# 2026-11-22 지시 — YTN이 매일 아침 메인으로 미는 이슈를 가져와 우리 테마 DB와 잇는다.
#   메인(탑뉴스·주요) + 정치·경제·사회·산업·최신 목록을 읽고, 사건사고·연예는 is_issue_relevant 로 뺀다.
YTN_MAIN_URL = "https://www.ytn.co.kr/"
YTN_LIST_URL = "https://www.ytn.co.kr/news/list.php?mcd={mcd}"
YTN_SECTIONS = [
    ("0101", "정치", 0.62),
    ("0102", "경제", 0.82),
    ("0103", "사회", 0.55),
    ("S0038", "산업", 0.84),
    ("0134", "최신", 0.60),
]
YTN_LINK_RE = re.compile(r'href="https://www\.ytn\.co\.kr/_ln/([0-9A-Z]{4})_(\d{14})(\d{4})?"')
YTN_TITLE_OPEN_RE = re.compile(r'<div class="title">(.*?)</div>', re.S)
YTN_TEXT_OPEN_RE = re.compile(r'<div class="(?:text|content)"[^>]*>(.*?)</div>', re.S)


def _ytn_time(code: str, now: datetime):
    try:
        return datetime.strptime(code, "%Y%m%d%H%M%S").replace(tzinfo=KST)
    except ValueError:
        return now - timedelta(hours=6)


_YTN_CAT = {m: (name, w) for m, name, w in YTN_SECTIONS}
YTN_CAT_NAME = {"0101": "정치", "0102": "경제", "0103": "사회", "0104": "국제",
                "0106": "문화", "0107": "스포츠", "0115": "전국", "0134": "최신",
                "S0038": "산업"}


def parse_ytn_page(page: str, now: datetime, cat_hint: str, weight_hint: float, rank_from: int = 0):
    """YTN 한 페이지에서 기사 링크·제목·리드·시각을 읽는다(메인·목록 공통)."""
    out, seen = [], set()
    for m in YTN_LINK_RE.finditer(page):
        cat, stamp = m.group(1), m.group(2)
        code = f"{cat}_{stamp}"
        if code in seen:
            continue
        seen.add(code)
        tail = page[max(0, m.start() - 220):m.end() + 1200]
        mt = YTN_TITLE_OPEN_RE.search(tail)
        if mt:
            title = " ".join(strip_tags(mt.group(1)).split())
        else:
            # 목록형(<div class="title"><a href="…">제목</a>) — 링크 바로 뒤가 제목이다
            after = page[m.end():m.end() + 300]
            title = " ".join(strip_tags(after.split("</a>")[0]).split())
        if len(title) < 6:
            continue
        mtext = YTN_TEXT_OPEN_RE.search(tail)
        lede = strip_tags(mtext.group(1)) if mtext else ""
        name = YTN_CAT_NAME.get(cat) or (cat_hint if cat_hint != "메인" else "기타")
        out.append({
            "id": f"ytn/{code}",
            "title": title,
            "lede": lede[:220],
            "press": "YTN",
            "url": f"https://www.ytn.co.kr/_ln/{code}",
            "section": f"YTN {name}" if cat_hint == "메인" else f"YTN {cat_hint}",
            "weight": weight_hint if cat_hint != "메인" else _YTN_CAT.get(cat, ("", 0.62))[1],
            "source": "press",
            "press_rank": rank_from + len(out) + 1,
            "time": _ytn_time(stamp, now).isoformat(),
        })
    return out


def collect_ytn(now: datetime):
    """YTN 메인 탑뉴스 + 주요 섹션 목록."""
    out = []
    try:
        page = fetch(YTN_MAIN_URL, timeout=20)
        got = parse_ytn_page(page, now, "메인", 0.70)
        out.extend(got)
        print(f"[info] ytn main: {len(got)} items", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] ytn main failed: {e}", file=sys.stderr)
    for mcd, name, w in YTN_SECTIONS:
        try:
            page = fetch(YTN_LIST_URL.format(mcd=mcd), timeout=20)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] ytn {name} failed: {e}", file=sys.stderr)
            continue
        got = parse_ytn_page(page, now, name, w, rank_from=len(out))
        out.extend(got)
        print(f"[info] ytn {name}: {len(got)} items", file=sys.stderr)
    # 같은 기사가 메인과 목록에 겹친다 — id 기준 첫 것(메인 우선)만 남긴다
    merged, seen = [], set()
    for a in out:
        if a["id"] in seen:
            continue
        seen.add(a["id"])
        merged.append(a)
    return merged


TIME_RE = re.compile(r'_ARTICLE_DATE_TIME[^>]*data-date-time="([^"]+)"')
# 기사 페이지가 스스로 밝히는 분류 (연예=106, 스포츠=107 등) — 가십 기사 판별에 쓴다
SITE_META_RE = re.compile(r'name="napp-site-analysis"[^>]*content="([^"]*)"', re.I)
SITE_SEC_RE = re.compile(r'section=(\d+)')
SITE_SVC_RE = re.compile(r'service=([a-zA-Z]+)')


def extract_body(page: str) -> str:
    """본문 영역(#dic_area)만 잘라낸다. 정규식 백트래킹을 피하려고 문자열 탐색으로 처리."""
    i = page.find('id="dic_area"')
    if i < 0:
        return ""
    start = page.find(">", i)
    if start < 0:
        return ""
    end = len(page)
    for marker in ('</article>', 'article_footer', 'media_end_categorize', 'id="comment'):
        j = page.find(marker, start)
        if j > start:
            end = min(end, j)
    return strip_tags(page[start + 1:end])


def enrich(article: dict) -> dict:
    """기사 원문 페이지에서 정확한 발행 시각과 본문 첫 문장을 가져온다."""
    if article.get("source") == "google":
        return article
    try:
        page = fetch(article["url"], kind="article")
    except Exception:  # noqa: BLE001
        return article
    m_time = TIME_RE.search(page)
    if m_time:
        try:
            dt = datetime.strptime(m_time.group(1).strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
            article["time"] = dt.isoformat()
        except ValueError:
            pass
    m_site = SITE_META_RE.search(page)
    if m_site:
        m_sec = SITE_SEC_RE.search(m_site.group(1))
        if m_sec:
            article["naver_section"] = int(m_sec.group(1))
        m_svc = SITE_SVC_RE.search(m_site.group(1))
        if m_svc:
            article["naver_service"] = m_svc.group(1).lower()
    if not article.get("lede") or len(article["lede"]) < 25:
        body = extract_body(page)
        if body:
            sents = [s for s in sentences(body) if not looks_like_caption(s)]
            article["body_lead"] = " ".join(sents[:2])
    return article


# --------------------------------------------------------------------------- 분류
def classify(article: dict):
    """키워드 적중 상위 3개만 합산해 테마 점수를 계산한다 (키워드가 많은 테마가 독점하는 것을 방지)."""
    title = article["title"]
    lede = article.get("lede", "") or ""
    text = title + " " + lede + " " + article.get("body_lead", "")
    best_tid, best_score, best_tags = "etc", 0, []
    for tid, _label, _color, kws in THEMES:
        hits = []
        for kw, w in kws:
            if kw not in text:
                continue
            pos = 3 if kw in title else (2 if kw in lede else 1)
            hits.append((w * pos, kw))
        if not hits:
            continue
        hits.sort(reverse=True)
        score = sum(h[0] for h in hits[:3])
        tags = [h[1] for h in hits[:4]]
        if score > best_score:
            best_tid, best_score, best_tags = tid, score, tags
    if best_tid == "etc":
        return "etc", [], 0
    relevance = best_score + int(article.get("weight", 0.7) * 2)
    return best_tid, best_tags[:4], relevance


# 테마 키워드가 약해도 이 말들이 있으면 증시 기사로 본다
MARKET_TERMS = ("주가", "증시", "코스피", "코스닥", "종목", "상한가", "급등", "급락", "투자자",
                "외국인", "기관", "공시", "실적", "영업이익", "수주", "공급계약", "목표주가",
                "특징주", "테마주", "상장", "IPO", "인수", "지분", "배당", "공모주", "주주")

# 증시 기사 판별용 강한 신호 (제목에 있으면 무조건 채택)
STRONG_MARKET = MARKET_TERMS + (
    "주식", "매수", "매도", "거래량", "시가총액", "공매도", "ETF", "선물", "옵션",
    "증권사", "리포트", "컨센서스", "어닝", "분기 실적", "3분기", "4분기", "영업익",
    "최대주주", "유상증자", "무상증자", "자사주", "액면분할", "감자", "관리종목",
    "투자의견", "목표가", "주가순자산", "PER", "PBR", "공모가", "수급", "반등", "약세",
    "강세", "폭락", "폭등", "상승 마감", "하락 마감",
)

# 상장사·핵심 기업 이름 (이 이름 + 사업 동작이 함께 나오면 증시 기사로 본다)
COMPANIES = (
    "삼성전자", "SK하이닉스", "삼전닉스", "현대차", "기아", "LG에너지솔루션", "삼성SDI",
    "삼성바이오로직스", "셀트리온", "한화에어로스페이스", "현대로템", "두산에너빌리티",
    "네이버", "카카오", "LG전자", "POSCO", "포스코", "롯데케미칼", "이마트", "CJ",
    "한화", "HD현대", "LS", "GS", "대한항공", "아모레", "하이브", "에코프로", "포스코퓨처엠",
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "메타", "아마존", "TSMC",
    "알테오젠", "유한양행", "한미약품", "HLB", "리가켐", "레인보우로보틱스", "로보티즈",
    "이오테크닉스", "한미반도체", "HPSP", "주성엔지니어링", "DB하이텍", "리노공업",
    "HD현대일렉트릭", "LS일렉트릭", "산일전기", "효성중공업", "한전기술", "두산에너빌",
    "LIG넥스원", "한국항공우주", "케이조선", "HD한국조선해양", "삼성중공업", "한화오션",
)

BUSINESS_ACTS = ("투자", "수주", "계약", "공급", "실적", "매출", "영업이익", "개발", "출시",
                 "증설", "인수", "합병", "상장", "임상", "특허", "감산", "증산", "가격 인상",
                 "MOU", "협약", "납품", "진출", "점유율", "생산", "공장")

# 기업 이름이 나와도 증시와 무관한 행사·사훈성 기사
NOT_MARKET = ("수상", "나눔", "봉사", "기부", "축제", "점등", "전시", "공연", "시상",
              "행사", "개막", "박람회", "체험", "공모전", "졸업", "입학")


def has_hangul(text: str) -> bool:
    """국내 대시보드이므로 한글이 없는 영문 단독 기사는 보여주지 않는다."""
    return any("\uac00" <= ch <= "\ud7a3" for ch in (text or ""))


# --------------------------------------------------------------------------- 연예·가십 차단
# 연예·방송·개인사 기사에만 나오는 말. 증시·산업 기사라면 아래 MARKET_ANCHOR가 함께 나오므로
# (한한령 해제·엔터주 실적·드라마 제작사 수주 등) 산업 기사는 그대로 남는다.
GOSSIP_MARK = (
    # 연예·방송·문화
    "배우", "가수", "아이돌", "걸그룹", "보이그룹", "연예인", "코미디언", "개그맨", "방송인",
    "예능", "드라마", "영화", "시청률", "컴백", "앨범", "신곡", "콘서트", "팬미팅", "화보",
    "열애", "이혼", "스캔들", "근황", "활동 중단", "자숙", "사과문", "소속사", "누리꾼",
    "인스타그램", "OST", "뮤지컬", "시상식", "팬들", "전속계약",
    # 개인사·수사
    "음주운전", "마약", "성폭행", "불법촬영", "스토킹", "상간",
)

# 증시·산업 기사임을 확실히 말해 주는 말 — 가십 표현이 있어도 이것이 있으면 남긴다
MARKET_ANCHOR = (
    "주가", "주식", "증시", "코스피", "코스닥", "상한가", "급등", "급락", "실적", "영업이익",
    "영업익", "매출", "수주", "공급계약", "목표주가", "투자의견", "시가총액", "거래량",
    "외국인", "기관", "공모주", "상장", "IPO", "인수", "합병", "지분", "배당", "공시",
    "자사주", "유상증자", "무상증자", "엔터주", "한한령", "수출", "컨센서스", "어닝",
    "특징주", "테마주", "주주", "공장", "증설", "임상", "신약", "FDA", "제약", "바이오",
    "백신", "점유율", "투자 확대", "가이던스",
)


def has_market_anchor(text: str) -> bool:
    return any(a in (text or "") for a in MARKET_ANCHOR)


def is_gossip(text: str) -> bool:
    """제목·도입부가 연예·가십·개인사인지. 증시·산업 단서가 함께 있으면 기사로 남긴다."""
    text = text or ""
    if not text or has_market_anchor(text):
        return False
    return any(g in text for g in GOSSIP_MARK)


def is_market_relevant(a: dict) -> bool:
    """증시와 무관한 생활·지역 뉴스를 걸러낸다."""
    title = a["title"]
    lede = a.get("lede", "") or ""
    if not has_hangul(title):
        return False
    if is_gossip(title + " " + lede):
        return False
    if any(t in title for t in STRONG_MARKET):
        return True
    if any(t in title for t in NOT_MARKET):
        return False
    has_company = any(c in title or c in lede for c in COMPANIES)
    if has_company and any(act in title or act in lede for act in BUSINESS_ACTS):
        return True
    if sum(1 for t in STRONG_MARKET if t in lede) >= 2:
        return True
    return False


# --------------------------------------------------------------------------- 메인 랭킹 필터
# 메인 랭킹에는 연예·건강·지역 행사·사건사고가 섞여 들어온다.
# 증시·산업·기업·거시·금리·환율·정책/규제·지정학·수주·공급망에 닿는 기사만 남긴다.
MAIN_STRONG = (
    # 증시·수급
    "주가", "주식", "증시", "코스피", "코스닥", "지수", "상한가", "급등", "급락", "폭락",
    "폭등", "매수", "매도", "거래량", "외국인", "공매도", "시가총액", "ETF", "공모주", "IPO",
    "상장", "공시", "유상증자", "무상증자", "자사주", "배당", "목표가", "투자의견", "실적",
    "영업이익", "영업익", "매출", "컨센서스", "어닝", "특징주", "테마주", "증권사", "리포트",
    # 거시
    "환율", "원달러", "금리", "연준", "한은", "한국은행", "FOMC", "금통위", "물가", "CPI",
    "국채", "채권", "GDP", "성장률", "무역수지", "경상수지", "고용", "실업", "최저임금",
    "인플레이션", "디플레이션", "기준금리", "경기침체",
    # 산업·기업
    "반도체", "메모리", "HBM", "D램", "파운드리", "엔비디아", "삼성전자", "SK하이닉스",
    "삼전닉스", "삼전", "하닉", "TSMC", "데이터센터", "AI", "인공지능", "디스플레이",
    "배터리", "이차전지", "2차전지", "전기차", "원전", "원자력", "LNG", "알래스카",
    "국제유가", "정유", "조선", "방산", "철강", "화학", "자동차", "바이오", "제약", "임상",
    "CDMO", "수출", "수입", "무역", "관세", "수주", "공급계약", "납품", "공장", "증설",
    "감산", "증산", "점유율", "투자", "수익", "손실", "자산",
    # 정책·제도·부동산
    "법안", "규제", "세제", "예산", "금융위", "공정위", "국토부", "특별법", "시행령",
    "금융", "증권", "은행", "보험", "연금", "부동산", "집값", "아파트", "재건축", "재개발",
    "분양", "전세", "경매", "리모델링",
    # 재난·정책 빅이슈
    "지진", "기상청", "태풍", "호우", "폭설", "한파", "산불", "홍수", "대피", "재난",
    "수능", "부정행위", "커닝", "재난문자", "세무사",
)

MAIN_WEAK = (
    "노조", "파업", "임단협", "정년", "일자리", "창업", "벤처", "스타트업", "소비", "유통",
    "물류", "해운", "항공", "농산물", "곡물", "원자재", "OPEC", "에너지", "전력", "충전",
    "수소", "태양광", "스마트폰", "갤럭시", "아이폰", "클라우드", "플랫폼", "게임",
    "통상", "산업부", "기재부", "공정거래", "보험료", "가상자산", "비트코인", "대출",
    "가계부채", "예금", "적금", "공모", "인수", "합병", "M&A", "지분", "최대주주",
    "구조조정", "감원", "보안", "해킹", "딥페이크",
)

MAIN_COMPANIES = (
    "삼성", "SK", "현대차", "기아", "LG", "롯데", "한화", "두산", "포스코", "POSCO", "GS",
    "네이버", "카카오", "쿠팡", "셀트리온", "한미약품", "유한양행", "알테오젠", "에코프로",
    "HD현대", "LS", "효성", "코오롱", "CJ", "이마트", "아모레", "하이브", "테슬라", "애플",
    "마이크로소프트", "구글", "메타", "아마존", "오픈AI", "앤트로픽", "인텔",
)

MAIN_DROP = (
    # 연예·가십·사생활
    "연예", "아이돌", "배우", "걸그룹", "보이그룹", "결혼", "이혼", "열애", "임신", "불륜",
    "스캔들", "근황", "인스타", "화보", "드라마", "영화", "예능", "뮤지컬", "콘서트",
    "팬미팅", "데뷔", "컴백", "열애설", "결별", "아나운서", "방송인", "코미디언", "가수",
    "OST", "스태프", "보너스", "여친", "모델", "패션", "스키복",
    # 건강·생활·음식
    "건강", "다이어트", "감량", "혈당", "콜레스테롤", "면역", "비타민", "음식", "레시피",
    "영양", "숙면", "수면", "보습", "피부", "탈모", "갱년기", "병원", "의사", "치매",
    "근육", "식품", "과일", "채소", "상추", "귤", "바나나", "달걀", "콩팥", "신장", "변비",
    "알레르기", "전자담배", "담배", "음주", "숙취", "비만", "체중", "식단", "간식", "커피",
    "라면", "뷔페", "보습크림",
    # 여행·레저·문화·날씨
    "여행", "산행", "등산", "캠핑", "맛집", "축제", "전시", "공연", "스키", "낚시", "골프",
    "호캉스", "관광", "해녀", "트레킹", "날씨", "기온", "우산", "미세먼지",
    # 사건사고·수사·재판
    "참변", "숨져", "사망", "살해", "피살", "성폭행", "성비위", "불법촬영", "마약", "검거",
    "체포", "구속", "입건", "실종", "납치", "음주운전", "교통사고", "추락", "익사", "실탄",
    "권총", "테러", "횡령", "구타", "폭행", "시신", "변사", "영안실", "스토킹", "협박",
    "징역", "선고", "무죄", "유죄", "기소", "구형",
    # 스포츠·연예·기타 생활
    "프로야구", "축구", "올림픽", "월드컵", "복권", "로또", "당첨", "반려견", "반려묘",
    "고양이", "유기견", "웨딩", "신혼", "육아", "출산", "유치원", "문해력", "표창",
    "봉사", "기부", "나눔", "박람회", "공모전", "졸업", "입학", "재승인", "강사", "일타",
    # 정치 단독 이슈(증시와 무관)
    "징계", "탈당", "제명", "공천", "국정조사", "특검", "후보 추천", "입국 거부", "당내",
)

# 개인 사건·수사성 표현 (정책·산업 신호가 없으면 버린다)
CASE_WORDS = (
    "리트", "만점자", "수석", "수험생", "헌재", "헌법소원", "효력정지", "경찰", "검찰",
    "조사", "입건", "고소", "소송", "의혹", "예고글", "밈", "스토킹", "폭로", "자백",
    "사과", "재판", "구속", "합격", "강사", "일타",
)
# 정책·제도·산업 신호 (사건성 기사라도 이것이 있으면 산업·정책 뉴스로 본다)
POLICY_INDUSTRY = (
    "정부", "교육부", "대책", "규제", "법안", "국회", "장관", "총리", "대통령", "시행",
    "탐지", "보안", "기술", "산업", "통신", "전수검사", "앱", "개발", "제도", "당국",
    "처벌", "감면", "포상", "차단", "점검",
)


# 강한 시장 키워드가 있어도 먼저 버리는 기사 종류 (연예·스포츠·개인 사건·학교)
HARD_DROP = (
    "연예", "아이돌", "배우", "가수", "걸그룹", "보이그룹", "예능", "드라마", "영화", "화보",
    "콘서트", "팬미팅", "열애", "불륜", "이혼", "결혼", "임신", "스캔들", "근황",
    "프로야구", "축구", "올림픽", "월드컵", "복권", "로또",
    "살해", "피살", "성폭행", "불법촬영", "마약", "교통사고", "참변", "숨져", "사망", "자살",
    "입건", "구속", "체포", "검거", "실탄", "권총",
    "일타", "강사", "교사", "학원", "학부모", "여고", "수험생", "감독관", "고3", "초등학생",
    "추락", "실종", "날씨", "기온", "추워", "눈 가능성", "재승인", "점수 조작", "가짜뉴스",
    "체납", "수당", "매매 상위 종목", "상위 종목",
)


MATCH_FIX = (
    ("견주가", "견주"), ("유가족", "유족"), ("은행나무", "나무"), ("TV조선", "TV방송"),
    ("조선일보", "일간지"), ("조선비즈", "경제지"), ("주간조선", "주간지"), ("조선뉴스", "뉴스"),
    ("정유라", "정씨"),   # 인물 정유라를 '정유(정제유)' 기사로 오인하지 않게
)


def matchable(title: str) -> str:
    """부분 문자열 오인(견주가→주가, 유가족→유가, 은행나무→은행, TV조선→조선)을 막는다."""
    for a, b in MATCH_FIX:
        title = title.replace(a, b)
    return title


def case_only(title: str) -> bool:
    return any(w in title for w in CASE_WORDS) and not any(w in title for w in POLICY_INDUSTRY)


def is_main_relevant(a: dict) -> bool:
    """메인 랭킹 기사가 증시·산업·거시·정책에 닿는지 판단한다.

    연예·건강·생활·스포츠·지역 행사·개인 사건은 제외하고,
    같은 사건이라도 정부 대책·규제·산업 영향이 있는 기사는 남긴다.
    """
    title = matchable(a["title"])
    if not has_hangul(title):
        return False
    if any(w in title for w in HARD_DROP):
        return False
    if is_gossip(title + " " + (a.get("lede", "") or "") + " " + (a.get("summary", "") or "")):
        return False
    if case_only(title) and not any(w in title for w in ("코스피", "증시", "주가", "환율", "금리")):
        return False
    if any(w in title for w in MAIN_STRONG):
        return True
    if any(w in title for w in MAIN_DROP):
        return False
    if any(c in title for c in MAIN_COMPANIES) and any(x in title for x in BUSINESS_ACTS):
        return True
    # 약한 단서 하나만으로는 연예·가심 기사가 새여 들어온다 — 두 개 이상일 때만 남긴다
    if sum(1 for w in MAIN_WEAK if w in title) >= 2:
        return True
    return False


# --------------------------------------------------------------------------- 시사·정책 필터
# 2026-11-22 지시 — 각 매체(YTN 포함) 메인에서 미는 시사·정책·산업 이슈를 이슈 목록에 넣는다.
#   단순 사건사고·연예·가십·지역행사는 그대로 뺀다(정책·규제·시험/교육·외교·재난·산업만).
POLICY_STRONG = (
    # 정책·제도 — 이것 하나만으로도 시사 이슈로 본다
    "정부", "대통령", "국회", "법안", "법개정", "개정안", "규제", "세제", "감세", "예산",
    "대책", "장관", "위원회", "공정위", "금융위", "국토부", "산업부", "교육부", "과기부",
    "복지부", "고용부", "시행령", "특별법", "조례", "국무회의", "당정", "청와대",
    # 시험·교육
    "수능", "시험", "부정행위", "커닝", "자격", "입시", "채점", "감독", "수험생",
    # 외교·안보·통상
    "외교", "정상회담", "회담", "협상", "타결", "서명", "관세", "통상", "FTA", "제재",
    "북한", "김정은", "대북", "이란", "이스라엘", "우크라이나", "러시아", "트럼프", "백악관",
    "국방", "방위", "한미", "미중",
    # 재난·보건
    "지진", "태풍", "호우", "폭설", "한파", "산불", "홍수", "재난", "대피", "기상청",
    "감염병", "백신", "질병", "방역",
)

POLICY_WEAK = (
    # 산업·시장·생활 — 둘 이상 겹칠 때만 이슈로 본다(한 단어로 개인사가 새는 것을 막는다)
    "지원", "육성", "투자", "수출", "공급망", "물류", "해운", "항공", "부동산", "집값",
    "전세", "재건축", "최저임금", "노동", "연금", "의료", "전기요금", "통신", "AI",
    "인공지능", "데이터센터", "양자", "반도체", "조선", "방산", "원전", "전력", "에너지",
    "배터리", "이차전지", "자동차", "철강", "화학", "바이오", "제약", "임상", "수주",
    "공장", "증설", "교육", "학생", "대학", "고용", "창업", "벤처", "세제", "물가",
)
POLICY_SIGNAL = POLICY_STRONG + POLICY_WEAK
# 개인사·인물 기사 표지 — 정책 신호가 없으면 시사 이슈로 넣지 않는다
CIVIC_DROP = ("이탈주민", "친생자", "병원비", "호소", "회고록", "근황", "투병", "별세", "부고",
              "유족", "빈소", "간병", "모금", "사연", "미담", "일화")
# 정당·선거 내부 싸움만 다루는 말 — 정책 신호가 함께 없으면 뺀다
PARTY_ONLY = ("징계", "탈당", "제명", "공천", "국정조사", "특검", "당내", "계파", "지지율",
              "당대표", "원내대표", "윤리심판원", "의총", "비대위")


def is_issue_relevant(a: dict) -> bool:
    """정치·사회·매체 메인 기사가 테마와 닿는 시사 이슈인지 판단한다.

    2026-11-22 지시 — 단순 사건사고·연예·가십·개인사는 빼고, 정책·규제·시험/교육·외교·
    재난·산업에 닿는 이슈만 넣는다. 정책 신호가 강하지 않으면 약한 신호 두 개 이상을 본다.
    """
    title = matchable(a["title"])
    lede = a.get("lede", "") or ""
    text = title + " " + lede
    if not has_hangul(title):
        return False
    if any(w in title for w in HARD_DROP):
        return False
    if is_gossip(text):
        return False
    if any(w in title for w in CIVIC_DROP):
        return False
    if sum(1 for w in PARTY_ONLY if w in title) >= 2 and not any(w in title for w in POLICY_STRONG[:40]):
        return False
    if any(w in title for w in POLICY_STRONG):
        return True
    weak = sum(1 for w in POLICY_WEAK if w in title)
    if weak >= 2:
        return True
    if weak >= 1 and sum(1 for w in POLICY_STRONG if w in lede) >= 1:
        return True
    # 우리 테마 DB(테마명·종목명)에 바로 닿는 기사면 남긴다 (예: 수능 AI 커닝 → AI 시험 부정행위)
    hits = theme_link(title + " " + lede)
    return bool(hits) and hits[0][0] >= 2.5


# --------------------------------------------------------------------------- 테마 DB 어휘
# 공개 달력(data/calendar.json)의 테마명·종목명으로 '오늘 뉴스가 어느 테마에 바로 닿는지'를 센다.
# (개인 룰·기준선·매수가는 쓰지 않는다 — 지인 공개 자료와 공개 기사만)
# 2026-11-22 달력을 잠그면서, 테마 이름만 담은 data/news_vocab.json 을 읽는다(load_theme_vocab).
THEME_VOCAB: list = []
_THEME_VOCAB_READY = False
TIDY_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]")
VOCAB_SPLIT_RE = re.compile(r"[·•,\/\u00b7]")
VOCAB_STOP = {"테마", "관련", "기대", "정책", "수혜", "부각", "대표주", "대표종목", "종목", "급등",
              "상한가", "최근", "신규", "국내", "글로벌", "시장", "공급", "수요", "실적", "수주",
              "협력", "확대", "개편", "재부각", "진입", "돌파", "기대감", "이슈", "모멘텀"}


def theme_tokens(name: str):
    """테마명 → (본문 알맹이, 괄호 안 고유어). 괄호는 사건의 고유명이 많아 가중치를 따로 준다."""
    main, paren = [], []
    for chunk in VOCAB_SPLIT_RE.split(TIDY_RE.sub(" ", name or "")):
        for w in re.findall(r"[가-힣A-Za-z][가-힣A-Za-z0-9\-]{1,}", chunk):
            w = w.strip("-")
            if len(w) < 2 or w in VOCAB_STOP or re.fullmatch(r"\d{4}", w):
                continue
            main.append(w)
    for p in re.findall(r"\(([^)]*)\)", name or ""):
        for w in re.findall(r"[가-힣A-Za-z][가-힣A-Za-z0-9\-]{1,}", p):
            w = w.strip("-")
            if len(w) < 2 or w in VOCAB_STOP or re.fullmatch(r"\d{4}", w) or w in main or w in paren:
                continue
            paren.append(w)
    return main, paren


def _vocab_from_rows(rows):
    """[(테마명, 본문토큰, 괄호토큰, 종목명)] → [(테마명, [(말, 가중치), ...])]."""
    df = {}
    for _n, toks, paren, _s in rows:
        for t in set(toks) | set(paren):
            df[t] = df.get(t, 0) + 1
    vocab = []
    for name, toks, paren, stocks in rows:
        kws = []
        for t in dict.fromkeys(toks):
            kws.append((t, 2.2 if df.get(t, 1) <= 2 else (1.2 if df.get(t, 1) <= 5 else 0.6)))
        for t in dict.fromkeys(paren):      # 괄호 안 고유어 — 테마에만 쓰이면 높게, 짧으면 낮게
            base = 2.0 if df.get(t, 1) <= 2 else 0.8
            kws.append((t, base if len(t) >= 4 else base * 0.55))
        # 종목명은 테마를 정확히 집어 준다 — 검색어로도 자주 쓰이므로 낱말이 길 때만 높은 가중치
        for s in dict.fromkeys(stocks):
            kws.append((s, 2.5 if len(s) >= 3 else 1.5))
        vocab.append((name, kws))
    return vocab


def load_theme_vocab():
    """테마 이름 어휘 → [(테마명, [(말, 가중치), ...])]. 없으면 빈 목록.

    2026-11-22: 테마달력(data/calendar.json)을 잠그면서, 테마 '이름'만 담은
    data/news_vocab.json 을 먼저 읽는다(종목·상한가 날짜·요약은 담지 않는다).
    그 파일이 없는 예전 저장소에서는 평문 달력에서 종목명까지 함께 읽는다.
    """
    global THEME_VOCAB, _THEME_VOCAB_READY
    if _THEME_VOCAB_READY:
        return THEME_VOCAB
    _THEME_VOCAB_READY = True
    here = os.path.dirname(os.path.abspath(__file__))
    rows = []
    try:
        v = json.load(open(os.path.join(here, "..", "data", "news_vocab.json"), encoding="utf-8"))
        for name in v.get("themes") or []:
            name = str(name or "").strip()
            if not name:
                continue
            toks, paren = theme_tokens(name)
            rows.append((name, toks, paren, []))
    except Exception:  # noqa: BLE001
        rows = []
    if not rows:
        try:
            cal = json.load(open(os.path.join(here, "..", "data", "calendar.json"), encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return THEME_VOCAB
        if cal.get("enc"):          # 잠근 파일 — 암호문이라 읽을 수 없다(위 어휘 파일이 있어야 한다)
            return THEME_VOCAB
        for mo in cal.get("months") or []:
            for th in mo.get("themes") or []:
                name = th.get("name") or ""
                if not name:
                    continue
                toks, paren = theme_tokens(name)
                stocks = [s.get("name") for s in (th.get("stocks") or []) if len(s.get("name") or "") >= 2]
                rows.append((name, toks, paren, stocks))
    THEME_VOCAB = _vocab_from_rows(rows)
    print(f"[info] theme vocab: {len(THEME_VOCAB)}테마 / {sum(len(k) for _n, k in THEME_VOCAB)}말", file=sys.stderr)
    return THEME_VOCAB


# 같은 뜻으로 뉴스에 더 자주 쓰이는 말 — 테마 DB 말로 이어 준다(2026-11-22)
VOCAB_ALIAS = {
    "수능": ("시험", "부정행위"),
    "커닝": ("부정행위",),
    "논술": ("시험",),
    "자격증": ("자격",),
    "반도체클러스터": ("반도체",),
    "한류": ("한한령",),
    "지선": ("지방선거",),
    "전기료": ("전기요금",),
}


def theme_link(text: str, limit: int = 4) -> list:
    """글 안에서 매칭되는 테마 DB 말을 점수로 모은다 → [(점수, 테마명, 맞은 말들)].

    흔한 말(여러 테마에 겹치는 '반도체' 등)은 가중치를 낮추고, 테마에만 쓰이는 말(종목명·
    '한한령'·'해상풍력' 등)은 높여서, 여러 테마가 한 기사에 무더기로 걸리지 않게 한다.
    """
    text = text or ""
    if not text.strip():
        return []
    probe = text
    for k, alts in VOCAB_ALIAS.items():
        if k in text:
            probe += " " + " ".join(alts)
    scored = []
    for name, kws in load_theme_vocab():
        hits, score = [], 0.0
        for kw, w in kws:
            if kw in probe:
                # 긴 낱말일수록 그 기사의 중심어다 — 짧은 낱말의 우연한 포함을 줄인다
                score += w * (1.0 if len(kw) >= 4 else 0.75)
                hits.append(kw)
        if score >= 1.8:
            scored.append((round(score, 2), name, hits[:3]))
    scored.sort(key=lambda x: -x[0])
    return scored[:limit]


# 거시·금리·환율 전망만 다루는 '무거운' 제목 — 테마와 닿지 않으면 아래로 내린다(11-22 지시)
HEAVY_MACRO = ("전망", "금리", "환율", "연준", "FOMC", "물가", "CPI", "국채", "나스닥", "다우",
               "뉴욕증시", "S&P", "달러", "인플레이션", "경기침체", "성장률", "통화정책")


def is_heavy_macro(title: str, theme: str, link: float) -> bool:
    if theme != "macro" or link >= 1.2:
        return False
    return sum(1 for w in HEAVY_MACRO if w in title) >= 1


def is_breaking(title: str) -> bool:
    return "속보" in title or "긴급" in title


def norm_title(t: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", t)


STOPWORDS = {"그리고", "하지만", "이번", "오늘", "지금", "결국", "대한", "위한", "관련", "이같",
             "있다", "있다는", "한다", "했다", "된다", "다는", "라는", "보다", "에서", "으로",
             "까지", "부터", "따라", "대해", "모두", "우리", "이날", "지난", "올해", "내년"}


def title_tokens(t: str) -> set:
    words = re.findall(r"[가-힣A-Za-z]{2,}", t)
    return {w for w in words if w not in STOPWORDS}


def is_near_duplicate(t: str, seen: list, seen_tokens: list) -> bool:
    """같은 사건을 살짝 바꿐 제목(다른 매체 중복)을 걸러낸다."""
    n = norm_title(t)
    if not n:
        return True
    toks = title_tokens(t)
    for s, st in zip(seen, seen_tokens):
        if n == s:
            return True
        k = min(len(n), len(s), 22)
        if k >= 12 and n[:k] == s[:k]:
            return True
        if len(n) > 10 and (n in s or s in n):
            return True
        if toks and st:
            inter = len(toks & st)
            if inter / max(1, len(toks | st)) >= 0.55:
                return True
    return False


# --- 같은 사건을 다룬 속보 묶기 — 제목이 달라도 핵심 말이 같으면 한 사건이다(2026-11-22 지시 #11029).
#   '증안펀드' ↔ '증시안정펀드'처럼 줄인 말은 원말로 펴서 비교한다. 그래서 세 칸이 모두 같은 사건의
#   다른 매체 기사로 채워지던 문제를 없앤다.
FLASH_GENERIC = {
    "정부", "금융당국", "당국", "증시", "주식", "코스피", "코스닥", "시장", "투자", "투자자",
    "우려", "전망", "발표", "착수", "준비", "가동", "대응", "강화", "확대", "논의", "검토",
    "관련", "오늘", "내일", "국내", "급락", "급등", "폭락", "폭등", "하락", "상승", "속보",
    "단독", "종합", "매체", "기자", "사태", "논란", "비상", "경고", "대책", "방침",
}


def _is_abbrev(a: str, b: str) -> bool:
    """'증안펀드'가 '증시안정펀드'의 줄임말인지 — 첫 글자가 같고, 글자가 순서대로 들어 있으면."""
    if len(a) < 3 or len(b) <= len(a) + 1 or a[0] != b[0]:
        return False
    it = iter(b)
    return all(ch in it for ch in a)


def _fold_into(toks: set, universe: set) -> set:
    """줄임말을 원말로 편다 — 비교하는 두 제목에서 같이 나온 말을 기준으로 한다."""
    out = set()
    for t in toks:
        for o in sorted(universe, key=len, reverse=True):
            if o != t and _is_abbrev(t, o):
                t = o
                break
        out.add(t)
    return out


def _is_company(tok: str) -> bool:
    """상장사 이름이 든 말인지 — 회사 이름 하나가 겹쳤다고 다른 사건을 한 칸으로 합치지 않는다."""
    return any(n in tok or tok in n for n in LISTED if len(n) >= 3)


def _core_tokens(title: str) -> set:
    """제목의 알맹이 말 — '정부·증시 급락' 같은 흔한 말과 회사 이름만 있는 말은 뺀다."""
    return {t for t in title_tokens(title) if t not in FLASH_GENERIC and not _is_company(t)}


def _shared_concepts(ta: set, tb: set) -> set:
    """두 제목이 같이 쓰는 알맹이 말 — '자사주'와 '자사주로'처럼 한쪽이 다른 쪽을 품으면 같은 말로 본다."""
    out = set()
    for a in ta:
        for b in tb:
            if a == b:
                out.add(a)
            elif min(len(a), len(b)) >= 3 and (a in b or b in a):
                out.add(a if len(a) >= len(b) else b)
    return out


def _bigram_jac(a: str, b: str) -> float:
    if len(a) < 2 or len(b) < 2:
        return 0.0
    ba = {a[i:i + 2] for i in range(len(a) - 1)}
    bb = {b[i:i + 2] for i in range(len(b) - 1)}
    return len(ba & bb) / max(1, len(ba | bb))


def same_flash_issue(a_title: str, b_title: str) -> bool:
    """두 속보 제목이 같은 사건인지 — 핵심 말이 겹치거나, 글자 결이 크게 겹치면 같은 사건으로 본다.

    핵심 말 하나만 겹칠 때는 글자 결(두 글자 묶음)도 어느 정도 겹쳐야 한다 — 회사 이름 하나가
    겹쳤다는 이유로 서로 다른 사건을 한 칸으로 합치지 않게.
    """
    na, nb = norm_title(a_title), norm_title(b_title)
    if not na or not nb:
        return False
    if na == nb or (len(na) > 10 and (na in nb or nb in na)):
        return True
    ta, tb = _core_tokens(a_title), _core_tokens(b_title)
    universe = ta | tb
    shared = (_fold_into(ta, universe) & _fold_into(tb, universe)) | _shared_concepts(ta, tb)
    jac = _bigram_jac(na, nb)
    if any(len(t) >= 4 for t in shared) and jac >= 0.10:
        return True
    if len(shared) >= 2 and jac >= 0.06:
        return True
    return jac >= 0.45


# --------------------------------------------------------------------------- 대체 수집
def collect_google_news():
    """네이버 수집이 실패했을 때 쓰는 비상 경로 (Google 뉴스 RSS, API 키 불필요)."""
    queries = ["코스피 증시", "주식 상한가 특징주", "반도체 HBM 수주", "국내 증시 외국인 수급"]
    out = []
    for q in queries:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q) +
               "&hl=ko&gl=KR&ceid=KR:ko")
        try:
            xml = fetch(url)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] google rss failed ({q}): {e}", file=sys.stderr)
            continue
        for m in re.finditer(r"<item>(.*?)</item>", xml, re.S):
            block = m.group(1)
            t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.S)
            l = re.search(r"<link>(.*?)</link>", block, re.S)
            p = re.search(r"<pubDate>(.*?)</pubDate>", block, re.S)
            s = re.search(r"<source[^>]*>(.*?)</source>", block, re.S)
            if not (t and l):
                continue
            title = html_lib.unescape(re.sub(r"<[^>]+>", "", t.group(1))).strip()
            link = html_lib.unescape(l.group(1)).strip()
            press = html_lib.unescape(s.group(1)).strip() if s else ""
            if " - " in title:
                title, _, maybe_press = title.rpartition(" - ")
                press = press or maybe_press
            item = {
                "id": "g:" + link[-40:],
                "title": title,
                "lede": "",
                "press": press,
                "url": link,
                "section": "google",
                "weight": 0.6,
                "source": "google",
            }
            if p:
                try:
                    dt = parsedate_to_datetime(p.group(1).strip()).astimezone(KST)
                    item["time"] = dt.isoformat()
                except Exception:  # noqa: BLE001
                    pass
            out.append(item)
    print(f"[info] google fallback: {len(out)} items", file=sys.stderr)
    return out


# --------------------------------------------------------------------------- 테마 순위·흐름 힌트
def to_dt(iso: str):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def theme_keywords(theme_id: str, arts: list, limit: int = 4):
    """테마 기사들에서 실제로 반복 등장한 키워드만 뽑는다 (빈도 기준, 추정 없음)."""
    score = {}
    for kw, _w in THEME_KWS.get(theme_id, []):
        if kw in GENERIC_KEYWORDS:
            continue
        s = 0
        for a in arts:
            title = a.get("title", "")
            summ = a.get("summary") or ""
            tags = a.get("tags") or []
            if kw in title:
                s += 3
            elif kw in tags:
                s += 2
            elif kw in summ:
                s += 1
        if s:
            score[kw] = s
    picked, picked_canon = [], set()
    for kw, _s in sorted(score.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0])):
        canon = KEYWORD_ALIAS.get(kw, kw)
        if canon in picked_canon or any(kw in p or p in kw for p in picked):
            continue
        picked.append(kw)
        picked_canon.add(canon)
        if len(picked) >= limit:
            break
    return picked


def flow_pool_from_articles(arts: list):
    pool = []
    for a in arts:
        t = to_dt(a.get("time"))
        if not t:
            continue
        title = a.get("title", "")
        full = title + " " + (a.get("summary") or "")
        pool.append((t, a.get("press", ""),
                     1 if (a.get("relevance") or 0) >= 14 else 0,
                     1 if any(w in full for w in STRUCT_WORDS) else 0,
                     1 if any(w in title for w in BURST_WORDS) else 0))
    return pool


def flow_hint(pool: list, now: datetime, count: int = 0):
    """공개 뉴스 패턴만으로 '단기 불씨' / '중기 흐름'을 가른다.
    pool = (보도시각, 매체, 화제, 구조적 표현, 속보성 표현) 튜플 목록 (최근 24시간 이력)."""
    n = len(pool)
    if not n:
        return {"type": "short", "label": "단기 불씨", "reason": "보도 시각 정보가 없어 흐름을 가르지 못했습니다."}

    times = [p[0] for p in pool]
    t3 = now - 3 * HOUR
    t6 = now - 6 * HOUR
    n3 = sum(1 for t in times if t >= t3)
    n6 = sum(1 for t in times if t >= t6)
    span = (max(times) - min(times)).total_seconds() / 3600.0
    hours = len({t.strftime("%Y-%m-%d %H") for t in times})
    presses = {p[1] for p in pool if p[1]}
    hot = sum(p[2] for p in pool)
    struct = sum(p[3] for p in pool)
    burst = sum(p[4] for p in pool)

    # 단기: 최근 몇 시간에 몰리고 속보성 표현이 많은가
    short = 0
    short += 3 if n3 / n >= 0.6 else (2 if n3 / n >= 0.35 else (1 if n3 / n >= 0.2 else 0))
    short += 2 if span <= 3 else (1 if span <= 6 else 0)
    short += 1 if burst >= 2 else 0
    short += 1 if hot >= 3 else 0

    # 중기: 하루를 넘겨 이어지는 보도 폭 + 다수 매체 + 구조적 업황·정책 표현
    long_ = 0
    long_ += 2 if span >= 18 else (1 if span >= 12 else 0)
    long_ += 1 if hours >= 8 and span >= 8 else 0
    long_ += 1 if len(presses) >= 8 and span >= 8 else 0
    long_ += 1 if struct >= 3 and span >= 8 else 0
    long_ += 1 if n >= 12 and span >= 8 else 0

    ratio6 = round(n6 / n * 100)
    if short > long_:
        reason = f"최근 3시간 {n3}건 · 최근 6시간 {n6}건({ratio6}%) · 보도 폭 {span:.1f}시간 · 매체 {len(presses)}곳"
        if burst:
            reason += f" · 속보성 표현 {burst}건"
        return {"type": "short", "label": "단기 불씨", "reason": reason}
    reason = f"보도 폭 {span:.1f}시간 · {hours}개 시간대 · 매체 {len(presses)}곳 · 24시간 {n}건 · 최근 6시간 {n6}건({ratio6}%)"
    if struct:
        reason += f" · 업황·정책 표현 {struct}건"
    return {"type": "medium", "label": "중기 흐름", "reason": reason}


HISTORY_HOURS = 26
HISTORY_MAX_ROWS = 1600


def load_history(path: str):
    """직전 실행이 data/news.json 에 남긴 테마별 24시간 보도 기록을 읽는다."""
    try:
        with open(path, encoding="utf-8") as f:
            prev = json.load(f)
        hist = prev.get("history")
        return hist if isinstance(hist, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def update_history(old: dict, kept: list, now: datetime):
    """기사 id 기준으로 중복 없이 합쳐 26시간까지만 남긴다 (기사는 공개 뉴스 메타뿐)."""
    cutoff = (now - timedelta(hours=HISTORY_HOURS)).strftime("%Y-%m-%dT%H")
    out = {}
    for tid, rows in (old or {}).items():
        if not isinstance(rows, list):
            continue
        clean = [r for r in rows if isinstance(r, list) and len(r) >= 6 and isinstance(r[1], str) and r[1] >= cutoff]
        if clean:
            out[tid] = clean

    for a in kept:
        tid = a.get("theme")
        if not tid or tid == "etc":
            continue
        t = to_dt(a.get("time")) or now
        hour = t.strftime("%Y-%m-%dT%H")
        if hour < cutoff:
            continue
        rows = out.setdefault(tid, [])
        rid = a.get("id") or a.get("url")
        if any(r[0] == rid for r in rows):
            continue
        full = a.get("title", "") + " " + (a.get("summary") or "")
        rows.append([rid, hour, (a.get("press") or "")[:20],
                     1 if (a.get("relevance") or 0) >= 14 else 0,
                     1 if any(w in full for w in STRUCT_WORDS) else 0,
                     1 if any(w in a.get("title", "") for w in BURST_WORDS) else 0])

    # 너무 커지지 않게 오래된 기록부터 덜어낸다
    total = sum(len(v) for v in out.values())
    if total > HISTORY_MAX_ROWS:
        flat = [(r[1], tid, r) for tid, rows in out.items() for r in rows]
        flat.sort(key=lambda x: x[0])
        drop = set(id(r) for _h, _t, r in flat[: total - HISTORY_MAX_ROWS])
        for tid in list(out):
            out[tid] = [r for r in out[tid] if id(r) not in drop]
            if not out[tid]:
                del out[tid]
    return out


def build_themes_rank(kept: list, now: datetime, history: dict | None = None):
    """기사 수 기준 테마 순위 + 흐름 힌트 (기타 테마는 순위에서 뺀다)."""
    history = history or {}
    by_theme = {}
    for a in kept:
        if a.get("theme") == "etc":
            continue
        by_theme.setdefault(a["theme"], []).append(a)

    rows = []
    for tid, arts in by_theme.items():
        arts = sorted(arts, key=lambda a: a.get("time") or "", reverse=True)
        times = [t for t in (to_dt(a.get("time")) for a in arts) if t]
        span = round((max(times) - min(times)).total_seconds() / 3600.0, 1) if len(times) > 1 else 0.0
        n6, hot = 0, 0

        # 24시간 보도 기록이 있으면 그것으로 흐름을 가르고, 없으면 이번 수집분만 쓴다
        hist = history.get(tid) or []
        pool = []
        for r in hist:
            t = datetime.strptime(r[1], "%Y-%m-%dT%H").replace(tzinfo=KST)
            pool.append((t, r[2], r[3], r[4], r[5]))
        hint_pool = pool if len(pool) >= len(arts) else flow_pool_from_articles(arts)
        day_n = len(hint_pool)
        day_presses = len({p[1] for p in hint_pool if p[1]})
        # 표시 수치와 힌트 판정이 같은 24시간 기록을 쓰도록 맞춘다
        pool_times = [p[0] for p in hint_pool]
        n6 = sum(1 for t in pool_times if t >= now - 6 * HOUR)
        hot = sum(p[2] for p in hint_pool)

        rows.append({
            "id": tid,
            "label": THEME_LABEL.get(tid, "기타"),
            "color": THEME_COLOR.get(tid, "#9aa4b2"),
            "count": len(arts),
            "recent_6h": n6,
            "recent_6h_ratio": round(n6 / day_n * 100) if day_n else 0,
            "day_count": day_n,
            "hot": hot,
            "presses": day_presses or len({a.get("press") for a in arts if a.get("press")}),
            "span_hours": span,
            "keywords": theme_keywords(tid, arts),
            "headlines": [{"title": a["title"], "url": a["url"], "press": a.get("press", ""),
                           "time": a.get("time", "")} for a in arts[:2]],
            "leaders": theme_leaders(tid, [{"title": a["title"]} for a in arts[:2]]),
            "hint": flow_hint(hint_pool, now, count=len(arts)),
        })
    rows.sort(key=lambda r: (-r["count"], -r["hot"], -r["recent_6h"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


# --------------------------------------------------------------------------- 대장주 배지
# 공개 시장에서 통상 쓰이는 테마별 '상한가 주도 대장주' 이름만 담는다(개인 DB·룰·매매 기준은 쓰지 않는다).
# 종목명은 모두 국내 증시 상장사이며, 기사에 직접 언급된 회사를 먼저 보여준다.
# 피해 기관 이름 안에 들어 있는 테마 키워드 — 이 글자로 전력·통신 테마 종목을 부르지 않게 먼저 가린다.
#   예) '한국전력공사'의 '전력'이 전력설비 대장주(HD현대일렉트릭·LS일렉트릭)를 불렀다(2026-11-22 지시 #11051).
ENTITY_MASK = (
    ("한국전력공사", "한전"), ("한국전력", "한전"), ("전력거래소", "전력당국"),
    ("한전KPS", "한전"), ("한전KDN", "한전"), ("한전기술", "한전"),
    ("SK텔레콤", "SKT"), ("SK브로드밴드", "SKT"), ("LG유플러스", "LGU+"),
    ("롯데카드", "롯데"), ("롯데마트", "롯데"), ("롯데이노베이트", "롯데"),
)

# 개인정보 유출·해킹 사건의 말 — 피해 기관의 업종(전력·통신·유통)으로 종목을 부르지 않는다.
SECURITY_CONTEXT = ("개인정보", "유출", "털렸", "털려", "해킹", "보안", "사이버", "랜섬웨어",
                    "악성코드", "피싱", "침해", "정보보호", "딥페이크", "명의도용", "랜섬")


def mask_entities(text: str) -> str:
    """기관·회사 이름을 줄여 쓴 말로 바꿔, 이름 속 글자가 테마 키워드로 읽히지 않게 한다."""
    for a, b in ENTITY_MASK:
        text = text.replace(a, b)
    return text


def is_security_context(text: str) -> bool:
    return any(w in text for w in SECURITY_CONTEXT)


def _rule(name, themes, strong, kws, stocks):
    return {"name": name, "themes": set(themes), "strong": tuple(strong),
            "kws": tuple(kws), "stocks": list(stocks)}


# 규칙마다 ① 이 규칙이 사는 분류 테마(themes) ② 제목에서만 인정하는 강한 말(strong)을 둔다.
#   기사 분류 주제가 규칙과 어긋나면, 제목에 그 테마의 강한 말이 있을 때만 규칙을 쓴다
#   (2026-11-22 지시 #11051 — 카테고리와 종목 칩이 서로 어긋나지 않게).
LEADER_RULES = (
    _rule("ai_security", ("aisec", "semiconductor"),
          ("부정행위", "커닝", "스마트안경", "AI 보안", "보안", "해킹", "딥페이크", "피싱",
           "랜섬웨어", "개인정보", "유출", "침해", "정보보호", "악성코드"),
          ("부정행위", "커닝", "스마트안경", "AI 보안", "보안", "해킹", "딥페이크", "위조", "탐지",
           "전수검사", "안경", "개인정보", "유출", "털렸", "털려", "침해", "정보보호", "피싱",
           "사이버", "랜섬웨어", "악성코드", "명의도용"),
          ["지슨", "라온시큐어", "샌즈랩", "한싹", "아톤", "엑스게이트"]),
    _rule("lng", ("battery", "geopolitics", "policy", "earnings"),
          ("알래스카", "가스관", "가스전", "LNG"),
          ("알래스카", "가스관", "가스전", "액화천연가스", "LNG 사업", "LNG 프로젝트"),
          ["동양철관", "하이스틸", "화성밸브", "세아제강"]),
    _rule("north", ("geopolitics", "policy", "earnings"),
          ("남북", "북미", "북한", "개성", "경협", "금강산", "대북"),
          ("남북", "북미", "북한", "김정은", "개성", "경협", "금강산", "대북"),
          ["인디에프", "좋은사람들", "코데즈컴바인", "아난티"]),
    _rule("medical_ai", ("bio", "semiconductor"),
          ("의료 AI", "의료AI", "AI 진단", "진단 AI", "의료기기"),
          ("의료 AI", "의료AI", "AI 진단", "진단 AI", "의료기기"),
          ["루닛", "노을", "뷰노"]),
    _rule("disaster", ("disaster", "policy"),
          ("지진", "재난", "태풍", "호우", "폭설", "한파", "산불", "대피"),
          ("지진", "재난", "태풍", "호우", "폭설", "한파", "산불", "대피", "안전", "소방"),
          ["삼영엠텍", "파라텍", "포메탈"]),
    _rule("nuclear", ("battery", "policy", "defense"),
          ("원전", "원자력", "SMR", "핵발전"),
          ("원전", "원자력", "SMR", "체코 원전", "핵발전"),
          ["두산에너빌리티", "우리기술", "한신기계", "보성파워텍"]),
    _rule("defense", ("defense", "geopolitics"),
          ("방산", "국방", "미사일", "전투기", "K9", "천궁", "전쟁"),
          ("방산", "국방", "미사일", "전투기", "K9", "천궁", "지정학", "전쟁", "이스라엘",
           "우크라이나", "중동"),
          ["LIG넥스원", "빅텍", "스페코", "한일단조"]),
    _rule("robot", ("robot", "semiconductor"),
          ("로봇", "휴머노이드", "자율주행", "피지컬 AI"),
          ("로봇", "휴머노이드", "자율주행", "피지컬 AI"),
          ["레인보우로보틱스", "클로봇", "유일로보틱스", "계양전기"]),
    _rule("battery", ("battery", "earnings"),
          ("2차전지", "이차전지", "배터리", "리튬", "양극재", "음극재"),
          ("2차전지", "이차전지", "배터리", "리튬", "양극재", "음극재"),
          ["에코프로비엠", "리튬포어스", "하이드로리튬"]),
    _rule("semiconductor", ("semiconductor", "earnings"),
          ("반도체", "HBM", "D램", "메모리", "파운드리", "엔비디아"),
          ("반도체", "HBM", "D램", "메모리", "파운드리", "엔비디아", "데이터센터", "AI 인프라",
           "삼전닉스", "삼성전자", "SK하이닉스", "소부장", "웨이퍼"),
          ["한미반도체", "이수페타시스", "가온칩스", "티엘비", "제주반도체"]),
    _rule("power", ("battery", "earnings"),
          ("변압기", "송전", "전력망", "전력기기", "전력설비"),
          ("전력", "변압기", "송전", "전력망", "전력기기"),
          ["HD현대일렉트릭", "LS일렉트릭", "산일전기", "제룡전기"]),
    _rule("shipbuilding", ("battery", "earnings", "geopolitics"),
          ("조선", "선박", "LNG선"),
          ("조선", "선박", "LNG선"),
          ["HD한국조선해양", "한화오션", "세진중공업"]),
    _rule("auto", ("battery", "earnings", "geopolitics"),
          ("자동차", "전기차", "완성차"),
          ("자동차", "전기차", "완성차", "부품주"),
          ["현대차", "기아"]),
    _rule("bio", ("bio", "earnings"),
          ("바이오", "제약", "임상", "신약", "CDMO", "기술수출"),
          ("바이오", "제약", "임상", "신약", "CDMO", "기술수출"),
          ["알테오젠", "HLB", "삼성바이오로직스"]),
    _rule("llm", ("semiconductor", "earnings"),
          ("LLM", "챗GPT", "AI 반도체", "AI 팩토리", "AI 데이터센터"),
          ("LLM", "챗GPT", "AI 반도체", "AI 팩토리", "AI 데이터센터"),
          ["네이버", "카카오", "코난테크놀로지", "솔트룩스"]),
    _rule("construction", ("policy", "earnings"),
          ("건설", "재건축", "재개발", "SOC", "인프라"),
          ("건설", "재건축", "재개발", "SOC", "인프라"),
          ["현대건설", "대우건설", "DL이앤씨"]),
    _rule("steel", ("battery", "earnings", "geopolitics"),
          ("철강", "원자재", "철광석", "구리", "니켈"),
          ("철강", "원자재", "철광석", "구리", "니켈"),
          ["POSCO홀딩스", "현대제철"]),
    _rule("space", ("defense", "earnings"),
          ("우주", "위성", "발사체", "누리호"),
          ("우주", "위성", "발사체", "누리호"),
          ["쎄트렉아이", "한국항공우주"]),
    _rule("entertainment", ("policy", "earnings", "etc"),
          ("엔터", "K팝", "음원", "드라마 제작"),
          ("엔터", "K팝", "음원", "드라마 제작"),
          ["하이브", "에스엠", "JYP Ent."]),
)


def _order_stocks(rule: dict, text: str) -> list:
    """같은 보안 테마라도 사건에 맞는 종목을 앞세운다 — 시험 부정행위·커닝은 지슨(감독·탐지),
    개인정보 유출·해킹은 라온시큐어·샌즈랩 쪽이 먼저다(화면은 앞의 두 개만 칩으로 보여 준다)."""
    stocks = list(rule["stocks"])
    if rule["name"] == "ai_security":
        exam = any(k in text for k in ("부정행위", "커닝", "시험", "수능", "스마트안경", "감독"))
        if exam:
            stocks = ["지슨"] + [s for s in stocks if s != "지슨"]
        else:
            stocks = [s for s in stocks if s != "지슨"] + ["지슨"]
    return stocks


def _rule_matches(rule: dict, src: str, title_like: str, theme_id: str | None,
                  security: bool) -> bool:
    """기사 분류(주제)와 규칙 테마가 어긋나면 제목의 강한 말이 있을 때만 규칙을 쓴다."""
    strong = any(k in title_like for k in rule["strong"])
    if security and rule["name"] != "ai_security" and not strong:
        # 개인정보 유출·해킹 기사 — 피해 기관의 업종(전력 등) 종목은 붙이지 않는다
        return False
    if theme_id in rule["themes"] or theme_id in (None, "etc"):
        return any(k in src for k in rule["kws"])
    return strong and any(k in src for k in rule["kws"])

THEME_LEADERS = {
    "semiconductor": ["한미반도체", "이수페타시스", "가온칩스"],
    "robot": ["레인보우로보틱스", "클로봇", "유일로보틱스"],
    "defense": ["LIG넥스원", "빅텍", "스페코"],
    "bio": ["알테오젠", "HLB", "삼성바이오로직스"],
    "battery": ["에코프로비엠", "리튬포어스", "하이드로리튬"],
    "policy": ["현대건설", "대우건설"],
    "geopolitics": ["인디에프", "좋은사람들", "코데즈컴바인"],
    "aisec": ["지슨", "라온시큐어", "샌즈랩"],
    "disaster": ["삼영엠텍", "파라텍", "포메탈"],
}

# 기사에 이름이 직접 나오면 대장주 후보로 올리는 국내 상장사 (너무 짧은 약칭은 오인 방지를 위해 제외)
LISTED = (
    "삼성전자", "SK하이닉스", "한미반도체", "이수페타시스", "가온칩스", "티엘비", "제주반도체",
    "이오테크닉스", "HPSP", "네이버", "카카오", "코난테크놀로지", "솔트룩스", "알테오젠",
    "삼성바이오로직스", "셀트리온", "한미약품", "유한양행", "HLB", "루닛", "노을", "뷰노",
    "현대차", "기아", "LG에너지솔루션", "삼성SDI", "에코프로비엠", "포스코퓨처엠", "POSCO홀딩스",
    "현대제철", "HD현대일렉트릭", "LS일렉트릭", "산일전기", "제룡전기", "효성중공업",
    "두산에너빌리티", "한전기술", "우리기술", "한신기계", "보성파워텍", "HD한국조선해양",
    "한화오션", "삼성중공업", "한화에어로스페이스", "LIG넥스원", "현대로템", "한국항공우주",
    "레인보우로보틱스", "두산로보틱스", "클로봇", "유일로보틱스", "계양전기", "빅텍", "스페코",
    "한일단조", "동양철관", "하이스틸", "화성밸브", "세아제강", "한국가스공사", "삼영엠텍",
    "파라텍", "포메탈", "리튬포어스", "하이드로리튬", "지슨", "라온시큐어", "샌즈랩",
    "인디에프", "좋은사람들", "코데즈컴바인", "아난티", "세진중공업", "현대건설", "대우건설",
    "DL이앤씨", "쎄트렉아이", "하이브", "에스엠", "이마트", "아모레퍼시픽", "LG전자",
)


def leaders_for(text: str, theme_id: str | None = None, limit: int = 4, named_text: str | None = None):
    """기사 제목에 직접 언급된 상장사를 앞세우고, 부족하면 공개 테마 대장주로 채운다.

    테마 대장주는 제목에서 먼저 찾고, 제목에 단서가 없을 때만 요약문까지 본다
    (요약문의 스쳐 지나가는 단어로 엉뚱한 종목이 붙는 것을 막는다).
    2026-11-22 지시(#11051) — 기사 분류(주제)와 규칙 테마가 어긋나면 붙이지 않고,
    피해 기관 이름 속 글자(한국전력 → 전력)는 테마 키워드로 읽지 않는다.
    """
    # 통용 약칭을 정식 종목명으로 바꿔 읽는다
    for a, b in (("삼전닉스", "삼성전자"), ("LS, 일렉트릭", "LS일렉트릭"), ("LS 일렉트릭", "LS일렉트릭"),
                 ("LS일렉", "LS일렉트릭"), ("한화에어로", "한화에어로스페이스"),
                 ("하닉", "SK하이닉스"), ("삼전", "삼성전자")):
        text = text.replace(a, b)
        if named_text is not None:
            named_text = named_text.replace(a, b)
    # 대장주 판단에서만 '재난문자'를 재난 테마로 오인하지 않게 바꿔 읽는다
    text = text.replace("재난문자", "안내문자")
    named_text = None if named_text is None else named_text.replace("재난문자", "안내문자")

    out = []
    title_like = mask_entities(named_text if named_text is not None else text)
    named_src = mask_entities(named_text if named_text is not None else text)
    for name in sorted(LISTED, key=len, reverse=True):
        if name not in named_src:
            continue
        if any(name in o for o in out):
            continue
        out.append(name)
        if len(out) >= limit:
            return out
    security = is_security_context(mask_entities(text))
    for source in ((named_text or text), text):
        src = mask_entities(source)
        for rule in LEADER_RULES:
            if not _rule_matches(rule, src, title_like, theme_id, security):
                continue
            for s in _order_stocks(rule, src):
                if s not in out:
                    out.append(s)
                if len(out) >= limit:
                    return out
            return out[:limit]  # 첫 번째로 맞는 테마의 대장주만 쓴다
    return out

def theme_leaders(theme_id: str, headlines: list, limit: int = 4):
    base = list(THEME_LEADERS.get(theme_id, []))
    if base:
        return base[:limit]
    out = []
    for h in headlines or []:
        for name in leaders_for(h.get("title", ""), limit=limit):
            if name not in out:
                out.append(name)
    return out[:limit]


# --------------------------------------------------------------------------- 실시간 속보
# 네이버 금융 실시간 속보 (news_list.naver?mode=LSS2D&section_id=101&section_id2=258).
# 이 주소는 stock.naver.com/news/flashnews 로 넘어가 화면을 스크립트로 그리므로,
# 같은 목록을 내려주는 공개 JSON 경로를 먼저 읽고, 그 경로가 막히면 예전 목록 HTML을 파싱한다.
FLASH_LEGACY_URL = ("https://finance.naver.com/news/news_list.naver"
                    "?mode=LSS2D&section_id=101&section_id2=258")
FLASH_API = "https://stock.naver.com/api/domestic/news/list"
FLASH_REFERER = "https://stock.naver.com/news/flashnews"


def fetch_json(url: str, referer: str = FLASH_REFERER, timeout: int = 15, retries: int = 1):
    last = None
    for _ in range(retries + 1):
        try:
            _wait_turn("section")
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "ko-KR,ko;q=0.9",
                "Referer": referer,
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"json fetch failed: {url} ({last})")


FLASH_LEGACY_ITEM = re.compile(r'class="articleSubject"(.*?)(?=class="articleSubject"|</ul>)', re.S)
FLASH_LEGACY_HREF = re.compile(r'href="[^"]*news_read\.naver\?([^"]+)"')
FLASH_LEGACY_DATE = re.compile(r'class="articleDate"[^>]*>([^<]+)<')
FLASH_LEGACY_PRESS = re.compile(r'class="press"[^>]*>([^<]+)<')
FLASH_LEGACY_TITLE = re.compile(r'>([^<>]{6,})</a>')


def parse_flash_legacy():
    """예전 목록 HTML(articleSubject)에서 속보를 읽는다 (JSON 경로가 막혔을 때)."""
    try:
        page = fetch(FLASH_LEGACY_URL, encoding="utf-8", timeout=20)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] flash legacy page failed: {e}", file=sys.stderr)
        return []
    out = []
    for chunk in FLASH_LEGACY_ITEM.findall(page)[:80]:
        m_href = FLASH_LEGACY_HREF.search(chunk)
        m_title = FLASH_LEGACY_TITLE.search(chunk)
        if not (m_href and m_title):
            continue
        qs = urllib.parse.parse_qs(m_href.group(1))
        aid = (qs.get("article_id") or [""])[0]
        oid = (qs.get("office_id") or [""])[0]
        title = " ".join(strip_tags(m_title.group(1)).split())
        if not (aid and oid and title):
            continue
        m_press = FLASH_LEGACY_PRESS.search(chunk)
        out.append({
            "id": f"{oid}/{aid}",
            "title": title,
            "press": strip_tags(m_press.group(1)) if m_press else "",
            "summary": "",
            "url": f"https://n.news.naver.com/article/{oid}/{aid}",
            "raw_time": (FLASH_LEGACY_DATE.search(chunk).group(1).strip()
                         if FLASH_LEGACY_DATE.search(chunk) else ""),
        })
    print(f"[info] flash legacy: {len(out)} items", file=sys.stderr)
    return out


def parse_flash_api():
    """네이버 금융 실시간 속보 JSON 목록을 최신순으로 읽는다."""
    out = []
    for page in range(1, FLASH_PAGES + 1):
        url = f"{FLASH_API}?category=FLASHNEWS&page={page}&pageSize={FLASH_PAGE_SIZE}"
        try:
            data = fetch_json(url)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] flash api page {page} failed: {e}", file=sys.stderr)
            break
        arts = data.get("articles") or []
        for a in arts:
            aid, oid = str(a.get("articleId") or ""), str(a.get("officeId") or "")
            title = " ".join((a.get("title") or "").split())
            if not (aid and oid and title):
                continue
            out.append({
                "id": f"{oid}/{aid}",
                "title": html_lib.unescape(title),
                "press": (a.get("officeHname") or "").strip(),
                "summary": make_summary(html_lib.unescape(a.get("subcontent") or ""), 150),
                "url": f"https://n.news.naver.com/article/{oid}/{aid}",
                "raw_time": (a.get("datetime") or "").strip(),
            })
        if len(arts) < FLASH_PAGE_SIZE:
            break
    print(f"[info] flash api: {len(out)} items", file=sys.stderr)
    return out


def flash_time(raw: str, now: datetime):
    """'2026-11-18 07:59:14' / '2026-11-18 07:59' 표기를 시각으로 바꾼다."""
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    return now


def collect_flash_news(now: datetime, extra: list | None = None, popular: list | None = None) -> list:
    """실시간 속보를 모아 화면용 최대 3건으로 줄인다 (2026-11-22 지시: 6 → 3).

    상단 '실시간 속보'는 많은 사람이 보고 있는 뉴스가 먼저다. 최근 60분 안에 나온
    네이버 금융 증시·산업 뉴스 가운데 ① 네이버 뉴스 메인 '언론사별 많이 본 뉴스'에
    오른 기사(인기) ② 같은 사건을 여러 매체가 함께 다룬 기사(확산) ③ 최신 시각 순으로
    점수를 매겨 상위 3건만 올린다. 새벽처럼 새 뉴스가 적을 때만 FLASH_MIN_FRESH건을 채운다.
    """
    raw = parse_flash_api()
    if not raw:
        raw = parse_flash_legacy()
    if not raw:  # 마지막 비상 경로: 이번 수집분의 기사
        raw = list(extra or [])
        for a in raw:
            a.setdefault("raw_time", "")

    seen_titles, seen_tokens, rows = [], [], []
    seen_ids = set()
    for a in raw:
        if a["id"] in seen_ids:
            continue
        seen_ids.add(a["id"])
        title = a["title"]
        if len(title) < 8:
            continue
        if not is_main_relevant({"title": title, "lede": a.get("summary", "")}):
            continue
        if is_near_duplicate(title, seen_titles, seen_tokens):
            continue
        t = flash_time(a.get("raw_time", ""), now)
        age = (now - t).total_seconds() / 60.0
        seen_titles.append(norm_title(title))
        seen_tokens.append(title_tokens(title))
        tid, _tags, _rel = classify({"title": title, "lede": a.get("summary", ""), "weight": 0.9})
        rows.append({
            "id": a["id"],
            "title": title,
            "press": a.get("press", ""),
            "time": t.isoformat(),
            "url": a["url"],
            "summary": a.get("summary", ""),
            "theme": tid,
            "theme_label": THEME_LABEL.get(tid, "기타"),
            "theme_color": THEME_COLOR.get(tid, "#9aa4b2"),
            "age_min": int(max(0, age)),
            "leaders": leaders_for(title + " " + a.get("summary", ""), tid, limit=2,
                                   named_text=title),
        })

    rows.sort(key=lambda r: r["time"], reverse=True)
    fresh = [r for r in rows if r["age_min"] <= FLASH_FRESH_MIN]
    grace = [r for r in rows if FLASH_FRESH_MIN < r["age_min"] <= FLASH_GRACE_MIN]
    older = [r for r in rows if r["age_min"] > FLASH_GRACE_MIN]

    # 인기·확산 점수 — 많이 본 뉴스에 오른 기사, 여러 매체가 같이 쓴 사건이 위로
    pop_ids = {a.get("id"): (a.get("main_rank") or 9) for a in (popular or [])}
    pop_tokens = [title_tokens(a.get("title", "")) for a in (popular or [])]
    pool = fresh + grace + older
    for r in pool:
        toks = title_tokens(r["title"])
        score = 0.0
        if r["id"] in pop_ids:
            score += 12 - min(8, pop_ids[r["id"]])
        for pt in pop_tokens:
            if toks and pt and len(toks & pt) / max(1, len(toks | pt)) >= 0.34:
                score += 3.5
                break
        # 같은 사건을 다룬 다른 기사 수(매체 확산) — 속보 목록 안에서 센다
        same = sum(1 for o in pool if o is not r and toks and
                   len(toks & title_tokens(o["title"])) / max(1, len(toks | title_tokens(o["title"]))) >= 0.34)
        score += min(6, same)
        if r["age_min"] <= 30:
            score += 2.0
        elif r["age_min"] <= FLASH_FRESH_MIN:
            score += 1.0
        r["hot"] = round(score, 2)

    # 같은 사건을 다룬 기사(정부의 '증안펀드' 가동 준비 등)는 한 묶음으로 보고, 화면에는
    # 묶음마다 1건만 올린다 — 세 칸이 모두 같은 사건의 다른 매체 기사로 채워지던 문제
    # (2026-11-22 지시 #11029). 대표는 그 사건에서 가장 인기·최신인 기사.
    groups: list[list] = []
    for r in sorted(fresh + grace + older, key=lambda r: (-r["hot"], r["time"])):
        for g in groups:
            if any(same_flash_issue(m["title"], r["title"]) for m in g):
                g.append(r)
                break
        else:
            groups.append([r])

    def rep_of(g: list) -> dict:
        """그 사건의 대표 기사 — 인기·확산이 거의 같은 수준이면 가장 최신 기사를 쓴다."""
        window = [r for r in g if r["age_min"] <= FLASH_GRACE_MIN] or g
        top = max(r["hot"] for r in window)
        near_top = [r for r in window if r["hot"] >= top - 1.5]
        return max(near_top, key=lambda r: r["time"])

    for g in groups:  # 묶음 점수 = 대표의 인기·확산 점수 + 같은 사건을 다룬 매체가 늘어난 만큼
        g.sort(key=lambda r: (-r["hot"], r["time"]))
        g[0]["_issue_hot"] = g[0]["hot"] + min(3.0, 0.7 * (len(g) - 1))
    groups.sort(key=lambda g: (-g[0]["_issue_hot"], -len(g), g[0]["time"]))
    window_groups = [g for g in groups if min(r["age_min"] for r in g) <= FLASH_GRACE_MIN]

    picked = [rep_of(g) for g in window_groups[:FLASH_MAX]]
    need = min(FLASH_MIN_FRESH, FLASH_MAX) - len(picked)
    if need > 0:  # 새벽 등 최근 1시간 뉴스가 적을 때만 오래된 기사(다른 사건)로 최소한을 채운다
        for g in groups:
            if len(picked) >= min(FLASH_MIN_FRESH, FLASH_MAX):
                break
            if g in window_groups:
                continue
            picked.append(rep_of(g))

    for r in picked:
        r["fresh"] = r["age_min"] <= FLASH_FRESH_MIN
        r["breaking"] = r["fresh"] and is_breaking(r["title"])
        r.pop("age_min", None)
        r.pop("_issue_hot", None)

    picked.sort(key=lambda r: r["time"], reverse=True)
    fresh_n = sum(1 for r in picked if r.get("fresh"))
    print(f"[info] flash: {len(picked)} cards (최근 {FLASH_FRESH_MIN}분 {fresh_n}건 / "
          f"기사 후보 {len(rows)}건)", file=sys.stderr)
    return picked


# --------------------------------------------------------------------------- 이슈 묶음
# 같은 사건을 다룬 기사끼리 묶어 '매체 수'로 순위를 매기기 위한 토큰·군집 도구
ISSUE_STOP = {
    "있다", "한다", "했다", "이번", "오늘", "지난", "위해", "관련", "대한", "그리고", "하지만",
    "이날", "올해", "내년", "모두", "우리", "결국", "단독", "종합", "속보", "이대로", "무슨",
    "이런", "그런", "어떻게", "아직", "다시", "이게", "저게", "그게", "보다", "에서", "으로",
    "까지", "부터", "따라", "대해", "논란", "의혹", "확산", "나온다", "나왔다", "무죄",
}

MAX_ISSUES = 30          # 대시보드에 남길 이슈 카드 수(화면에는 앞 14건을 3:7 비율로 먼저 보여준다)
MAX_PER_THEME = 3        # 한 테마가 목록을 독점하지 않도록 하는 상한
MAX_RELATED = 3          # 카드에 접어 넣을 다른 매체 기사 수
BREAKING_HOURS = 3       # 이 시간 안에 나온 [속보]만 최상단·속보 배지 (아침 속보가 저녁까지 붙박이되는 것을 막는다)
GOSSIP_SECTIONS = (106, 107)   # 네이버 기사 분류: 연예·스포츠

# 이슈 묶음에서 너무 흔해 서로 다른 사건을 붙이는 말 ("AI" 하나로 연예 가십과 수능 기사가 붙었다)
CLUSTER_STOP = {"AI", "인공지능"}


def issue_tokens(title: str) -> set:
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|[“”\"‘’]", " ", title)
    t = re.sub(r"(\d+)\s*천", lambda m: str(int(m.group(1)) * 1000), t)
    t = re.sub(r"(\d+)\s*만", lambda m: str(int(m.group(1)) * 10000), t)
    words = re.findall(r"[가-힣A-Za-z0-9]{2,}", t)
    return {w for w in words if w not in ISSUE_STOP}


def _jac(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster_news(items: list, max_df: int = 30):
    """제목의 고유 토큰을 2개 이상 공유하면 같은 이슈로 연결한다(2단계 병합)."""
    freq = {}
    for it in items:
        for t in it["tok"]:
            freq[t] = freq.get(t, 0) + 1
    sigs = [{t for t in it["tok"] if 2 <= freq[t] <= max_df and t not in CLUSTER_STOP} for it in items]

    parent = list(range(len(items)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            shared = sigs[i] & sigs[j]
            jj = _jac(items[i]["tok"], items[j]["tok"])
            if (len(shared) >= 2 and jj >= 0.15) or len(shared) >= 3 or jj >= 0.45:
                union(i, j)

    groups = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(i)
    keys = list(groups)
    if len(keys) > 1:
        reps = {k: set().union(*(sigs[i] for i in groups[k])) for k in keys}
        distinctive = {t for t in freq if freq[t] <= 15}
        for a in range(len(keys)):
            for b in range(a + 1, len(keys)):
                ka, kb = keys[a], keys[b]
                if find(groups[ka][0]) == find(groups[kb][0]):
                    continue
                if len((reps[ka] & reps[kb]) & distinctive) >= 3:
                    union(groups[ka][0], groups[kb][0])

    out = {}
    for i in range(len(items)):
        out.setdefault(find(i), []).append(items[i])
    return list(out.values())


def _fresh(a: dict, now: datetime, hours: int = BREAKING_HOURS) -> bool:
    t = to_dt(a.get("time"))
    return bool(t) and (now - t).total_seconds() <= hours * 3600


def _age_penalty(age_h: float) -> int:
    """오래된 이슈는 매체 수에서 깎아 내려 자연스럽게 아래로 내려가게 한다."""
    if age_h <= BREAKING_HOURS:
        return 0
    if age_h <= 6:
        return 1
    if age_h <= 9:
        return 2
    if age_h <= 12:
        return 3
    return 5


def _card_breaking(card: dict, now: datetime) -> bool:
    """최근 BREAKING_HOURS 안에 나온 [속보] 기사가 있을 때만 속보 배지를 단다.

    원문에서 확인한 정확한 시각을 쓰므로 '14시간 전' 같은 상대 표기 반올림으로
    아침 속보가 저녁에 속보 배지를 다시 달지 않는다.
    """
    members = card.get("_members") or [card]
    if is_breaking(card.get("title") or "") and _fresh(card, now):
        return True
    for a in members:
        if a.get("id") == card.get("id"):
            continue      # 대표 기사는 원문에서 확인한 정확한 시각으로만 본다
        if is_breaking(a.get("title") or "") and _fresh(a, now):
            return True
    return False


def is_gossip_card(card: dict) -> bool:
    """연예·가십·개인사 카드인지 판단한다.

    ① 제목·원문 요약에 연예·개인사 말이 있고 증시·산업 단서가 없는 경우
    ② 발행처가 기사를 연예·스포츠로 분류한 경우(증시·산업 단서가 없을 때만)
    """
    text = ((card.get("title") or "") + " " +
            (card.get("summary") or card.get("_lede") or ""))
    if is_gossip(text):
        return True
    if has_market_anchor(text):
        return False
    if card.get("_naver_section") in GOSSIP_SECTIONS:
        return True
    return card.get("_naver_service") == "entertain"


def build_issues(cands: list, now: datetime):
    """같은 이슈를 하나의 카드로 묶고, 매체 수와 속보 여부로 순위를 매긴다."""
    for a in cands:
        a["tok"] = issue_tokens(a["title"])
    groups = cluster_news(cands)

    cards = []
    for g in groups:
        # 대표 기사: 메인 랭킹 순위가 높은 기사 → 관련도 높은 기사
        g.sort(key=lambda a: (a.get("main_rank") or 99, -(a.get("relevance") or 0)))
        rep = g[0]
        presses, plist = [], []
        for a in g:
            p = a.get("press")
            if p and p not in presses:
                presses.append(p)
                plist.append(p)
        best_rank = min((a.get("main_rank") or 99) for a in g)

        related = []
        used = {rep.get("press")}
        for a in g[1:]:
            if a.get("press") in used:
                continue
            used.add(a.get("press"))
            related.append({"title": a["title"], "press": a.get("press", ""),
                            "url": a["url"], "time": a.get("time", "")})
            if len(related) >= MAX_RELATED:
                break

        lede = rep.get("lede") or ""
        if not lede:
            for a in g:
                if a.get("lede"):
                    lede = a["lede"]
                    break

        cards.append({
            "id": rep["id"],
            "title": rep["title"],
            "url": rep["url"],
            "press": rep.get("press", ""),
            "time": rep.get("time", ""),
            "section": rep.get("section", ""),
            "source": rep.get("source", "section"),
            "main_rank": None if best_rank == 99 else best_rank,
            "theme": rep.get("theme", "etc"),
            "theme_label": rep.get("theme_label", "기타"),
            "tags": rep.get("tags", []),
            "presses": len(presses),
            "press_list": plist[:6],
            "related": related,
            "article_count": len(g),
            "breaking": any(is_breaking(a["title"]) and _fresh(a, now) for a in g),
            "relevance": (rep.get("relevance") or 0) + min(24, max(0, len(presses) - 1) * 3),
            "civic": any(a.get("source") in ("civic", "press") for a in g),
            "_members": g,
            "_lede": lede,
        })

    def attach_link(c: dict):
        """이슈 카드가 우리 테마 DB(상한가 테마명·종목)에 바로 닿는지 — 11-22 지시 가중치."""
        text = " ".join([c.get("title") or "", c.get("_lede") or c.get("summary") or ""])
        hits = theme_link(text)
        c["_link"] = {"score": hits[0][0] if hits else 0.0,
                      "theme": hits[0][1] if hits else "",
                      "kw": hits[0][2] if hits else [],
                      "themes": [h[1] for h in hits[:3]]}

    for c in cards:
        attach_link(c)

    # 글로벌·시장 흐름(무거운 거시)은 '오늘 가장 큰 1~2건'만 상단권에 남기고 나머지는 뒤로 — 2026-11-22 지시
    macro_cards = [c for c in cards
                   if is_heavy_macro(c.get("title", ""), c.get("theme", ""),
                                     (c.get("_link") or {}).get("score") or 0.0)]
    macro_cards.sort(key=lambda c: -c.get("presses", 0))
    for c in macro_cards:
        c["_macro_lead"] = False
    for c in macro_cards[:2]:            # 가장 큰 글로벌·시장 2건은 오늘 분위기를 읽는 대표로 남긴다
        c["_macro_lead"] = True

    def ts(c):
        t = to_dt(c.get("time"))
        return t.timestamp() if t else 0

    def order(c):
        """최근 3시간 속보를 먼저, 그 다음은 매체 수·테마 연결·시사 가중치 − 오래된 만큼의 감점.

        2026-11-22 지시: 금리·환율·거시 전망 같은 무거운 기사가 상단을 덮지 않게 하고,
        우리 테마 DB에 바로 닿는 이슈와 여러 매체가 같이 미는 시사·정책·산업 이슈를 위로 올린다.
        """
        t = to_dt(c.get("time"))
        age_h = ((now - t).total_seconds() / 3600.0) if t else 24.0
        link = (c.get("_link") or {}).get("score") or 0.0
        presses = c.get("presses", 0)
        bonus = 0.0
        if link >= 1.2:                                   # 테마 DB에 바로 닿는 이슈
            # 한 매체만 다룬 기사가 여러 매체 이슈를 밀어내지 않게 — 2매체 이상일 때 온전한 가중치
            bonus += min(4.5, 1.1 * link) * (1.0 if presses >= 2 else 0.5)
        if c.get("civic") and presses >= 2:               # 각 매체가 같이 미는 시사·정책 이슈
            bonus += min(3.0, 0.7 * presses)
        # DB에 아직 없는 새 테마 씨앗 — 여러 매체가 같이 미는 새 정책·산업·시사 이슈도
        # 기존 테마 뉴스와 고르게 위로 오게 한다(2026-11-22). 무거운 거시 전망은 제외.
        if (link < 1.2 and presses >= 3
                and not is_heavy_macro(c.get("title", ""), c.get("theme", ""), link)):
            bonus += min(4.0, 1.0 * presses)
        if is_heavy_macro(c.get("title", ""), c.get("theme", ""), link):
            # 오늘 가장 큰 글로벌·시장 흐름 2건은 남기고, 그 밖의 거시 전망은 뒤로
            bonus -= 0.5 if c.get("_macro_lead") else 5.0
        return (0 if c.get("breaking") else 1,
                -(c.get("presses", 0) - _age_penalty(age_h)) - bonus, -ts(c))

    cards.sort(key=order)

    # 원문 조회는 실제로 화면에 남을 카드 위주로 하고, 총 ARTICLE_LIMIT건을 넘기지 않는다
    limit = min(MAX_ISSUES, MAX_ARTICLES)
    enriched_ids: set[str] = set()

    def pick_limited(items: list) -> list:
        """테마별 상한과 전체 카드 수 상한을 적용해 화면에 남길 카드를 고른다."""
        per_theme, out = {}, []
        for c in items:
            n = per_theme.get(c["theme"], 0)
            if n >= MAX_PER_THEME:
                continue
            per_theme[c["theme"]] = n + 1
            out.append(c)
            if len(out) >= limit:
                break
        return out

    def enrich_selected(items: list) -> None:
        """고른 카드의 대표 기사 원문(시각·본문 리드·분류)을 보강한다. 총 ARTICLE_LIMIT건까지."""
        budget = ARTICLE_LIMIT - len(enriched_ids)
        todo = [c for c in items if c["id"] not in enriched_ids][:max(0, budget)]
        if not todo:
            return
        targets = []
        for c in todo:
            enriched_ids.add(c["id"])
            t = {"id": c["id"], "url": c["url"], "lede": c.get("_lede") or "", "time": c.get("time", "")}
            if c.get("source") == "main":
                t["source"] = "main"
            targets.append((c, t))
        with ThreadPoolExecutor(max_workers=ARTICLE_FETCH_WORKERS) as pool:
            list(pool.map(lambda p: enrich(p[1]), targets))
        for c, t in targets:
            if t.get("time"):
                c["time"] = t["time"]
            c["summary"] = make_summary(t.get("lede") or t.get("body_lead") or c.get("_lede") or "")
            c["leaders"] = leaders_for(c["title"] + " " + c["summary"], c["theme"],
                                       named_text=c["title"] + " " + " ".join(c["tags"]))
            c["_naver_section"] = t.get("naver_section")
            c["_naver_service"] = t.get("naver_service")

    enrich_selected(pick_limited(cards))

    # 연예·가십·개인사 카드는 이슈 순위에서 빼고(요약까지 본 뒤), 속보 배지를 정확한 시각으로 다시 판단
    kept_cards, gossip_dropped = [], []
    for c in cards:
        if is_gossip_card(c):
            gossip_dropped.append(c["title"])
            continue
        if not c.get("summary"):
            c["summary"] = make_summary(c.get("_lede") or "")
            c["leaders"] = leaders_for(c["title"] + " " + c["summary"], c["theme"],
                                       named_text=c["title"] + " " + " ".join(c["tags"]))
        c["breaking"] = _card_breaking(c, now)
        kept_cards.append(c)
    cards = kept_cards
    if gossip_dropped:
        print(f"[info] gossip dropped: {len(gossip_dropped)} → {gossip_dropped[:2]}", file=sys.stderr)

    # 시각 보강·가십 제외 뒤 순서를 다시 잡고, 테마 상한과 카드 수 상한을 적용한다
    for c in cards:                 # 요약까지 붙은 뒤 테마 DB 연결을 다시 잰다
        attach_link(c)
    cards.sort(key=order)
    cards = pick_limited(cards)

    # 원문을 못 받아 요약이 빈 카드는 남은 원문 조회 예산 안에서 한 번 더 보강한다
    need = [c for c in cards if not c.get("summary")]
    if need:
        enrich_selected(need)
        for c in need:
            c["breaking"] = _card_breaking(c, now)
        cards.sort(key=order)

    for i, c in enumerate(cards):
        c["issue_rank"] = i + 1
        c["db_themes"] = (c.get("_link") or {}).get("themes") or []
        c.pop("_members", None)
        c.pop("_lede", None)
        c.pop("_link", None)
    print(f"[info] issues: {len(cards)} cards (max {limit})", file=sys.stderr)
    return cards


# --------------------------------------------------------------------------- 오늘 상한가
# 네이버 증권 '실시간 랭킹(상승 정렬)' API에서 현재가가 상한가 가격에 있는 종목만 골라 오늘의 상한가 목록을 만든다.
# 종목마다 네이버 종목 뉴스와 구글 뉴스 검색에서 당일 보도를 찾아 '왜 상한가였는지' 이슈 요약·대표 기사·테마 키워드를 붙인다.
# 공개 시장 데이터와 공개 기사만 쓰고, 개인 DB·매매 룰은 쓰지 않는다.
UPPER_RANK_API = ("https://stock.naver.com/api/domestic/market/stock/default"
                  "?tradeType=KRX&marketType={market}&orderType=up&startIdx=0&pageSize=100")
UPPER_MARKETS = (("KOSPI", "코스피"), ("KOSDAQ", "코스닥"))
UPPER_STATUS_API = "https://stock.naver.com/api/stockSecurity/exchanges/market-status?exchanges=krx"
UPPER_REFERER = "https://stock.naver.com/market/stock/kr/stocklist/upper"
STOCK_NEWS_API = "https://m.stock.naver.com/api/news/stock/{code}?pageSize=30&page=1"
STOCK_NEWS_REFERER = "https://m.stock.naver.com/"
GOOGLE_RSS_API = "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
UPPER_WORKERS = 6           # 종목별 뉴스 조회 동시 요청 수
UPPER_MIN_RATE = 15.0       # 상한가는 가격대에 따라 29% 안팎 — 이보다 낮으면 상한가로 보지 않는다

# 상한가 종목의 이슈를 한 단어 테마로 붙이기 위한 공개 키워드 사전.
# 기사 제목·도입부에 실제로 나온 단어만 근거로 쓰고, 없으면 테마를 비워 둔다(추정 금지).
UPPER_THEME_HINTS = (
    ("엔터·K콘텐츠", ("한한령", "엔터", "K팝", "케이팝", "드라마", "콘텐츠", "방송", "연예", "아이돌")),
    ("로봇·휴머노이드", ("휴머노이드", "로봇", "로보틱스", "피지컬 AI", "자율주행")),
    ("바이오·임상", ("임상", "치매", "신약", "항암", "바이오", "FDA", "품목허가", "기술수출")),
    ("스마트팜·농업", ("스마트팜", "농업", "온실", "농식품", "원예")),
    ("게임", ("게임", "신작", "퍼블리싱")),
    ("반도체·장비", ("반도체", "HBM", "D램", "파운드리", "웨이퍼", "노광", "장비")),
    ("2차전지·배터리", ("2차전지", "배터리", "양극재", "음극재", "전고체")),
    ("원전·전력", ("원전", "SMR", "전력", "송전", "태양광", "풍력")),
    ("방산·조선", ("방산", "국방", "함정", "조선")),
    ("화장품·뷰티", ("화장품", "뷰티")),
    ("여행·유통", ("여행", "호텔", "면세", "카지노", "유통")),
    ("AI·데이터센터", ("데이터센터", "클라우드", "GPU", "인공지능", "AI")),
    ("상장 유지·관리종목", ("상장폐지", "상폐", "관리종목", "시총 미달", "퇴출", "유예")),
    ("유상증자·공모", ("유상증자", "공모", "청약", "전환사채", "CB")),
    ("정책·규제", ("정책", "규제", "법안", "국회", "정부 지원")),
)


def _won(n) -> str:
    """거래대금을 폰 화면에 짧게 (예: 1조234억 → '1.2조', 7,223억)."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    if n >= 1_000_000_000_000:
        v = n / 1_000_000_000_000
        return (f"{v:.1f}".rstrip("0").rstrip(".")) + "조"
    if n >= 100_000_000:
        return f"{round(n / 100_000_000):,}억"
    if n >= 10_000:
        return f"{round(n / 10_000):,}만"
    return f"{n:,}"


def _prev_weekday(d):
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def upper_market_status(now: datetime) -> dict:
    """네이버 증권 시장 상태 API에서 '이 상한가 목록이 어느 날짜 기준인지'를 확인한다."""
    info = {"base_date": now.date().isoformat(), "session": "", "is_today": True,
            "trading_day": True, "from_api": False}
    try:
        data = fetch_json(UPPER_STATUS_API, referer=UPPER_REFERER, timeout=12)
        for ex in (data or {}).get("exchanges", []):
            if str(ex.get("exchange", "")).lower() != "krx":
                continue
            for st in ex.get("statuses", []):
                if st.get("marketType") not in ("KOSPI", "KOSDAQ"):
                    continue
                latest = st.get("latest") or {}
                today = st.get("today") or {}
                base = str(latest.get("tradeBaseAt") or today.get("date") or "")
                if base:
                    info["base_date"] = base
                info["session"] = str((latest.get("session") or {}).get("displayLabel") or "")
                info["trading_day"] = bool(today.get("isTradingDay", True))
                info["is_today"] = (info["base_date"] == now.date().isoformat())
                info["from_api"] = True
                break
            if info["from_api"]:
                break
    except Exception as e:  # noqa: BLE001
        print(f"[warn] upper market status: {e}", file=sys.stderr)
    if not info["from_api"]:
        # 상태 API가 막히면 시각으로만 보정한다(장 시작 전이면 직전 평일 기준).
        if now.hour < 9:
            info["base_date"] = _prev_weekday(now.date()).isoformat()
        info["is_today"] = (info["base_date"] == now.date().isoformat())
    return info


def arrival_window(now: datetime, base_date: str) -> tuple[bool, str]:
    """상한가 도달 시각을 1분봉으로 잴 수 있는 때인지 (2026-11-26 지시).

    장중(평달 09:00~15:30)에는 긁지 않는다 — 상한가에 닿은 분이 장 끝까지 바뀔 수 있기 때문이다.
    장 마감 뒤·휴장일·직전 거래일 자료일 때만 조회하고 그 값을 확정으로 본다.
    """
    try:
        bd = datetime.strptime(str(base_date), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return True, "기준일 미상 — 조회"
    if bd != now.date():
        return True, "직전 거래일 — 마감 뒤 확정"
    if now.weekday() >= 5:
        return True, "휴장일 — 확정"
    mins = now.hour * 60 + now.minute
    if mins < 9 * 60:
        return True, "장 시작 전 — 직전 마감 확정"
    if mins < 15 * 60 + 30:
        return False, "장중 — 15:30 마감 후 확정"
    return True, "장 마감 후 확정"


def fetch_upper_stocks() -> list:
    """코스피·코스닥 상승 정렬 상위에서 '현재가 = 상한가'인 종목만 남긴다."""
    rows, seen = [], set()
    for market, label in UPPER_MARKETS:
        try:
            data = fetch_json(UPPER_RANK_API.format(market=market), referer=UPPER_REFERER, timeout=15)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] upper rank {market}: {e}", file=sys.stderr)
            continue
        if not isinstance(data, list):
            continue
        for x in data:
            if str(x.get("type") or "ST") == "DR":
                continue
            code = str(x.get("itemcode") or "")
            try:
                price = int(str(x.get("nowPrice") or "0").replace(",", ""))
                limit = int(str(x.get("upperLimitPrice") or "0").replace(",", ""))
                rate = float(str(x.get("prevChangeRate") or "0").replace(",", ""))
            except ValueError:
                continue
            if not price or not limit or price != limit or rate < UPPER_MIN_RATE:
                continue
            if code in seen:
                continue
            seen.add(code)
            try:
                value = int(float(str(x.get("tradeAmount") or "0").replace(",", "")))
                volume = int(float(str(x.get("tradeVolume") or "0").replace(",", "")))
            except ValueError:
                value, volume = 0, 0
            rows.append({
                "name": str(x.get("itemname") or "").strip(),
                "code": code,
                "market": "코넥스" if code.startswith("900") else label,
                "price": price,
                "change_rate": round(rate, 2),
                "trading_value": value,
                "volume": volume,
                "session": str(x.get("tradingSessionType") or ""),
                # 불건전 기업 판별용 — 네이버 랭킹 API 가 종목마다 실어 주는 공식 필드
                # (upper_rank.screen 이 관리종목·거래정지·시장경보·DR·우선주·SPAC·자본잠식 검사)
                "type": str(x.get("type") or "ST"),
                "assets": x.get("propertyTotal"),
                "debt": x.get("debtTotal"),
                "market_sum": x.get("marketSum"),
                "continual_upper": x.get("continualUpperLimit"),
                "accum_upper": x.get("accumUpper"),
                "listed_date": x.get("listedDate"),
                "status": {
                    "manageStatusGb": str(x.get("manageStatusGb") or "0"),
                    "managementReasonCode": x.get("managementReasonCode"),
                    "tradeStopYn": str(x.get("tradeStopYn") or "N"),
                    "tradableStatus": str(x.get("tradableStatus") or ""),
                    "marketAlertType": str(x.get("marketAlertType") or "00"),
                    "tradingHaltReasonCode": x.get("tradingHaltReasonCode"),
                },
            })
    rows.sort(key=lambda r: -r["trading_value"])
    return [r for r in rows if r["name"]]


def naver_stock_news(code: str) -> list:
    """네이버 증권 종목 뉴스(제목 + 도입부)."""
    out = []
    try:
        blocks = fetch_json(STOCK_NEWS_API.format(code=code), referer=STOCK_NEWS_REFERER, timeout=12)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] stock news {code}: {e}", file=sys.stderr)
        return out
    for b in blocks or []:
        for it in (b or {}).get("items") or []:
            try:
                dt = datetime.strptime(str(it.get("datetime") or ""), "%Y%m%d%H%M").replace(tzinfo=KST)
            except ValueError:
                continue
            out.append({
                "source": "naver",
                "title": html_lib.unescape(str(it.get("titleFull") or it.get("title") or "")).strip(),
                "body": html_lib.unescape(str(it.get("body") or "")).strip(),
                "press": str(it.get("officeName") or "").strip(),
                "dt": dt,
                "url": str(it.get("mobileNewsUrl") or ""),
            })
    return out


def google_news_rss(query: str, when: str = "3d") -> list:
    """구글 뉴스 RSS — 네이버 종목 뉴스에 없는 당일 보도를 보완한다."""
    url = GOOGLE_RSS_API.format(q=urllib.parse.quote(f"{query} when:{when}"))
    try:
        xml = fetch(url, timeout=15)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] google rss '{query}': {e}", file=sys.stderr)
        return []
    out = []
    for raw in re.findall(r"<item>(.*?)</item>", xml, re.S):
        t = re.search(r"<title>(.*?)</title>", raw, re.S)
        link = re.search(r"<link>(.*?)</link>", raw, re.S)
        pub = re.search(r"<pubDate>(.*?)</pubDate>", raw, re.S)
        src = re.search(r'<source url="[^"]*">([^<]*)</source>', raw, re.S)
        desc = re.search(r'<description>(.*?)</description>', raw, re.S)
        press_font = re.search(r'color="#6f6f6f">([^<]*)</font>', html_lib.unescape(desc.group(1)) if desc else "")
        if not (t and link and pub):
            continue
        try:
            dt = parsedate_to_datetime(pub.group(1)).astimezone(KST)
        except (TypeError, ValueError):
            continue
        title = html_lib.unescape(t.group(1)).strip()
        press = html_lib.unescape(src.group(1)).strip() if src else ""
        if not press and press_font:
            press = press_font.group(1).strip()
        if re.match(r"^https?://", press):   # 매체명 자리에 주소만 온 경우는 매체로 쓰지 않는다
            press = ""
        if " - " in title:   # 구글 RSS 제목은 '기사 제목 - 매체'
            head, tail = title.rsplit(" - ", 1)
            if not press or tail.strip() == press:
                title = head.strip()
        out.append({"source": "google", "title": title, "body": "", "press": press,
                    "dt": dt, "url": html_lib.unescape(link.group(1)).strip()})
    return out


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _pick_upper_issue(cands: list, name: str, base_dt: datetime):
    """당일 보도 중 '이 종목'이 제목·도입부에 실제로 나온 기사를 고른다."""
    nn = _norm_name(name)
    if not nn:
        return None
    scored = []
    for c in cands:
        if not c.get("dt") or c["dt"] < base_dt:
            continue
        title = c.get("title") or ""
        body = c.get("body") or ""
        in_title = nn in _norm_name(title)
        in_body = nn in _norm_name(body)
        if not (in_title or in_body):   # 종목 이름이 없는 기사는 근거로 쓰지 않는다
            continue
        score = 0
        if in_title:
            score += 6
        if in_body:
            score += 1
        if "상한가" in title:
            score += 8   # 이 화면의 목적은 '왜 상한가인지' — 제목에 상한가가 있는 기사를 먼저 본다
        if any(k in title for k in ("급등", "폭등", "가격제한폭", "上")):
            score += 2
        if "특징주" in title:
            score += 1
        if re.match(r"^\s*\[[^\]]{1,12}\]\s*" + re.escape(name) + r"\s*[,，]", title):
            score += 3   # '[특징주] OO, ...' 처럼 그 종목만 다룬 기사
        if body:
            score += 5   # 도입부(본문)가 있는 기사를 우선 — 이슈 요약이 훨씬 정확해진다
        scored.append((score, c))
    if not scored:
        return None
    scored.sort(key=lambda t: (-t[0], -t[1]["dt"].timestamp()))
    best = scored[0][1]
    best = dict(best)
    best["score"] = scored[0][0]
    return best


def _headline_summary(title: str, name: str) -> str:
    """도입부가 없을 때는 제목에서 군더더기만 덜어 1줄 이슈로 쓴다(내용을 지어내지 않는다)."""
    s = re.sub(r"^\s*\[[^\]]{1,24}\]\s*", "", title or "")      # [특징주] 같은 머리표
    s = re.sub(r"^(?:속보|단독|종합)\s*", "", s)
    s = s.strip(" \"'‘’“”-—·,…")
    if len(s) > 110:
        s = s[:110].rstrip(" ,·-—") + "…"
    return s


def upper_theme(text: str):
    """기사에 실제로 나온 키워드로만 테마를 붙인다."""
    low = (text or "").lower()
    if not low:
        return "", []
    hits = []
    for idx, (label, keywords) in enumerate(UPPER_THEME_HINTS):
        got = [k for k in keywords if k.lower() in low]
        if got:
            hits.append((len(got), idx, label, got))
    if not hits:
        return "", []
    hits.sort(key=lambda t: (-t[0], t[1]))
    return hits[0][2], hits[0][3][:3]


def _pool_candidates(pool: list) -> list:
    """오늘 수집한 뉴스 카드에서 종목 이름이 걸리는 기사를 후보로 바꾼다."""
    out = []
    for c in pool or []:
        for r in [c] + list(c.get("related") or []):
            iso = r.get("time") or ""
            try:
                dt = datetime.fromisoformat(str(iso))
            except ValueError:
                dt = None
            if dt is None:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KST)
            out.append({"source": "pool", "title": str(r.get("title") or ""),
                        "body": str(r.get("summary") or ""), "press": str(r.get("press") or ""),
                        "dt": dt, "url": str(r.get("url") or "")})
    return out


def build_upper_limits(now: datetime, pool: list | None = None, prev_upper: dict | None = None) -> dict:
    """오늘(또는 직전 거래일) 상한가 종목 + 종목별 상한가 이슈 요약."""
    status = upper_market_status(now)
    stocks = fetch_upper_stocks()
    try:
        base_dt = datetime.strptime(status["base_date"], "%Y-%m-%d").replace(tzinfo=KST)
    except (KeyError, ValueError):
        base_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)

    pool_c = _pool_candidates(pool or [])
    arrival_ok, arrival_note = arrival_window(now, status["base_date"])
    prev_upper = prev_upper or {}
    keep_arrival = {}
    if not arrival_ok and prev_upper.get("base_date") == status["base_date"] and prev_upper.get("arrival_final"):
        # 장 마감 뒤에 이미 재 둔 오늘 도달 시각은 그대로 이어 쓴다
        for it in (prev_upper.get("items") or []):
            if it.get("code") and it.get("arrival"):
                keep_arrival[str(it["code"])] = {"arrival": it.get("arrival"),
                                                 "arrival_min": it.get("arrival_min"),
                                                 "arrival_after": it.get("arrival_after") or 0}

    def work(stock):
        cands = naver_stock_news(stock["code"]) + google_news_rss(f'"{stock["name"]}" 상한가', "3d")
        # 불건전 판정용 — 환기종목·감사의견·상폐·횡령·배임·회생·파산·자본잠식 기사를 따로 찾아 둔다
        screen_news = list(cands) + list(pool_c) + google_news_rss(
            f'"{stock["name"]}" (환기종목 OR 감사의견 OR 상장폐지 OR 횡령 OR 배임 OR 회생절차 OR 파산 OR 자본잠식)',
            "1y")
        best = _pick_upper_issue(cands, stock["name"], base_dt)
        if best is None:
            # 상한가 표현이 없는 날에는 종목 이름만으로 한 번 더 찾는다
            extra = google_news_rss(f'"{stock["name"]}"', "2d")
            cands += extra
            screen_news += extra
            best = _pick_upper_issue(cands, stock["name"], base_dt)
        if best is None and pool_c:
            best = _pick_upper_issue(pool_c, stock["name"], base_dt)
        return best, screen_news

    issues, news_of = [], {}
    if stocks:
        with ThreadPoolExecutor(max_workers=UPPER_WORKERS) as ex:
            for stock, (best, screen_news) in zip(stocks, ex.map(work, stocks)):
                issues.append(best)
                news_of[str(stock["code"])] = screen_news

    items = []
    for stock, best in zip(stocks, issues):
        summary, from_where = "", ""
        title = url = press = atime = ""
        if best:
            title = best.get("title") or ""
            url = best.get("url") or ""
            press = best.get("press") or ""
            atime = best["dt"].isoformat() if best.get("dt") else ""
            if best.get("body"):
                summary = make_summary(best["body"], 130)
                from_where = "본문"
            if not summary:
                summary = _headline_summary(title, stock["name"])
                from_where = "제목" if summary else ""
        theme, kws = upper_theme(" ".join([title, summary]))
        items.append({
            **stock,
            "price_text": f"{stock['price']:,}",
            "trading_value_text": _won(stock["trading_value"]),
            "theme": theme,
            "theme_keywords": kws,
            "issue_summary": summary,
            "summary_from": from_where,
            "article_title": title,
            "article_url": url,
            "article_press": press,
            "article_time": atime,
        })

    # 2026-11-26 — (1) 불건전 기업 제외 (2) 테마 묶음·선도주 순위 (3) 125봉 바닥 첫 상한가 (4) 달력 연결
    #   네트워크(분봉·일봉)가 막혀도 상한가 목록 자체는 그대로 내보낸다 — 실패한 종목만 판정을 비운다.
    #   도달 시각은 장중에 긁지 않는다 — 15:30 마감 뒤에만 1분봉으로 확정한다(2026-11-26 지시).
    groups, excluded = [], []
    try:
        cal = upper_rank.load_calendar(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    "..", "data", "calendar.json"))
        flat, groups, excluded, items = upper_rank.rank(items, status["base_date"], cal, pool or [],
                                                        news_by_code=news_of, arrival_ok=arrival_ok,
                                                        keep_arrival=keep_arrival)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] upper rank: {e}", file=sys.stderr)
        flat = items

    base = status["base_date"]
    try:
        bdt = datetime.strptime(base, "%Y-%m-%d")
        base_text = f"{bdt.month}/{bdt.day}"
    except ValueError:
        base_text = base

    if status["is_today"]:
        label = f"오늘 {base_text}"
        note = "" if items else "아직 당일 상한가가 집계되지 않았습니다. 장중에 다시 확인해 주세요."
        if items:
            note = "장중에는 현재 상한가 가격에 있는 종목만 표시됩니다."
    else:
        label = f"직전 거래일 {base_text}"
        why = "휴장일" if not status.get("trading_day") else "장 시작 전"
        note = f"{why}이라 직전 거래일 기준입니다."
        if not items:
            note += " 직전 거래일 상한가 종목은 없었습니다."
    if excluded:
        note = (note + " " if note else "") + f"불건전 종목 {len(excluded)}개(관리종목·우선주·투자경보·뉴스 악재 등)는 순위에서 빠졌습니다."
    if items and not arrival_ok:
        note = (note + " " if note else "") + "상한가 도달 시각은 장 마감(15:30) 뒤 확정됩니다."

    print(f"[info] upper limits: {base} {len(items)} stocks"
          + (f" (제외 {len(excluded)})" if excluded else "") + f" · 도달시각 {arrival_note}", file=sys.stderr)
    return {
        "base_date": base,
        "base_date_text": base_text,
        "label": label,
        "is_today": bool(status["is_today"]),
        "session_label": status.get("session") or "",
        "count": len(items),
        "note": note,
        "arrival_state": "final" if arrival_ok else "pending",
        "arrival_note": arrival_note,
        "arrival_final": bool(arrival_ok),
        "rank_rule": "테마로 묶고 그 안에서 ① 125봉 바닥횡보 뒤 첫 상한가 먼저 ② 오늘 상한가에 먼저 닿은 순",
        "items": items,
        "themes": groups,
        "excluded": excluded,
    }


# --------------------------------------------------------------------------- 전광판(시장 분위기)
# 헤더의 🇰🇷·🇺🇸 호재/혼조/악재는 기사 제목 단어가 아니라 **실제 지수 등락률**로 판정한다.
#   한국(kr): 코스피·코스닥 둘 다 하락이면 악재, 둘 다 상승이면 호재,
#             방향이 엇갈리면 평균 -0.6% 이하 악재 / +0.6% 이상 호재 / 그 사이 혼조.
#             (지수가 마이너스인데 뉴스 때문에 호재로 뒤집히지 않는다)
#   미국(us): 나스닥·S&P500·다우 평균 +0.5% 이상 호재, -0.5% 이하 악재,
#             그 사이이거나 방향이 엇갈리면 혼조.
# 장 시작 전처럼 오늘 등락률이 아직 0인 때는 live=false 로 보내 화면이 뉴스 분위기로 보조하게 한다.
KR_INDICES = (("KOSPI", "kospi", "코스피", "https://m.stock.naver.com/api/index/KOSPI/basic"),
              ("KOSDAQ", "kosdaq", "코스닥", "https://m.stock.naver.com/api/index/KOSDAQ/basic"))
US_INDICES = ((".IXIC", "nasdaq", "나스닥", "https://api.stock.naver.com/index/.IXIC/basic"),
              (".INX", "sp500", "S&P500", "https://api.stock.naver.com/index/.INX/basic"),
              (".DJI", "dow", "다우", "https://api.stock.naver.com/index/.DJI/basic"))
INDEX_REFERER = "https://m.stock.naver.com/"


def _num(s):
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _kst_hm(iso) -> str:
    """지수 응답의 localTradedAt(현지 시각)을 한국 시각 'MM-DD HH:MM'으로 바꾼다."""
    try:
        dt = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST).strftime("%m-%d %H:%M")


def fetch_index(code: str, field: str, name: str, url: str):
    """네이버 지수 API 한 곳에서 현재가·등락률·장 상태를 읽는다 (실패하면 None)."""
    try:
        d = fetch_json(url, referer=INDEX_REFERER, timeout=10, retries=2)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] index {code}: {e}", file=sys.stderr)
        return None
    chg = _num(d.get("fluctuationsRatio"))
    if chg is None:
        print(f"[warn] index {code}: no fluctuationsRatio", file=sys.stderr)
        return None
    return {"code": code, "field": field, "name": name, "value": _num(d.get("closePrice")),
            "chg": round(chg, 2), "status": (d.get("marketStatus") or "").upper() or None,
            "as_of": d.get("localTradedAt"), "as_of_kst": _kst_hm(d.get("localTradedAt"))}


def _rows_text(rows) -> str:
    return " · ".join(f"{r['name']} {r['chg']:+.2f}%" for r in rows)


def _mood_out(rows, key: str, label: str, why: str, avg: float, live: bool) -> dict:
    newest = max(rows, key=lambda r: str(r.get("as_of") or ""))
    out = {"key": key, "label": label, "why": why, "avg": round(avg, 2), "live": live,
           "as_of_kst": newest.get("as_of_kst") or ""}
    for r in rows:
        out[r["field"]] = {"name": r["name"], "value": r.get("value"), "chg": r["chg"],
                           "status": r.get("status"), "as_of": r.get("as_of")}
    return out


def judge_kr_mood(rows) -> dict | None:
    if not rows:
        return None
    chgs = [r["chg"] for r in rows]
    avg = sum(chgs) / len(chgs)
    if all(c < 0 for c in chgs):
        key, label = "bad", "악재"
    elif all(c > 0 for c in chgs):
        key, label = "good", "호재"
    elif avg <= -0.6:
        key, label = "bad", "악재"
    elif avg >= 0.6:
        key, label = "good", "호재"
    else:
        key, label = "mid", "혼조"
    live = any(abs(c) >= 0.005 for c in chgs)  # 오늘 등락이 아직 0이면(장 시작 전) 화면이 뉴스로 보조
    return _mood_out(rows, key, label, f"{_rows_text(rows)} (평균 {avg:+.2f}%)", avg, live)


def judge_us_mood(rows) -> dict | None:
    if not rows:
        return None
    chgs = [r["chg"] for r in rows]
    avg = sum(chgs) / len(chgs)
    mixed = any(c > 0 for c in chgs) and any(c < 0 for c in chgs)
    if mixed:
        key, label = "mid", "혼조"
    elif avg >= 0.5:
        key, label = "good", "호재"
    elif avg <= -0.5:
        key, label = "bad", "악재"
    else:
        key, label = "mid", "혼조"
    live = any(abs(c) >= 0.005 for c in chgs)
    return _mood_out(rows, key, label, f"{_rows_text(rows)} (평균 {avg:+.2f}%)", avg, live)


def build_market_mood(now: datetime) -> dict:
    """코스피·코스닥 / 나스닥·S&P500·다우 실제 등락률로 전광판 판정을 만든다."""
    kr_rows = [r for r in (fetch_index(*x) for x in KR_INDICES) if r]
    us_rows = [r for r in (fetch_index(*x) for x in US_INDICES) if r]
    kr = judge_kr_mood(kr_rows)
    us = judge_us_mood(us_rows)
    if kr:
        print(f"[info] market mood KR={kr['label']} ({kr['why']})", file=sys.stderr)
    else:
        print("[warn] market mood KR: 지수 조회 실패 — 화면은 뉴스 분위기로 대체", file=sys.stderr)
    if us:
        print(f"[info] market mood US={us['label']} ({us['why']}, {us['as_of_kst']} 기준)", file=sys.stderr)
    return {"generated_at": now.isoformat(), "kr": kr, "us": us}


# --------------------------------------------------------------------------- 메인
def build(out_path: str):
    now = datetime.now(KST)
    print(f"[info] settings: ARTICLE_LIMIT={ARTICLE_LIMIT} ARTICLE_FETCH_WORKERS={ARTICLE_FETCH_WORKERS} "
          f"MAX_ARTICLES={MAX_ARTICLES} SECTION_DELAY={SECTION_DELAY}s ARTICLE_DELAY={ARTICLE_DELAY}s",
          file=sys.stderr)
    raw = []
    for sid, name, weight in SECTIONS:
        raw.extend(parse_section(sid, name, weight))
    section_count = len(raw)
    for sid, name, weight in CIVIC_SECTIONS:
        got = parse_section(sid, name, weight)
        for a in got:
            a["source"] = "civic"
        raw.extend(got)
    civic_count = sum(1 for a in raw if a.get("source") == "civic")
    ytn_items = collect_ytn(now)
    raw.extend(ytn_items)
    main_items = parse_main_ranking(now)
    raw.extend(main_items)

    # 기사 id 기준 병합 (같은 기사가 경제 섹션과 메인 랭킹에 동시에 오를 수 있다)
    merged = {}
    for a in raw:
        cur = merged.get(a["id"])
        if cur is None:
            merged[a["id"]] = a
            continue
        if a["weight"] > cur["weight"]:
            cur["weight"] = a["weight"]
            cur["section"] = a["section"]
        if a.get("source") == "main":
            cur["source"] = "main"
            cur["main_rank"] = a.get("main_rank")
            cur["press_id"] = a.get("press_id", "")
        if len(a.get("lede", "")) > len(cur.get("lede", "")):
            cur["lede"] = a["lede"]
        if not cur.get("press"):
            cur["press"] = a.get("press", "")

    # 1차 분류·필터 (목록의 리드만으로 충분)
    candidates, main_dropped = [], 0
    for a in merged.values():
        if any(w in a["title"] for w in ("매매 상위 종목", "상위 종목", "주요 공시")):
            continue
        if a.get("source") == "main":
            if not is_main_relevant(a):
                main_dropped += 1
                continue
        elif a.get("source") in ("civic", "press"):
            if not is_issue_relevant(a):
                continue
        elif not is_market_relevant(a):
            continue
        tid, tags, rel = classify(a)
        head = a["title"] + " " + a.get("lede", "")
        if (tid == "etc" and rel < MIN_RELEVANCE and not any(t in head for t in MARKET_TERMS)
                and a.get("source") not in ("civic", "press")):
            continue
        a["theme"] = tid
        a["theme_label"] = THEME_LABEL.get(tid, "기타")
        a["tags"] = [t for t in (tags or []) if t != a["title"]][:3]
        a["relevance"] = rel
        candidates.append(a)

    if len(candidates) < 12:
        print("[warn] not enough naver items, using google fallback", file=sys.stderr)
        for g in collect_google_news():
            tid, tags, rel = classify(g)
            g.update(theme=tid, theme_label=THEME_LABEL.get(tid, "기타"), tags=tags[:3],
                     relevance=rel)
            candidates.append(g)

    issues = build_issues(candidates, now)
    kept = issues[:MAX_ARTICLES]
    flash = collect_flash_news(now, extra=candidates, popular=main_items)

    history = update_history(load_history(out_path), kept, now)
    # 테마별 이슈 수
    counts = {}
    for a in kept:
        counts[a["theme"]] = counts.get(a["theme"], 0) + 1
    order = [t[0] for t in THEMES]
    themes = [{"id": tid, "label": THEME_LABEL[tid], "color": THEME_COLOR[tid], "count": counts.get(tid, 0)}
              for tid in order if counts.get(tid)]
    themes.sort(key=lambda t: -t["count"])
    etc = counts.get("etc")
    if etc:
        themes.append({"id": "etc", "label": "기타", "color": "#9aa4b2", "count": etc})

    # 오늘 상한가 — 종목별 당일 보도를 오늘 수집한 뉴스 카드에서도 한 번 더 찾는다
    #   지난 실행의 상한가(장 마감 뒤 잰 도달 시각)를 이어 쓰려고 먼저 읽어 든다
    prev_upper = {}
    try:
        with open(out_path, encoding="utf-8") as f:
            prev_upper = (json.load(f) or {}).get("upper_limits") or {}
    except Exception:  # noqa: BLE001
        prev_upper = {}
    upper_limits = build_upper_limits(now, kept, prev_upper)

    # 헤더 전광판 — 실제 지수 등락률 (실패해도 news.json 생성은 계속)
    market_mood = build_market_mood(now)

    payload = {
        "generated_at": now.isoformat(),
        "generated_at_kst": now.strftime("%Y.%m.%d %H:%M"),
        "flash_count": len(flash),
        "flash_fresh_min": FLASH_FRESH_MIN,
        "flash_fresh_count": sum(1 for f in flash if f.get("fresh")),
        "flash_updated": flash[0]["time"] if flash else None,
        "count": len(kept),
        "article_count": sum(c.get("article_count", 1) for c in kept),
        "main_source": {
            "presses": len({a.get("press") for a in main_items if a.get("press")}),
            "collected": len(main_items),
            "dropped": main_dropped,
            "cards": sum(1 for c in kept if c.get("source") == "main"),
            "sections": section_count,
            "civic": civic_count,
            "ytn": len(ytn_items),
            "civic_cards": sum(1 for c in kept if c.get("source") == "civic"),
        },
        "themes": themes,
        "themes_rank": build_themes_rank(kept, now, history),
        "upper_limits": upper_limits,
        "market_mood": market_mood,
        "history": history,
        "flash": flash,
        "issues": [{k: v for k, v in c.items() if not k.startswith("_")} for c in kept],
        "articles": [{k: c.get(k) for k in ("id", "title", "summary", "press", "time", "url",
                                            "theme", "theme_label", "tags", "section", "relevance",
                                            "source", "leaders", "issue_rank")
                      if c.get(k) is not None} for c in kept],
    }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write("\n")

    # 뉴스 ↔ 테마달력 — 오늘 이슈를 달력의 테마·종목에 이어 붙여 data/news_themes.json 을 새로 쓴다.
    #   (지난 배포본은 진화론 님 패키지에 들어 있던 2026-11-24 자료라 자동으로 갱신되지 않았다)
    try:
        data_dir = os.path.dirname(os.path.abspath(out_path))
        cal = upper_rank.load_calendar(os.path.join(data_dir, "calendar.json"))
        nt = upper_rank.build_news_themes(kept, upper_limits, cal)
        nt_path = os.path.join(data_dir, "news_themes.json")
        old_nt = {}
        try:
            with open(nt_path, encoding="utf-8") as f:
                old_nt = json.load(f)
        except Exception:  # noqa: BLE001
            old_nt = {}
        # 이슈가 하나도 안 걸렸으면(휴장·수집 실패) 지난 목록을 지우지 않는다
        if nt["news_links"] or not (old_nt.get("news_links")):
            upper_rank.write_json(nt_path, nt)
        else:
            nt = old_nt
        print(f"[done] news↔달력 테마 {len(nt.get('news_links') or [])}건 -> {nt_path}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] news_themes: {e}", file=sys.stderr)
    print(f"[done] flash {len(flash)} / {len(kept)} issues / {payload['article_count']} articles -> {out_path}",
          file=sys.stderr)
    return payload


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/news.json")
    args = ap.parse_args()
    build(args.out)
