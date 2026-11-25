#!/usr/bin/env python3
"""핫바 레이더 생성기 — 일봉 1·2·3 / 주봉(48주 거래량) 1·2·3 / 월봉(12월 거래량) 1·2·3.

결과: projects/stock-news-radar/data/hotbar.json   (사이트의 비밀 '핫바' 탭이 읽는다)
      projects/stock-news-radar/data/radar.json     (비공개 '레이더' — 종목 순서·정리만 손댄다. 잠근 파일)

⚠ hotbar.json 은 공개 저장소에 올라가므로 **AES-256-GCM(PBKDF2-SHA256 10만회)으로 잠근다** —
  파일에는 {"enc":1,"salt":..,"iv":..,"ct":..} 만 남고 종목·숫자는 보이지 않는다.
  비밀코드는 이 스크립트(공개 저장소에 올리지 않는다)와 푸른하늘님 기기에만 있다.
  다른 코드로 잠그려면: HOTBAR_PW=새코드 python3 scripts/build_hotbar_radar.py
  차트용 봉(일봉 1·2·3·4 45봉 안팎 · 주봉 52봉 · 월봉 30개월)과 기준선·기준 거래량도 함께 싣는다.

일봉(2026-11-19 개편):
  실제 상한가(전일 종가 대비 +28.5% 이상, 또는 고가=종가로 계산상 상한가의 95% 이상)가
  최근 1달(캘린더 30일 ≈ 20~22거래일) 안에 나온 종목만 잡고, 첫 상한가(그 앞 60거래일 무상한가)
  → 눌림 → 첫 반등을 하루씩 따라간다. 한 달이 지난 상한가 자리는 싣지 않고, 그 자리에
  종목이 없으면 억지로 채우지 않고 비워 둔다. 눌림 폭은 종목 위치·성격에 따라 다르므로 %로
  자르지 않고, 상한가 봉 시가를 종가로 다 토해내면(그림 붕괴) 뺀다. 고점 대비 위치(dd)와
  바닥권(1년 고점 -45% 이하) 표시를 함께 싣고, 바닥권을 앞에 정렬한다.
  일봉은 앞·중·뒤 자리를 모두 싣는다(배지로 구분).

테마·재료 판정(2026-11-19 밤 푸른하늘님 지시 → 같은 날 정정 "테마 섹터 개별이라도 넣어야지"):
  **일봉·주봉·월봉 모두** material_ok() 를 통과한 종목만 싣는다.
    · 테마 DB·달력·오늘 상한가 뉴스에 테마(섹터)가 있으면 싣는다 — 테마 이름이 '개별 …'
      묶음(예: '개별 수주·실적 서프라이즈', '3분기 실적 서프라이즈·수주 (개별 실적주)')이어도 싣는다.
    · 테마가 없어도 확인된 개별 재료(단독 뉴스·수주·실적·공시)의 reason 이 있으면 싣는다.
    · 테마도 없고 reason 도 '재료 미확인'인 **진짜 무재료 종목만** 뺀다. 뺀 종목은 로그에 찍힌다.
  카드 오른쪽 글자는 theme_label() — 테마가 확실하면 짧은 테마명, 개별이면 '개별 · 수주'처럼
  그 종목의 섹터나 재료 키워드를 붙인다(키워드를 못 찾으면 '개별'). 정렬은 테마 확실 종목 먼저,
  개별은 맨 아래.

일봉 4번(2026-11-19 추가, 비밀 핫바에만):
  3번(첫 반등 양봉)이 그저께 이전에 이미 나온 종목은 그 뒤 어떻게 눌리고 진행 중인지
  4번으로 따로 싣는다 — 첫 상한가 날짜·3번 날짜·3번 뒤 경과일·3번 고가 대비 현재가(dd3)와
  상한가 봉 시가(기준선) 대비 위치를 실물 숫자로 담는다. 주봉·월봉은 1·2·3 그대로다.
  일봉 섹션의 단계 순서는 4 → 1 → 2 → 3 (사용자 지시, 2026-11-19).
  4번 카드에는 일봉 차트 팝업용 candles([날짜,시,고,저,종,거래량] 35~55봉)와 lu_date(1번 첫
  상한가 날)·base_open(그 봉 시가=기준선)도 함께 싣는다. 1·2·3번 카드에는 넣지 않는다.

  ※ 2026-11-21 푸른하늘님 지시로 기준선을 바로잡았다 — 기준선은 가격(1번 시가)이 아니라
    **그림 기준선**이다: ① 상한가 → ② 하락 음봉(눌림) → ③ 반등 양봉이 실제로 나온 뒤에야
    ② 저점에 가로선을 긋고, ④ 그 선까지 다시 내려올 때 사는 자리로 본다. ③이 아직 없으면
    선을 미리 긋지 않고 '3번 대기'로 둔다. 차트에 그리는 자리는 base_open = ② 저점.

주봉·월봉(2026-11-19 밤 개편 — 푸른하늘님 지시):
  · 테마·재료 있는 종목만(theme_db·달력 테마, '개별' 제외)
  · 시작 거래량: 바닥에서 거래량이 최소 6개월(주봉 26주·월봉 6개월) 조용히 누운 뒤
    그 6개월 최대 거래량보다 **뚜렷하게(2배 이상)** 터진 **뚜렷한 양봉**(도지·몸통 없는 봉 제외).
    직전 종가가 1년 고점의 60% 이하(-40% 이상) = 바닥권.
    여러 개면 **가장 앞선(이른) 시작 거래량**에 세운다 — 고점 뒤 반짝이 아니라 출발 자리.
    2026-11-20 정리: "+1%·+0%" 같은 약한 봉, 6개월 최대의 1.0~1.8배짜리 어중간한 봉, 도지가
    1번 칸에 섞이던 것을 걷어냈다(푸른하늘님 사진 3장 = 자이언트스텝 13.5배·진에어 4.6배·
    아시아나IDT 50.9배, 모두 긴 하락 뒤 바닥 횡보 → 이전 6개월을 압도하는 큰 빨간 양봉).
  · 1번 = 시작 거래량 봉(이번/지난 주·달) · 2번 = 그 뒤 눌림(이 봉의 저점이 '줄')
    · 3번 = 눌림 뒤 거래량 실린 첫 양봉 · 4번 = 3번 뒤 다시 **2번 눌림 저점(기준선)** +5% 안까지
    내려온 재확인 사는 자리(2026-11-21 기준선 바로잡음 — 1번 시가가 아니다).
    기준선을 -3% 아래로 깨면 그림 깨짐으로 싣지 않고, 아직 줄 근처로 안 내려온 3번 진행은 4번으로 올리지 않는다.
  · 앞/뒤(2026-11-19 22:5x 정정): **뒤쪽을 빼지 않고 표시만 한다.**
      앞쪽 = 20일선 ≥ 60일선(역배열 아님) + 장기 이평선(주봉 240선·월봉 120선) 아래
      뒤쪽 = 장기 이평선 위이거나 20일선 < 60일선(데드크로스, 보통 -60% 이상 빠진 자리)
    장기선은 10년 일봉 원본(brain/cache/hotbar_parts)까지 붙여 잰다 — 450봉 캐시로는 못 잰다.
    봉이 모자라 장기선을 못 그리는 종목은 long_bars·long_need 에 남기고 20/60선만으로 판정한다.
  · 기준선(그림 기준선 = ② 눌림 저점): **③ 반등 양봉이 나온 종목만** 긋는다(2026-11-21 지시).
    3번이 없는 동안에는 선을 긋지 않고 '3번 대기'로 두며, 3번 뒤에도 선은 그대로 둔다(4번을 재는 자).

앞/뒤 구분(2026-11-19 전수조사 brain/chart_1234_bottom_study.md §1·§5 그대로):
  vr_all = 봉 거래량 ÷ 10년(2015-06~) 전체 최대 봉 거래량 (같은 봉끼리 — 일은 일, 주는 주, 월은 월)
  앞 = 0.90 이상(역대 최고 수준) · 중 = 0.50~0.90 · 뒤 = 0.50 미만(과거 대시세 뒤 반짝)
  주봉·월봉은 '앞'만 싣는다(2026-11-19 02:03 지시 "앞쪽만 보면 되요"). '뒤'는 싣지 않고,
  그 단계에 '앞'이 하나도 없을 때만 '중'을 대신 싣는다.
  일봉 카드의 앞/중/뒤는 **일봉 거래량으로 재지 않는다**(작은 봉이라 늘 '뒤'가 된다 — 2026-11-19
  07:38 지시). 그 상한가 봉이 속한 **주봉·월봉 봉 거래량 ÷ 그 앞 10년 주·월봉 최대** 로 재서
  주봉·월봉 중 큰 쪽으로 판정하고, 어느 봉으로 쟀는지(pos_src·vr_week·vr_month)를 함께 싣는다.

재료: 오늘 상한가 기사 요약 → 네이버 종목뉴스 최근 기사(scripts/fetch_stock_reasons.py 캐시)
      → 테마 DB 이슈요약 → 테마 이름 → '재료 미확인'.

A++ (2026-11-19 지시 — 자동 판정 없음):
  코드는 A++를 스스로 판정하지 않는다(예전 규칙이 형지엘리트·컨텍 등에 자동으로 붙였다).
  뉴스로 살아있는 재료를 확인하고 실물 차트에서 며칠 뒤 오를 만큼 이쁜 1·2·3·4 자리인지
  눈으로 검수한 종목만 brain/hotbar_a_plus.json 에 손으로 적는다:
      {"093240": "형지그룹 상폐 유예 — 살아있는 재료 + 이쁜 4번 자리"}
  빈 {} 이면 배지 없음(A++ 0). 도장을 찍거나 지운 뒤에는 이 스크립트를 한 번 더 돌린다.

상위 버전(2026-11-20 푸른하늘님 지시 "상위버전이 좋으면 업댓하자 · 빼걸 빼고 널 집어넣자"):
  · 480봉 0~100 눈금 — 지금 종가가 최근 480봉(모자라면 있는 만큼) 최저~최고 사이 어디인지.
    카드에 '480봉 24/100' 처럼 붙고, 35 아래=아래쪽 / 35~70=가운데 / 70 위=위쪽으로 색을 나눈다
    (brain/front_back_window_study.md §3·§11: 눈금은 앞/뒤 도장이 아니라 위치 자 — 도장은 10년 거래량 그대로).
  · 주봉 240선 하단 선 뭉침 — 240주 창에서 5·10·20·60·120주 선 간격 20% 안 + 선 무리가 창 하단 35% 안
    + 주가가 선 무리 ±40% 안 + 그 주 거래량이 240주 최대의 90% 이상이면 '선뭉침'(초록).
    선은 뭉쳤는데 거래량이 아직 모자라면 '선뭉침·불씨전'(노랑). 잰 숫자(간격·하단·거래량 배수)는 차트에.
  · 주봉·월봉 5번 이후 — 일봉처럼 4번 뒤 고점·저점을 번갈아 5·6·7…12번까지 이어 센다(2번 기준선은 3번 뒤에도 둔다).
  · 진화 점수판 — brain/evolution_scorecard.md 맨 앞줄(누적 적중률·목표 99%)과 최근 채점,
    brain/cache/scorecard/predictions.json 의 공식 예상(P1~P8)을 잠긴 자료 안에 함께 넣는다.
    핫바 탭 맨 위에 펼침 상자로 뜨고, hotbar.json 암호화 밖으로는 나가지 않는다.

사용:
  python3 scripts/build_hotbar_radar.py                # 최신 시세 받아 계산 + 배포 JSON 생성
  python3 scripts/build_hotbar_radar.py --no-fetch     # 오늘 받아 둔 시세 캐시로만 계산(빠른 반복)
  python3 scripts/build_hotbar_radar.py --fetch-only   # 시세만 받아 캐시에 저장
  python3 scripts/build_hotbar_radar.py --radar        # 레이더 종목까지 앞쪽만 남기도록 정리(손볼 때만)
  python3 scripts/build_hotbar_radar.py --debug 095610 # 한 종목의 판정 근거를 찍어 본다

10년 기준표(brain/cache/vol_allmax.json)는 2015-06-15~2026-11-17 자료로 한 번 만들어 두고,
매 실행마다 오늘 캐시의 봉을 합쳐 쓴다. 몇 달 지나면 brain/tools/hotbar_fetch.py 로
hotbar_parts 를 새로 받고 build_vol_allmax.py 를 다시 돌려 기준표를 갱신해야 한다.
"""
from __future__ import annotations

import argparse
import base64
import glob
import gzip
import hashlib
import json
import os
import re
import secrets
import shutil
import statistics
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "brain", "tools"))
import pink_arrow as PINK        # noqa: E402  분홍 ↑(후보 G) — 비밀 핫바 일봉 차트에만 쓴다
import pink_export as PINKX      # noqa: E402  오늘 분홍↑ 종목 명단 → brain/cache(공개 저장소 밖)
import stock_risk as RISK        # noqa: E402  재무·공시 위험 플래그 — 18-7(2026-11-24 보완 1번)
import stage10_core as S10       # noqa: E402  10단계 판정 — 16:30 복기·10단계 탭과 같은 함수
# 10단계 생성기의 판정(닻 선택·새 ②③ 그림까지)을 팝업이 그대로 쓰기 위해 모듈을 빌려 온다.
#   실패해도(시세·네트워크 없는 시험) 빌더가 멈추지 않게 None으로 두고 예전 계산으로 물러난다.
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import build_hotbar_buy as B10   # noqa: E402
except Exception:                    # pragma: no cover
    B10 = None
UNIV = os.path.join(ROOT, "brain", "cache", "universe_raw.json")
DELTA_DIR = os.path.join(ROOT, "brain", "cache")
ALLMAX = os.path.join(DELTA_DIR, "vol_allmax.json")
OUT = os.path.join(ROOT, "projects", "stock-news-radar", "data", "hotbar.json")
# 오늘 분홍↑ 종목의 평문 명단 — 공개 일봉 125봉 자료(build_day125.py)가 이 종목 봉까지 받게 한다.
#   잠긴 hotbar.json 을 풀지 않고도 알 수 있게, 공개 저장소 밖(brain/cache)에만 적는다.
PINK_TODAY = os.path.join(ROOT, "brain", "cache", "pink_today_hotbar.json")
# 형광↑ 알림 팝업(#cfOv)이 읽는 **오늘 화살 후보 + 등급 재료** — 핫바와 같은 비밀코드로 잠근다.
#   2026-11-24 전수조사(brain/study_pink_pre_vs_post_limitup.md §8) 권고안을 그대로 옮긴 자료.
#   팝업은 잠금이 풀린 본인 화면(visOn())에서만 뜨므로 잠긴 화면에는 이 파일이 풀려 나가지 않는다.
POPUP_OUT = os.path.join(ROOT, "projects", "stock-news-radar", "data", "popup.json")
POPUP_PINK = os.path.join(ROOT, "brain", "cache", "pink_today_popup.json")
# 실전 탭 핫바(일봉·주봉·월봉) 카드에 이름이 뜨는 종목의 평문 코드 명단 — 공개 일봉 125봉 자료
#   (build_day125.py)가 이 종목까지 받게 한다. 이게 없으면 진에어처럼 실전 카드에서만 보이는 종목이
#   공개 125봉 자료에 빠져 그 카드만 일봉 40봉으로 열렸다(2026-11-25 v122 — 모든 종목 일봉 125봉 통일).
HOTBAR_CODES = os.path.join(ROOT, "brain", "cache", "hotbar_codes.json")
POPUP_ADMIN = os.path.join(ROOT, "brain", "cache", "popup_admin")   # 관리종목·정지 확인 결과(하루치 캐시)
# 오늘 픽에 처음 들어온 시각(added_at) — 2026-11-25 지시로 팝업을 없애고 실전 최상단에 세우면서,
#   "30분 단위 추가되면 제일상단 순"의 기준이 된다(공개 저장소 밖 · 잠그지 않는 작은 파일).
PICK_ADDED = os.path.join(ROOT, "brain", "cache", "pick_added.json")
# 10단계 생성기(scripts/build_hotbar_buy.py)가 적는 10단계 요약(평문 · 저장소 밖) — 팝업 stage10의 정본
MONTHLY_PLAIN = os.path.join(ROOT, "brain", "cache", "monthly_plain.json")
CF_LU_MIN, CF_LU_MAX = 15, 250   # A — 상한가 뒤 15~250거래일(식은 바닥)
CF_DD_MAX = -50                  # 1년 고점 대비 -50% 이하(깊이 — 진짜 알파)
CF_VAL_MIN = 10.0                # 20거래일 평균 거래대금 10억원(개수 조절용)
CF_THEME_DAYS = 20               # 같은 테마 다른 종목 상한가 20거래일 내
CF_OBS_MAX = 10                  # B(무상한가) 관찰 줄 최대 개수(2026-11-24 — 5개 잘림 지적)
CF_FAST4_DAYS = 10               # 적극매수 판정 — '④가 상한가 뒤 10거래일 이내' 칸(+20% 78.2% · 재상한가 32.7%)
CF_BUY_MAX = 14                  # 🎯 실전 매수 적중 최대(넘으면 배지·대금 순으로) — 넘친 종목은 아래 '외 N'으로 센다
# 재무·공시 위험(18-7 · 2026-11-24 보완 1번) — 이 점수부터 🎯 칸에서 아예 뺀다.
#   · 2점(적자+차입 같은 두 가지)은 하향 — 적극매수만 막고 ⚠를 달아 보이는 채로 둔다.
#   · 3점 이상 또는 고유 악재(횡령·관리종목·불성실공시…)는 빼고 보고에 남긴다.
CF_RISK_CUT = 3
CF_RADAR_MAX = 6                 # 📡 레이더 길목 최대(핵심만)
RADAR = os.path.join(ROOT, "projects", "stock-news-radar", "data", "radar.json")
# 2026-11-24 — 레이더가 비공개 탭이 되면서 data/radar.json 은 잠금본이다.
#   정리(--radar)는 저장소 밖 평문 원본(brain/cache/radar_plain.json)을 읽어 고치고, 다시 잠가 올린다.
RADAR_MASTER = os.path.join(ROOT, "brain", "cache", "radar_plain.json")
THEME_DB = os.path.join(ROOT, "scheduled-actions", "📊-건전테마-재부각-레이더", "theme_db.json")
# 테마별 대장주 — 90개 테마 대장주 전수조사(2026-11-19, brain/theme_leaders.json)의 결과.
#   대장 = 그 테마에서 가장 많은 돈(거래대금)이 몰린 종목. 없는 테마는 theme_db 상한가일 횟수로 채운다.
LEADERS = os.path.join(ROOT, "brain", "theme_leaders.json")
# A++ 수동 도장 — 코드는 A++를 스스로 찍지 않는다(2026-11-19 지시).
#   뉴스(살아있는 재료)와 실물 차트(며칠 뒤 오를 만큼 이쁜 1·2·3·4 자리)를 눈으로 검수한
#   종목만 이 파일에 손으로 적고, 빌드가 그 종목에만 배지를 붙인다. 없거나 비면 A++ 0.
APLUS = os.path.join(ROOT, "brain", "hotbar_a_plus.json")
# 진화 점수판 — 16:30 복기가 매일 채점을 적는 원장과, 기계가 읽는 공식 예상 파일
SCORECARD = os.path.join(ROOT, "brain", "evolution_scorecard.md")
PREDICT = os.path.join(ROOT, "brain", "cache", "scorecard", "predictions.json")
KST = timezone(timedelta(hours=9))

# 핫바 잠금 — data/hotbar.json 은 공개 저장소에 올라가므로 내용을 AES-256-GCM 으로 암호화해 둔다.
# 비밀번호는 환경변수 HOTBAR_PW 로 받는다(없으면 지금 쓰는 비밀코드).
# 2026-11-21 푸른하늘님 지시로 비밀코드를 <YOUR_PRIVATE_PASSWORD> 으로 바꿨다 — 이 파일은 공개 저장소에 올리지 않는다.
HOTBAR_PW = os.environ.get("HOTBAR_PW") or "<YOUR_PRIVATE_PASSWORD>"
PBKDF2_ITER = 100000


def seal(payload: dict, pw: str) -> dict:
    """브라우저 Web Crypto(crypto.subtle)가 그대로 풀 수 있는 형태로 잠근다.

    PBKDF2-SHA256(100,000회, salt 16바이트) → AES-256-GCM(iv 12바이트) → ct||tag 를 base64 로.
    파일에는 enc·salt·iv·ct 네 칸만 남아, GitHub 에서 열어도 종목명·숫자가 보이지 않는다.
    """
    from Crypto.Cipher import AES
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    key = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, PBKDF2_ITER, dklen=32)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ct, tag = AES.new(key, AES.MODE_GCM, nonce=iv).encrypt_and_digest(raw)
    b64 = lambda x: base64.b64encode(x).decode("ascii")
    return {"enc": 1, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct + tag)}

FETCH_COUNT = 520       # 종목당 일봉 (약 24개월 — 480봉 눈금 + 48주·12개월 판정에 충분)

# ---- 판정 문턱값 (모두 '실제 시세'에서 나온 값) ----
LU_RET = 0.285          # 상한가 판정: 전일 종가 대비 +28.5% 이상
LU_CEIL = 0.95          # 또는 고가=종가로 계산상 상한가(전일×1.3)의 95% 이상 = 잠긴 상한가
LU_LOOKBACK = 180       # '첫 상한가' 판정: 그 앞 180봉 안에 상한가가 없어야 한다(2026-11-19 지시)
DAY_WINDOW_DAYS = 30    # 일봉 1→10 대상: 상한가가 최근 1달(캘린더 30일 ≈ 20~22거래일) 안
DAY_MAX_NUM = 12        # 일봉 번호는 12번까지만 매긴다(그 뒤는 12번으로 묶음)
TF_MAX_NUM = 12         # 주봉·월봉도 5번 이후를 12번까지 이어 센다(2026-11-20 지시)

# ---- 480봉 0~100 눈금 · 주봉 240선 하단 선 뭉침 (2026-11-20 지시, brain/front_back_window_study.md)
OSC_BARS = 480          # 눈금 창 — 2년 치. 640으로 늘려도 같은 자리(연구 §2)라 480 하나만 쓴다
OSC_LOW, OSC_HIGH = 35, 70   # 아래쪽 · 가운데 · 위쪽 칸
CL_WIN = 240            # 주봉 240주(약 4.6년) 창
CL_MAS = (5, 10, 20, 60, 120)   # 이 다섯 선이 한 줄로 모였는가
CL_SPREAD = 20.0        # 선 간격 (최대-최소)/최소 ≤ 20%
CL_BOTTOM = 35.0        # 선 무리가 창의 하단 35% 안
CL_DIST = 40.0          # 주가가 선 무리에서 ±40% 안(±15%로 좁히면 첫 상한가가 거의 안 걸린다 — 연구 §6-1)
CL_VOL = 0.90           # 그 주 거래량이 240주 최대의 90% 이상
BOTTOM_DD = -45         # 1년 고점 대비 -45% 이하 = 바닥권(강조 표시)
# ---- 주봉·월봉 핫바 (2026-11-19 푸른하늘님 지시로 전면 개편) ----
#   ① 테마·재료 있는 종목만  ② 바닥에서 거래량이 최소 6개월 조용히 누운 뒤,
#   그 6개월 최대 거래량보다 크게 터진 **시작 거래량**(1번 봉)  ③ 뒤쪽도 버리지 않고 '앞쪽/뒤쪽'으로 표시.
WEEK_LOOKBACK = 26      # 주봉: 직전 26주(6개월) 최대 거래량 — 이걸 넘는 양봉이 시작 거래량
MONTH_LOOKBACK = 6      # 월봉: 직전 6개월 최대 거래량
WEEK_SCAN = 12          # 최근 12주 안에서 시작 거래량을 찾는다(그보다 오래되면 3번이 지난 자리)
MONTH_SCAN = 4          # 최근 4개월
START_NEAR_LOW = 0.35   # (참고) 시작 봉 직전 종가가 6개월 최저가에 붙어 있는 정도
START_MULT = 2.0        # "이전 6개월 거래량을 뚜렷하게 넘어서는" 시작 거래량 — 6개월 최대의 2배 이상
                        #   (2026-11-20 지시 "주봉.월봉은 지금사진 처럼 1번으로 정리" — 사진 3장은 4.6·13.5·50.9배)
BOTTOM_1Y = 0.60        # 시작 봉 직전 종가가 1년 고점의 60% 이하 = 바닥권(-40% 이상)에서 출발
LINE_NEAR = 1.05        # 주봉·월봉 4번 — 3번 반등 뒤 2번 눌림 저점(기준선) +5% 안까지 내려온 적
LINE_KEEP = 0.97        # 기준선 -3% 아래로 깨면 그림 깨짐(4번으로 싣지 않는다)
WEEK_MA_LONG = 240      # 장기 이평선 — 주봉 240선
MONTH_MA_LONG = 120     # 월봉 120선
BODY_MIN = 0.20         # 기준 봉 몸통이 봉 전체 길이의 20% 이상이어야 양봉/음봉 구분이 확실
BODY_MIN_PCT = 0.3      # (그리고 시가 대비 0.3% 이상) — 도지·몸통 없는 봉은 기준선을 긋지 않는다
MIN_AMT3 = 5e8          # 최근 3일 평균 거래대금 5억 미만 = 얇은 종목(일봉은 싣되 '얇음' 딱지, 주·월봉은 제외)
MIN_DAYS = 60           # 주봉·월봉을 보려면 최소 60거래일
MIN_DAYS_DAY = 25       # 일봉 1→10 은 상장한 지 얼마 안 된 종목도 싣는다(무조건 편입)

# ---- 앞/중/뒤 문턱 (10년 전체 최대 거래량 대비) ----
POS_FRONT = 0.90        # 이상 = 앞 (역대 최고 수준의 거래량)
POS_MID = 0.50          # 이상 = 중, 미만 = 뒤 (과거 대시세 뒤의 반짝)
POS_ORDER = {"앞": 0, "중": 1, "뒤": 2, None: 3}

# 단계 이름 — 일봉은 2026-11-19 지시대로 시가·종가·저가 같은 말 없이 번호만 쓴다.
#   1번 상한가 → 2번 눌림(살 줄) → 3번 반등(핫바) → 4번 사는 자리 → 5·6·7… 그 뒤 흐름
# 주봉·월봉은 기존 1·2·3 그대로.
DAY_STAGE_DESC = {1: "상한가", 2: "눌림", 3: "반등(핫바)", 4: "사는 자리"}

def day_desc(n: int) -> str:
    return DAY_STAGE_DESC.get(n, "그 뒤 흐름")

STAGE_ORDER = {"day": tuple(range(1, DAY_MAX_NUM + 1)),
               "week": tuple(range(1, TF_MAX_NUM + 1)), "month": tuple(range(1, TF_MAX_NUM + 1))}
# 2026-11-21 지시 — 변별력이 없는 '주봉 첫 거래량(6개월 최대 2배)' 문구는 기본 화면에서 접는다.
#   화면에는 '시작 거래량'만 남기고, 자세한 잣대는 STAGE_HELP(카드 tooltip)로 내린다.
STAGE_DESC = {
    "day": {n: day_desc(n) for n in range(1, DAY_MAX_NUM + 1)},
    "week": {1: "시작 거래량", 2: "눌림", 3: "첫 반등", 4: "사는 자리"},
    "month": {1: "시작 거래량", 2: "눌림", 3: "첫 반등", 4: "사는 자리"},
}
STAGE_HELP = {
    "week": {1: "바닥에서 6개월 조용하던 거래량을 뚜렷하게 넘어선 주봉 양봉(6개월 최대 2배 이상)"}, 
    "month": {1: "바닥에서 6개월 조용하던 거래량을 뚜렷하게 넘어선 월봉 양봉(6개월 최대 2배 이상)"},
    "day": {2: "2번 줄 — ③(반등 양봉)이 나온 뒤에야 ② 눌림 저점에 긋고, 더 높은 자리에서 다시 ②③이 나오면 그 ②③ 아래(③ 저점)로 갱신한다"},
}
for _k in ("week", "month"):
    for _n in range(5, TF_MAX_NUM + 1):
        STAGE_DESC[_k][_n] = "그 뒤 흐름"     # 일봉 5번 이후와 같은 말


# ------------------------------------------------------------------ 시세 받기
def fetch_daily(symbol: str, count: int = FETCH_COUNT) -> tuple[list[list], str | None]:
    url = (f"https://fchart.stock.naver.com/sise.nhn?symbol={symbol}"
           f"&timeframe=day&count={count}&requestType=0")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read().decode("euc-kr", errors="replace")
            root = ET.fromstring(raw)
            chart = root.find("chartdata")
            cname = chart.attrib.get("name") if chart is not None else None
            rows = []
            for item in root.findall(".//item"):
                p = item.attrib.get("data", "").split("|")
                if len(p) < 6 or "null" in p[1:5]:
                    continue
                d = p[0]
                rows.append([f"{d[:4]}-{d[4:6]}-{d[6:8]}",
                             float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5])])
            rows = [r for r in rows if r[1] > 0 and r[2] > 0 and r[3] > 0 and r[4] > 0]
            if rows:
                return rows, cname
        except Exception:
            time.sleep(0.5 + attempt)
    return [], None


def universe() -> tuple[list[str], dict]:
    codes, names = [], {}
    for code, name, market, typ, _mv in json.load(open(UNIV)):
        if typ != "stock":
            continue
        codes.append(code)
        names[code] = name
    # 오늘 상한가 · 레이더에 올라온 종목은 확실히 포함한다
    try:
        d = json.load(open(os.path.join(ROOT, "projects", "stock-news-radar", "data", "news.json")))
        for it in ((d.get("upper_limits") or {}).get("items") or []):
            c = it.get("code")
            if c and c not in names:
                codes.append(c)
                names[c] = it.get("name") or c
    except Exception:
        pass
    try:
        r = json.load(open(RADAR))
        for t in (r.get("tiers") or []):
            for s in (t.get("stocks") or []):
                c = s.get("code")
                if c and c not in names:
                    codes.append(c)
                    names[c] = s.get("name") or c
    except Exception:
        pass
    return codes, names


def load_leaders() -> dict[str, dict]:
    """테마 이름 → 대장주 {code, name} — brain/theme_leaders.json (90개 테마 대장주 전수조사 결과).

    파일이 없으면 theme_db의 상한가일 목록으로 대신 고른다(상한가를 가장 많이·먼저 낸 종목).
    정렬에서만 쓴다 — 대장이 그 단계의 맨 위로 오게 한다(2026-11-20 지시
    "대장이 위에 배치 첫상한가 첫거래량 테마 재료 우선").
    """
    out: dict[str, dict] = {}
    try:
        for name, v in (json.load(open(LEADERS, encoding="utf-8")) or {}).items():
            c = str(v.get("code") or "")
            if name and c:
                out[name.strip()] = {"code": c, "name": v.get("name") or ""}
    except Exception:
        pass
    try:
        db = json.load(open(THEME_DB, encoding="utf-8"))
        for t in db.get("목록") or []:
            name = (t.get("테마") or "").strip()
            if not name or name in out:
                continue
            best = None
            for st in t.get("상한가") or []:
                days = st.get("상한가일") or []
                if not days:
                    continue
                key = (-len(days), min(days))
                if best is None or key < best[0]:
                    best = (key, str(st.get("종목코드") or ""), st.get("종목명") or "")
            if best and best[1]:
                out[name] = {"code": best[1], "name": best[2]}
    except Exception:
        pass
    return out


def theme_map() -> dict:
    """종목코드 → [{"name": 테마, "issue": 이슈 한 줄, "dates": 상한가일}] — 카드의 테마·일정·재료."""
    m: dict[str, list[dict]] = {}

    def put(c: str, name: str, issue: str = "", dates: list | None = None):
        for e in m.setdefault(c, []):
            if e["name"] == name:
                if not e.get("issue") and issue:
                    e["issue"] = issue
                if dates:
                    e.setdefault("dates", []).extend(dates)
                return
        m[c].append({"name": name, "issue": issue, "dates": list(dates or [])})

    try:
        db = json.load(open(THEME_DB, encoding="utf-8"))
    except Exception:
        return m
    for t in db.get("목록") or []:
        name = (t.get("테마") or "").strip()
        issue = (t.get("이슈요약") or "").strip()
        for st in t.get("상한가") or []:
            c = str(st.get("종목코드") or "")
            dd = st.get("상한가일") or []
            if isinstance(dd, str):
                dd = [dd]
            if c and name and "미확인" not in name:
                put(c, name, issue, dd)
    # 상한가 테마 달력(calendar.json)의 테마 이름도 같이 붙인다 — DB에 없는 종목까지 일정 배지가 붙도록
    try:
        cal = json.load(open(os.path.join(ROOT, "projects", "stock-news-radar", "data", "calendar.json"), encoding="utf-8"))
        for mo in cal.get("months") or []:
            for t in mo.get("themes") or []:
                name = (t.get("name") or "").strip()
                if "미확인" in name:
                    continue
                for st in t.get("stocks") or []:
                    c = str(st.get("code") or "")
                    if c and name:
                        # 2026-11-25 — 달력은 이제 '일봉상 첫 상한가(잡은 날)' 하나만 싣는다
                        first = str(st.get("first") or "")
                        put(c, name, (t.get("summary") or "").strip(), [first] if first else [])
    except Exception:
        pass
    # 오늘 상한가 뉴스가 붙인 테마(섹터)도 같이 붙인다 — 테마 DB·달력에 없는 종목까지 테마가 보이도록
    #   (2026-11-19 정정: "테마 섹터 개별이라도 넣어야지")
    try:
        nd = json.load(open(os.path.join(ROOT, "projects", "stock-news-radar", "data", "news.json"), encoding="utf-8"))
        for it in ((nd.get("upper_limits") or {}).get("items") or []):
            c = str(it.get("code") or "")
            name = (it.get("theme") or "").strip()
            if c and name:
                put(c, name, (it.get("issue_summary") or "").strip())
    except Exception:
        pass
    return m


def news_map() -> dict:
    """종목코드 → {"today": 오늘 상한가 카드의 이슈요약, "stock": 네이버 종목뉴스 최근 기사 제목}."""
    m: dict[str, dict] = {}
    try:
        d = json.load(open(os.path.join(ROOT, "projects", "stock-news-radar", "data", "news.json"), encoding="utf-8"))
        for it in ((d.get("upper_limits") or {}).get("items") or []):
            c = it.get("code")
            s = (it.get("issue_summary") or "").strip()
            if c and s:
                e = m.setdefault(str(c), {})
                e["today"] = s
                e["title"] = (it.get("article_title") or "").strip()
                e["press"] = it.get("article_press") or ""
                e["time"] = it.get("article_time") or ""
    except Exception:
        pass
    try:
        rc = json.load(open(os.path.join(DELTA_DIR, "hotbar_reason_cache.json"), encoding="utf-8"))
        for c, v in (rc or {}).items():
            title = (v.get("title") or "").strip()
            if not title:
                continue
            e = m.setdefault(str(c), {})
            e["stock"] = title
            e.setdefault("press", v.get("press") or "")
            e.setdefault("time", v.get("time") or "")
            e["url"] = v.get("url") or ""
    except Exception:
        pass
    return m


def _short(s: str, n: int) -> str:
    s = " ".join(s.split())
    s = re.sub(r"\s*\[[^\]]*$", "", s)          # 끝에 잘린 대괄호(예: [이런국장…) 떼기
    s = s.replace("&quot;", '"').replace("&amp;", "&").replace("&#39;", "'")
    return s if len(s) <= n else s[:n].rstrip(" ,·-[]…") + "…"


def reason_of(code: str, tmap: dict | None, newsmap: dict | None) -> tuple[str, str]:
    """카드에 넣을 재료 한 줄과 테마 이름. 확인된 재료가 없으면 ('재료 미확인', '').

    순서: 오늘 상한가 기사 요약 → 네이버 종목뉴스에서 확인한 최근 기사 제목
          → 테마 DB 이슈요약 → 테마 이름(달력). 테마명은 괄호를 뗀 짧은 이름을 쓴다.
    """
    tm = list((tmap or {}).get(code) or [])
    theme = ""
    if tm:
        best = max(tm, key=lambda e: (len(e.get("dates") or []), len(e.get("issue") or "")))
        theme = best["name"]
    news = (newsmap or {}).get(code) or {}
    weak = ("등 마감", "마감시황", "거래상위")
    for txt in (news.get("today"), news.get("stock")):
        if not txt:
            continue
        if any(w in txt for w in weak) and not any(k in txt for k in ("상한가", "급등")):
            continue
        return _short(txt, 46), theme
    for e in tm:
        if e.get("issue"):
            first = re.split(r"[.。]|다\.\s|며 |고 ", e["issue"].strip())[0]
            base = re.sub(r"\s*\([^)]*\)\s*", " ", e["name"]).strip()
            return _short(f"{base} · {first}", 60), e["name"]
    if theme:
        return _short(re.sub(r"\s*\([^)]*\)\s*", " ", theme).strip(), 40), theme
    return "재료 미확인", ""


INDIV_MARKS = ("개별", "미확인")

# 카드 오른쪽에 '개별' 대신 보일 짧은 키워드 — 섹터가 먼저, 없으면 재료 종류(2026-11-19 정정 지시).
#   "테마 섹터 개별이라도 넣어야지" → 테마 DB에 없어도 개별 재료·섹터가 확인되면 싣고,
#   카드에는 그 섹터/재료 키워드를 보여 준다(예: '개별 · 수주').
SECTOR_KEYS = (
    ("반도체", ("반도체", "HBM", "메모리", "파운드리", "웨이퍼", "소부장", "기판", "후공정")),
    ("2차전지", ("2차전지", "배터리", "양극재", "음극재", "분리막", "전해액")),
    ("바이오", ("바이오", "제약", "신약", "임상", "백신", "항암", "치료제")),
    ("화장품", ("화장품", "뷰티", "코스메틱")),
    ("방산", ("방산", "방위", "미사일", "국방")),
    ("조선", ("조선", "선박", "해양플랜트")),
    ("건설", ("건설", "재건", "토목", "부동산", "아파트")),
    ("게임", ("게임",)),
    ("엔터", ("엔터", "드라마", "콘텐츠", "한한령", "K팝", "웹툰")),
    ("로봇", ("로봇", "휴머노이드", "피지컬")),
    ("AI", ("AI", "인공지능", "LLM", "데이터센터")),
    ("전력", ("전력", "변압기", "전선", "송전", "전기")),
    ("원전", ("원전", "SMR", "핵")),
    ("태양광", ("태양광", "재생에너지", "풍력")),
    ("자동차", ("자동차", "차량", "전기차", "부품")),
    ("식품", ("식품", "음식", "제과", "식음료")),
    ("화학", ("화학", "정유", "나프타", "석유")),
    ("철강", ("철강", "금속", "알루미늄")),
    ("해운", ("해운", "운임", "선사")),
    ("항공", ("항공", "여행", "관광")),
    ("유통", ("유통", "소매", "편의점")),
    ("금융", ("금융", "은행", "증권", "보험")),
    ("통신", ("통신", "5G", "네트워크")),
    ("의료기기", ("의료기기", "진단", "의료AI")),
    ("보안", ("보안", "해킹", "정보보호")),
)
MATERIAL_KEYS = (
    ("공개매수", ("공개매수", "상폐", "MBO")),
    ("수주", ("수주", "공급계약", "납품", "선정", "계약 체결", "계약")),
    ("실적", ("실적", "영업이익", "매출", "흑자", "서프라이즈")),
    ("공시", ("유상증자", "전환사채", "감자", "자사주", "최대주주", "경영권")),
    ("설비투자", ("공장", "설비", "증설")),
    ("임상", ("임상", "FDA", "허가", "기술이전")),
    ("M&A", ("인수", "합병")),
    ("기술", ("특허", "기술", "개발", "양산")),
    ("수출", ("수출",)),
    ("지분", ("지분", "단순 투자")),
    ("제품", ("출시", "신제품")),
)
SECTOR_KEYS = SECTOR_KEYS + (("남북경협", ("남북경협", "개성공단", "금강산")),)


def is_indiv_theme(theme: str) -> bool:
    """테마 이름이 테마가 아니라 '개별 …' 묶음인지(예: '3분기 실적 서프라이즈·수주 (개별 실적주)')."""
    t = " ".join((theme or "").split())
    return any(w in t for w in INDIV_MARKS)


def keyword_of(text: str) -> str:
    """재료 문장에서 짧은 섹터·재료 키워드 하나를 뽑는다(섹터 먼저, 없으면 재료 종류)."""
    t = text or ""
    for word, keys in SECTOR_KEYS:
        if any(k in t for k in keys):
            return word
    for word, keys in MATERIAL_KEYS:
        if any(k in t for k in keys):
            return word
    return ""


def material_ok(theme: str, reason: str) -> tuple[bool, str]:
    """핫바에 실을 종목인지 — **진짜 무재료 종목만 뺀다** (2026-11-19 정정: "테마 섹터 개별이라도 넣어야지").

    일봉·주봉·월봉 **모두** 같은 기준을 쓴다.
      · theme_db·달력·오늘 상한가 뉴스에 테마가 있으면 싣는다(테마가 '개별 …' 묶음이어도 싣는다).
      · 테마가 없어도 확인된 개별 재료(단독 뉴스·수주·실적·공시)의 reason 이 있으면 싣는다.
      · 테마도 없고 reason 도 '재료 미확인'인 종목만 뺀다.
    돌려주는 값: (실을지, 뺀 이유)
    """
    t = " ".join((theme or "").split())
    r = " ".join((reason or "").split())
    if t:
        return True, ""
    if r and r not in ("재료 미확인", "개별", "미확인"):
        return True, ""
    return False, "테마·재료 없음"


def theme_label(theme: str, reason: str) -> str:
    """카드 오른쪽에 보일 칸 — 테마가 확실하면 짧은 테마명, 개별이면 '개별 · 키워드'."""
    t = " ".join((theme or "").split())
    if t and not is_indiv_theme(t):
        return short_theme(t)
    key = keyword_of(f"{t} {reason or ''}")
    return f"개별 · {key}" if key else "개별"


def short_theme(theme: str) -> str:
    """카드에 보일 정도로 짧게 — ' — ' 뒤 부연과 괄호 설명을 뗀다(사이트도 같은 규칙)."""
    t = (theme or "").strip().split(" — ")[0]
    t = re.sub(r"\s*\([^)]*\)\s*", " ", t).strip()
    return t or (theme or "").strip()


def bar(entries, k: int) -> list:
    """테마 이름만 k개 (카드의 일정 배지·호환용)."""
    return [e["name"] for e in (entries or [])][:k]


def load_allmax() -> dict:
    """10년 전체 최대 봉 거래량 — brain/tools/build_vol_allmax.py 가 만든 기준표.
    없으면 빈 표를 돌려주고, 그때는 앞/뒤 판정을 붙이지 않는다."""
    try:
        with open(ALLMAX, encoding="utf-8") as f:
            return (json.load(f) or {}).get("max") or {}
    except Exception:
        print("⚠ 10년 거래량 기준표가 없습니다:", ALLMAX, "— python3 brain/tools/build_vol_allmax.py", flush=True)
        return {}


def load_a_plus() -> dict[str, list[str]]:
    """손으로 찍은 A++ 도장만 읽는다 — {코드: [이유…]}.

    파일 모양(둘 다 받는다):
      {"005930": "살아있는 재료 + 이쁜 1·2·3·4 자리"}
      {"stamps": {"005930": ["재료", "이쁜 4번"]}}
    '_'로 시작하는 칸은 설명용으로 보고 건너뛴다. 파일이 없거나 깨졌으면 A++ 0으로 간다.
    """
    try:
        with open(APLUS, encoding="utf-8") as f:
            raw = json.load(f) or {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"⚠ A++ 수동 도장 파일을 읽지 못했습니다({APLUS}): {e} — A++ 0으로 진행", flush=True)
        return {}
    src = raw.get("stamps") if isinstance(raw.get("stamps"), dict) else raw
    out: dict[str, list[str]] = {}
    for k, v in (src or {}).items():
        code = str(k).strip()
        if not code or code.startswith("_") or not code.isdigit():
            continue
        if isinstance(v, str):
            why = [v.strip()] if v.strip() else []
        elif isinstance(v, (list, tuple)):
            why = [str(x).strip() for x in v if str(x).strip()]
        elif isinstance(v, dict):
            why = [str(x).strip() for x in (v.get("why") or []) if str(x).strip()]
        else:
            why = []
        out[code.zfill(6)] = why or ["직접 검수"]
    return out


def pos_of(ratio: float | None) -> str | None:
    if ratio is None:
        return None
    if ratio >= POS_FRONT:
        return "앞"
    if ratio >= POS_MID:
        return "중"
    return "뒤"


# ------------------------------------------------------------ 480봉 눈금 · 주봉 240선 선 뭉침
def osc_pos(rows: list[list]) -> dict | None:
    """지금 종가가 최근 480봉(2년) 최저~최고 사이에서 몇 점(0~100)인가.

    brain/front_back_window_study.md: 눈금은 '얼마나 위에 있나'를 보는 자이고
    앞/뒤 도장은 10년 거래량이 찍는다 — 그래서 화면에서도 눈금은 작은 숫자로만 붙인다.
    봉이 480개보다 모자라면 있는 봉으로 재고, 몇 봉으로 쟀는지(osc_n)를 함께 남긴다.
    """
    if not rows:
        return None
    win = rows[-OSC_BARS:]
    lo = min(r[3] for r in win)
    hi = max(r[2] for r in win)
    if hi <= lo:
        return None
    c = rows[-1][4]
    v = (c - lo) / (hi - lo) * 100
    return {"osc": int(round(max(0.0, min(100.0, v)))), "osc_n": len(win),
            "osc_lo": round(lo, 2), "osc_hi": round(hi, 2),
            "osc_band": "아래쪽" if v <= OSC_LOW else ("가운데" if v <= OSC_HIGH else "위쪽")}


def cluster_240(wk: list[dict], when: str | None = None, vol_weeks: int = 1) -> dict | None:
    """주봉 240주 창에서 5·10·20·60·120주 선이 창 하단에 한 줄로 뭉쳤는가.

    when = 잰 날짜(그 주에 세운다 — 일봉이면 1번 상한가 봉이 든 주, 주봉·월봉이면 1번 시작 봉이 든 주).
    주지 않으면 마지막 주(오늘) 기준. 그 주의 봉·선·창으로 잰다 — 상한가 주의 거래량으로 재야
    "불씨가 붙었는가"를 맞게 본다(연구 §6: 그 주 거래량이 240주 최대의 90% 이상).

    네 가지를 다 넘어야 '선뭉침'(cl=1):
      ① 다섯 선 간격 (최대-최소)/최소 ≤ 20%  ② 선 무리가 창(240주 최저~최고)의 하단 35% 안
      ③ 주가가 선 무리에서 ±40% 안           ④ 그 주 거래량이 240주 최대의 90% 이상
    선은 뭉쳤는데 ④만 모자라면 cl_wait=1 ('선뭉침·불씨전') — 화면은 노랑으로 구분한다.
    잰 값은 모두 남겨 차트에서 숫자로 확인할 수 있게 한다(cl_sp·cl_pos·cl_dist·cl_vol).
    """
    if len(wk) < CL_WIN:
        return None                      # 240주가 안 쌓이면 잴 수 없다(상장 얼마 안 된 종목)
    i = len(wk) - 1
    if when:
        hit = next((k for k, b in enumerate(wk) if b["start"] <= when <= b["end"]), None)
        if hit is None:
            return None
        i = hit
    win = wk[max(0, i + 1 - CL_WIN): i + 1]
    if len(win) < CL_WIN:
        return None
    mas = []
    for m in CL_MAS:
        seg = wk[max(0, i + 1 - m): i + 1]
        if len(seg) < m:
            return None
        mas.append(sum(b["c"] for b in seg) / m)
    if min(mas) <= 0:
        return None
    lo = min(b["l"] for b in win)
    hi = max(b["h"] for b in win)
    if hi <= lo:
        return None
    spread = (max(mas) - min(mas)) / min(mas) * 100
    center = sum(mas) / len(mas)
    pos = (center - lo) / (hi - lo) * 100
    last = wk[i]["c"]
    dist = (last / center - 1) * 100 if center else 0.0
    vmax = max(b["v"] for b in win) or 0
    vseg = wk[max(0, i + 1 - max(1, vol_weeks)): i + 1]
    best = max(vseg, key=lambda b: (vol_pace(b, WEEK_DAYS) if b is wk[i] else b["v"])) if vseg else wk[i]
    volr = ((vol_pace(best, WEEK_DAYS) if best is wk[i] else best["v"]) / vmax) if vmax else 0.0
    ok_line, ok_bot = spread <= CL_SPREAD, pos <= CL_BOTTOM
    ok_dis, ok_vol = abs(dist) <= CL_DIST, volr >= CL_VOL
    out = {"cl_sp": round(spread, 1), "cl_pos": round(pos, 1), "cl_dist": round(dist, 1),
           "cl_vol": round(volr, 2), "cl_w": len(wk), "cl_at": best["end"]}
    if ok_line and ok_bot and ok_dis and ok_vol:
        out["cl"] = 1
    elif ok_line and ok_bot and ok_dis:
        out["cl"], out["cl_wait"] = 0, 1     # 선은 뭉쳤는데 거래량이 아직 안 붙었다
    else:
        out["cl"] = 0
    return out


def cluster_table(vol_weeks: int = 8) -> dict[str, dict]:
    """10년 원본(brain/cache/hotbar_parts)을 한 번 훑어 종목별 선뭉침 숫자만 남긴다.

    주봉 240주를 만들려면 2015-06~ 자료가 필요한데, 2,700종목 일봉을 통째로 메모리에
    올리면 수 GB가 된다 — 종목 하나씩 주봉으로 접어 숫자 몇 개만 보관한다.
    기준 주는 최근 8주 안에서 거래량이 가장 컸던 주(핫바 종목의 상한가·시작 거래량이 그 안에 있다).
    테마 종목만 보던 long_history 와 달리 10년 자료가 있는 모든 종목을 채운다 —
    '개별'로 뜨는 종목(대한항공우 같은)도 선뭉침을 볼 수 있게 하기 위해서다.
    """
    out: dict[str, dict] = {}
    for path in sorted(glob.glob(os.path.join(DELTA_DIR, "hotbar_parts", "part_*.json.gz"))):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                daily = (json.load(f) or {}).get("daily") or {}
        except Exception:
            continue
        for c, rows in daily.items():
            if c in out or not rows or len(rows) < CL_WIN * 4:
                continue
            wk = make_bars(clean_rows(rows), week_key)
            r = cluster_240(wk, vol_weeks=vol_weeks)
            if r:
                out[c] = r
    return out


# ------------------------------------------------------------------ 진화 점수판 (잠긴 자료 안에만)

def scorecard(base_date: str) -> dict | None:
    """brain/evolution_scorecard.md 맨 앞줄 숫자 + 최근 채점 + 공식 예상(P1~P8).

    화면에는 핫바 탭 맨 위 상자로만 나가고, hotbar.json 암호화 안에 함께 실린다.
    숫자는 점수판 문서에 적힌 값을 그대로 읽는다(여기서 다시 세지 않는다 — 채점은 16:30 복기 몫).
    """
    try:
        md = open(SCORECARD, encoding="utf-8").read()
    except Exception:
        return None
    out: dict = {"target": 99.0, "as_of": ""}
    m = re.search(r"개시:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})[^0-9]*([0-9]{1,2}:[0-9]{2})", md)
    if m:
        out["as_of"] = f"{m.group(1)} {m.group(2)}"
    m = re.search(r"전체 누적 적중률:\s*\*\*적중\s*(\d+)\s*건\s*/\s*전체\s*(\d+)\s*건\s*=\s*([0-9.]+)%", md)
    if not m:
        return None
    out["hit"], out["total"], out["rate"] = int(m.group(1)), int(m.group(2)), float(m.group(3))
    m = re.search(r"보합\s*(\d+)건을 빼고 확정만 세면\s*\*\*(\d+)/(\d+) = ([0-9.]+)%", md)
    if m:
        out["flat"] = int(m.group(1))
        out["fix_hit"], out["fix_total"], out["fix_rate"] = int(m.group(2)), int(m.group(3)), float(m.group(4))
    m = re.search(r"패스·추격금지 판정:\s*\*?(\d+)건 적중\s*/\s*(\d+)건\s*=\s*([0-9.]+)%", md)
    if m:
        out["pass_hit"], out["pass_total"], out["pass_rate"] = int(m.group(1)), int(m.group(2)), float(m.group(3))
    m = re.search(r"오늘\(([^)]+)\)\s*장중 잠정:([^→\n]+)", md)
    if m:
        out["today"] = {"date": m.group(1).strip(), "text": re.sub(r"\*\*", "", m.group(2)).strip()}

    # 표 A — 공식 픽 채점표(마크다운 표)에서 최근 것 몇 줄만
    rows = []
    for line in md.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 8:
            continue
        verdict = re.sub(r"\*", "", cells[6])
        if not any(k in verdict for k in ("적중", "실패", "보합")):
            continue
        name = re.sub(r"\([^)]*\)", "", cells[2]).strip()
        code = (re.search(r"\(([^)]+)\)", cells[2]) or [None, ""])[1]
        chg = cells[5].split("/")[0].strip().replace("%", "")
        try:
            chg_v = float(chg)
        except Exception:
            chg_v = None
        rows.append({"d": cells[1].strip(), "name": name, "code": code,
                     "chg": chg_v, "v": "적중" if "적중" in verdict and "실패" not in verdict
                     else ("실패" if "실패" in verdict else "보합")})
    out["recent"] = rows[-8:][::-1]          # 최근 채점 8건 (새것부터)

    # 공식 예상 P1~P8 — 채점일이 기준일보다 뒤면 '대기'
    try:
        pj = json.load(open(PREDICT, encoding="utf-8"))
        preds = []
        for p in (pj.get("predictions") or []):
            sd = p.get("score_date") or ""
            preds.append({"id": p.get("id") or "", "date": sd, "md": sd[5:].replace("-", "/"),
                          "target": p.get("target") or "", "f": p.get("forecast") or "",
                          "st": "대기" if sd and sd > base_date else "채점일",
                          "basis": (pj.get("rules") or {}).get("basis") or ""})
        out["preds"] = preds
    except Exception:
        out["preds"] = []
    return out


# ------------------------------------------------------------------ 레이더(공개) 정리
def wave_ratio(rows: list[list], tops: list | None) -> float | None:
    """최근 1년(13개월) 중 가장 큰 월봉 거래량 ÷ 10년 전체 최대 월봉 거래량.

    종목이 지금 어느 사이클에 서 있는지 재는 자 — 1에 가까우면 최근 1년의 파동이 역대급,
    작으면 과거 대시세의 반짝(대한항공우 0.49 · 삼아알미늄형). 이번 달(진행 중)은
    지난 거래일 수로 환산해 완성 달과 같은 잣대로 비교한다.
    """
    if len(rows) < 260:
        return None
    mo = bar_vols(rows, month_key)
    vals = [v for _st, _en, v in mo[-13:]]
    # 마지막 달이 아직 진행 중이면 환산
    if mo:
        st, en, v = mo[-1]
        days = sum(1 for r in rows if r[0] >= st)
        if days < MONTH_DAYS and rows[-1][0][:7] == st[:7]:
            vals[-1] = v / days * MONTH_DAYS
    last = max(vals, default=0)
    mx = max((v for v, _d in tops or []), default=0)
    if not last or not mx:
        return None
    return last / mx


def apply_radar(amax: dict, delta: dict) -> str:
    """레이더 정리 — 비공개 말(앞/뒤·핫바)은 파일에 쓰지 않고 '순서'만 손본다.

    최근 1년 중 가장 큰 주봉 거래량이 10년 전체 최대의 50% 미만이면
    '과거 대시세 뒤의 반짝'으로 보고 뺀다(대한항공우·삼아알미늄형).
    자료가 짧은 종목은 판정하지 않고 그대로 둔다.
    뺐던 종목이 다시 앞/중이 될 수 있도록 원본 목록은 brain/cache/radar_full.json 에 보관한다.
    """
    try:
        src = RADAR_MASTER if os.path.exists(RADAR_MASTER) else RADAR
        cur = json.load(open(src, encoding="utf-8"))
        if int((cur or {}).get("enc") or 0) == 1:      # 잠근 파일은 평문이 아니다 — 건너뛴다
            print("⚠ radar.json 이 잠금본이고 평문 원본이 없습니다 — 정리를 건너뜁니다", flush=True)
            return "skip"
    except Exception as e:
        print("⚠ radar.json 을 읽지 못했습니다:", e, flush=True)
        return "skip"
    full_path = os.path.join(DELTA_DIR, "radar_full.json")
    if os.path.exists(full_path):
        try:
            full = json.load(open(full_path, encoding="utf-8"))
        except Exception:
            full = cur
    else:
        full = cur
        json.dump(full, open(full_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 원본 목록의 테마 순서를 유지하고, 각 테마의 종목은 원본 목록 그대로 다시 평가한다
    full_tiers = {t.get("theme"): t for t in (full.get("tiers") or [])}
    stat = {"kept": 0, "front": 0, "mid": 0, "none": 0, "dropped": 0, "dropped_names": []}
    for t in cur.get("tiers") or []:
        src = full_tiers.get(t.get("theme")) or t
        orig = src.get("stocks") or []
        scored = []
        for i, s in enumerate(orig):
            code = str(s.get("code") or "")
            rows = delta.get(code) or []
            pos, vr = None, None
            if len(rows) >= 260:
                vr = wave_ratio(rows, (amax.get(code) or {}).get("m"))
                pos = pos_of(vr)
            if pos == "뒤":
                stat["dropped"] += 1
                stat["dropped_names"].append(f"{s.get('name')}({code}) {vr:.2f}")
                continue
            key = pos if pos else "none"
            stat[key] = stat.get(key, 0) + 1
            scored.append((POS_ORDER.get(pos, 3), i, s))
        scored.sort(key=lambda x: (x[0], x[1]))
        stocks = [s for _, _, s in scored]
        stat["kept"] += len(stocks)
        t["stocks"] = stocks
        if not stocks:
            t["active"] = False
    with open(RADAR_MASTER, "w", encoding="utf-8") as f:      # 저장소 밖 평문 원본
        json.dump(cur, f, ensure_ascii=False, indent=1)
    with open(RADAR, "w", encoding="utf-8") as f:             # 공개 저장소에는 잠근 파일만
        json.dump(seal(cur, HOTBAR_PW), f, ensure_ascii=False, separators=(",", ":"))
    print("레이더 정리:", stat["kept"], "종목 유지 / 뺌", stat["dropped"], stat["dropped_names"],
          "| 앞", stat.get("앞", 0), "중", stat.get("중", 0), "파동없음", stat["none"], flush=True)
    return f"kept {stat['kept']} / dropped {stat['dropped']}"


def bar_vols(rows: list[list], keyfn) -> list[list]:
    """[[봉 시작일, 봉 끝 날짜, 거래량], ...] — 앞/뒤 판정에서 '같은 봉'을 빼놓기 위해 시작일을 함께 둔다."""
    out, key = [], object()
    for r in rows:
        k = keyfn(r[0])
        if k != key:
            out.append([r[0], r[0], r[5]])
            key = k
        else:
            out[-1][1] = r[0]
            out[-1][2] += r[5]
    return out


def merge_tops(amax: dict, c: str, rows: list[list]) -> None:
    """10년 기준표(큰 봉 12개)에 오늘 캐시의 봉을 한 종목씩 합쳐 갱신한다."""
    if not rows:
        return
    cur = amax.setdefault(c, {})
    for kind, series in (("d", [[r[0], r[0], r[5]] for r in rows]),
                         ("w", bar_vols(rows, week_key)),
                         ("m", bar_vols(rows, month_key))):
        merged = {d: v for v, d in (cur.get(kind) or [])}
        for _st, en, v in series:
            merged[en] = max(merged.get(en) or 0, v)
        cur[kind] = [[int(v), d] for d, v in sorted(merged.items(), key=lambda kv: -kv[1])[:12]]


def prior_max(tops: list | None, before: str) -> float | None:
    """그 봉이 시작하기 전까지의 가장 큰 봉 거래량 — ①이 역대 최고를 넘으면 1을 넘는다."""
    best = None
    for v, d in tops or []:
        if d < before and (best is None or v > best):
            best = v
    return best


def clean_rows(rows: list[list]) -> list[list]:
    """시가·고가·저가가 0으로 찍힌 빈 봉(휴장·거래정지 자료 오류)을 뺀다.
    하나만 섞여도 차트의 저가 축이 0까지 내려가 봉이 안 보인다."""
    return [r for r in rows if len(r) >= 6 and r[1] > 0 and r[2] > 0 and r[3] > 0 and r[4] > 0]


def delta_jsonl(today: str) -> str:
    """오늘 시세 캐시 — 종목 한 줄짜리 ndjson.gz. 2,700종목 전체를 한꺼번에 파싱하면
    1GB 안팎 메모리를 쓰게 되어(작은 서버에서 OOM), 종목 하나씩 읽고 쓴다."""
    return os.path.join(DELTA_DIR, f"hotbar_delta_{today.replace('-', '')}.jsonl.gz")


def delta_path(today: str) -> str:
    """예전 형식({\"daily\":{코드:봉}}) 캐시 — 새 형식이 없을 때만 변환해서 쓴다."""
    return os.path.join(DELTA_DIR, f"hotbar_delta_{today.replace('-', '')}.json.gz")


def delta_names_path(today: str) -> str:
    return os.path.join(DELTA_DIR, f"hotbar_delta_{today.replace('-', '')}.names.json")


def _split_dict_cache(src: str, dst: str) -> int:
    """예전 dict 캐시를 종목 한 줄짜리 ndjson.gz 로 바꾼다 — 한 종목(450봉)씩만 메모리에."""
    dec = json.JSONDecoder()
    tmp, n = dst + ".part", 0
    with gzip.open(src, "rt", encoding="utf-8") as f, gzip.open(tmp, "wt", encoding="utf-8") as out:
        buf, pos, eof = "", 0, False

        def fill(need: int = 1):
            nonlocal buf, pos, eof
            while len(buf) - pos < need and not eof:
                d = f.read(1 << 20)
                if not d:
                    eof = True
                    break
                buf = buf[pos:] + d
                pos = 0

        while True:                       # \"daily\" 키 찾기
            fill(1)
            i = buf.find('"daily"', pos)
            if i >= 0:
                pos = i + 7
                break
            if eof:
                sys.exit("시세 캐시 형식을 읽지 못했습니다: " + src)
            keep = max(0, pos)
            buf, pos = buf[keep:], 0
        while True:                       # daily 의 '{'
            fill(1)
            j = buf.find("{", pos)
            if j >= 0:
                pos = j + 1
                break
            if eof:
                sys.exit("시세 캐시 형식을 읽지 못했습니다: " + src)
            buf, pos = buf[pos:], 0
        while True:
            fill(2)
            while pos < len(buf) and buf[pos] in " \t\r\n,":
                pos += 1
            if pos < len(buf) and buf[pos] == "}":
                break
            while True:                   # 종목코드 키
                fill(1)
                while pos < len(buf) and buf[pos] in " \t\r\n":
                    pos += 1
                if pos < len(buf):
                    break
                if eof:
                    break
                buf, pos = buf[pos:], 0
            if eof and pos >= len(buf):
                break
            code, end = dec.raw_decode(buf, pos)
            pos = end
            while True:                   # ':'
                fill(2)
                while pos < len(buf) and buf[pos] in " \t\r\n:":
                    pos += 1
                if pos < len(buf):
                    break
                if eof:
                    break
                buf, pos = buf[pos:], 0
            while True:                   # 봉 배열 — 다 들어올 때까지 채운다
                try:
                    rows, end = dec.raw_decode(buf, pos)
                    pos = end
                    break
                except json.JSONDecodeError:
                    if eof:
                        raise
                    more = f.read(1 << 20)
                    if not more:
                        eof = True
                        raise
                    buf, pos = buf[pos:] + more, 0
            out.write(json.dumps([str(code), rows], ensure_ascii=False, separators=(",", ":")))
            out.write("\n")
            n += 1
            if n % 500 == 0:
                print(f"  변환 {n}종목", flush=True)
    os.replace(tmp, dst)
    print(f"  변환 완료 {n}종목 → {os.path.basename(dst)}", flush=True)
    return n


def _names_from_dict(src: str) -> dict:
    """예전 dict 캐시 끝의 names 블록만 읽는다(전체를 파싱하지 않고 뒤쪽 몇 MB만 본다)."""
    tail = ""
    with gzip.open(src, "rt", encoding="utf-8") as f:
        while True:
            d = f.read(1 << 20)
            if not d:
                break
            tail = (tail + d)[-3_000_000:]
    i = tail.rfind('"names"')
    if i < 0:
        return {}
    j = tail.find("{", i)
    try:
        return json.JSONDecoder().raw_decode(tail, j)[0] or {}
    except Exception:
        return {}


def iter_delta(today: str):
    """(종목코드, 봉들) — 한 종목씩. 새 ndjson 캐시가 없으면 예전 dict 캐시를 변환해 쓴다."""
    jp, dp = delta_jsonl(today), delta_path(today)
    if not os.path.exists(jp):
        if not os.path.exists(dp):
            sys.exit(f"시세 캐시가 없습니다: {jp}  (먼저 --fetch-only 로 실행)")
        print("· 예전 시세 캐시를 종목별 파일로 변환합니다:", os.path.basename(dp), flush=True)
        _split_dict_cache(dp, jp)
        nm = _names_from_dict(dp)
        if nm:
            json.dump(nm, open(delta_names_path(today), "w", encoding="utf-8"), ensure_ascii=False)
    with gzip.open(jp, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            code, rows = json.loads(line)
            yield str(code), clean_rows(rows)


LIVE_URL = "https://polling.finance.naver.com/api/realtime/domestic/stock/"
HEAD = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"}


def fetch_quotes(codes: list[str], chunk: int = 200, workers: int = 8) -> dict[str, list]:
    """오늘 봉 하나만 배치로 받는다 — 30분 갱신용(2026-11-23).

    네이버 실시간 창구는 종목 수백 개를 한 번에 준다. 2,700종목을 3~4초에 받으므로
    30분마다 시세·형광↑을 최신으로 따라오게 하는 데 쓴다(fetch_all 은 종목당 520봉이라 느리다).
    돌려주는 값: {종목코드: [날짜, 시가, 고가, 저가, 종가, 거래량]}
    """
    groups = [codes[i:i + chunk] for i in range(0, len(codes), chunk)]

    def get(group: list[str]) -> dict[str, list]:
        out: dict[str, list] = {}
        try:
            req = urllib.request.Request(LIVE_URL + ",".join(group), headers=HEAD)
            with urllib.request.urlopen(req, timeout=20) as resp:
                d = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return out
        for it in d.get("datas") or []:
            try:
                code = str(it.get("itemCode") or "")
                c = float(str(it["closePrice"]).replace(",", ""))
                o = float(str(it["openPrice"]).replace(",", ""))
                h = float(str(it["highPrice"]).replace(",", ""))
                lo = float(str(it["lowPrice"]).replace(",", ""))
                v = float(str(it["accumulatedTradingVolume"]).replace(",", ""))
                day = str(it.get("localTradedAt") or "")[:10]
            except Exception:
                continue
            if not code or not day or min(o, h, lo, c) <= 0:
                continue
            out[code] = [day, o, h, lo, c, v]
        return out

    res: dict[str, list] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for part in ex.map(get, groups):
            res.update(part)
    return res


def overlay_row(rows: list[list], row: list | None) -> list[list]:
    """캐시 봉들에 오늘 봉 하나를 덮어쓴다(같은 날짜면 교체, 새 날짜면 뒤에 붙임)."""
    if not row or not rows:
        return rows
    if rows[-1][0] == row[0]:
        return rows[:-1] + [row]
    if rows[-1][0] < row[0]:
        return rows + [row]
    return rows


def flush_live(today: str, live: dict[str, list]) -> None:
    """이어 받은 캐시에 오늘 봉을 실제로 써 넣는다 — 10단계·테마달력 스크립트도 오늘 봉을 보게."""
    if not live:
        return
    jp, tmp = delta_jsonl(today), delta_jsonl(today) + ".part"
    n = 0
    try:
        with gzip.open(jp, "rt", encoding="utf-8") as src, \
                gzip.open(tmp, "wt", encoding="utf-8", compresslevel=1) as out:
            for line in src:
                line = line.strip()
                if not line:
                    continue
                code, rows = json.loads(line)
                row = live.get(str(code))
                if row and rows:
                    if rows[-1][0] == row[0]:
                        rows[-1] = row
                    elif rows[-1][0] < row[0]:
                        rows.append(row)
                out.write(json.dumps([str(code), rows], ensure_ascii=False,
                                     separators=(",", ":")) + "\n")
                n += 1
        os.replace(tmp, jp)
        print(f"· 이어 받은 캐시에 오늘 봉 {len(live)}종목을 써 넣었습니다({n}행)", flush=True)
    except Exception as e:
        print(f"⚠ 오늘 봉 쓰기 실패(계산은 계속): {e}", flush=True)


def fetch_all(codes: list[str], today: str) -> dict:
    """받는 대로 한 종목씩 ndjson.gz 에 적는다 — 전체 시세를 메모리에 쌓지 않는다."""
    jp, tmp = delta_jsonl(today), delta_jsonl(today) + ".part"
    names: dict[str, str] = {}
    t0, done, got = time.time(), 0, 0
    with gzip.open(tmp, "wt", encoding="utf-8") as out, ThreadPoolExecutor(max_workers=16) as ex:
        futs = {ex.submit(fetch_daily, c): c for c in codes}
        for fut in as_completed(futs):
            c = futs[fut]
            done += 1
            try:
                rows, cname = fut.result()
            except Exception:
                rows, cname = [], None
            if rows:
                got += 1
                if cname:
                    names[c] = cname
                out.write(json.dumps([c, rows], ensure_ascii=False, separators=(",", ":")))
                out.write("\n")
            if done % 300 == 0:
                print(f"  받는 중 {done}/{len(codes)} ({time.time()-t0:.0f}s)", flush=True)
    os.replace(tmp, jp)
    json.dump(names, open(delta_names_path(today), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  시세 {got}/{len(codes)}종목 · {time.time()-t0:.0f}s", flush=True)
    return names


def load_names(today: str) -> dict:
    try:
        return json.load(open(delta_names_path(today), encoding="utf-8")) or {}
    except Exception:
        return {}


def previous_delta(today: str) -> tuple[str, str] | None:
    """오늘 것보다 앞선 날짜의 시세 캐시(가장 최근) — 그날 파일이 없을 때 이어 받는 데 쓴다."""
    day = today.replace("-", "")
    cands = []
    for path in glob.glob(os.path.join(DELTA_DIR, "hotbar_delta_*.jsonl.gz")):
        m = re.search(r"hotbar_delta_(\d{8})\.jsonl\.gz$", path)
        if m and m.group(1) < day:
            cands.append((m.group(1), path))
    if not cands:
        return None
    prev_day, prev_path = max(cands)
    prev_names = os.path.join(DELTA_DIR, f"hotbar_delta_{prev_day}.names.json")
    return prev_path, prev_names


def carry_delta(today: str) -> bool:
    """오늘 시세 캐시가 없으면 어제(최근) 캐시를 오늘 이름으로 이어 받는다 — 30분 갱신 첫 회를 살린다.

    520봉을 2,700종목 다시 받지 않고, 어제 끝난 봉에 오늘 봉만 배치(fetch_quotes)로 덮어쓴다.
    봉의 날짜는 원래 봉 날짜를 그대로 쓰기 때문에 없는 봉을 만들어 넣지 않는다(오늘 봉은 실시간 값).
    """
    jp = delta_jsonl(today)
    prev = previous_delta(today)
    if not prev:
        return False
    try:
        shutil.copyfile(prev[0], jp)
        if prev[1] and os.path.exists(prev[1]):
            shutil.copyfile(prev[1], delta_names_path(today))
        print(f"· 어제 시세 캐시({os.path.basename(prev[0])})를 오늘 것으로 이어 받았습니다", flush=True)
        return True
    except Exception as e:
        print(f"⚠ 시세 캐시 이어받기 실패: {e}", flush=True)
        return False


# ------------------------------------------------------------------ 봉 집계
def make_bars(rows: list[list], keyfn) -> list[dict]:
    out, key = [], object()
    for r in rows:
        k = keyfn(r[0])
        if k != key:
            out.append({"k": k, "start": r[0], "end": r[0], "o": r[1], "h": r[2],
                        "l": r[3], "c": r[4], "v": r[5], "days": 1})
            key = k
        else:
            b = out[-1]
            b["end"] = r[0]
            b["h"] = max(b["h"], r[2])
            b["l"] = min(b["l"], r[3])
            b["c"] = r[4]
            b["v"] += r[5]
            b["days"] += 1
    return out


def week_key(d: str):
    y, w, _ = date.fromisoformat(d).isocalendar()
    return (y, w)


def month_key(d: str):
    return d[:7]


WEEK_DAYS = 5
MONTH_DAYS = 20


def vol_pace(b: dict, full_days: int) -> float:
    """진행 중인 봉(이번 주·이번 달)은 지난 날 수로 환산해 완성 봉과 같은 잣대로 비교한다."""
    if b["days"] >= full_days:
        return b["v"]
    return b["v"] / b["days"] * full_days


def cycle_pos(when: str, wk: list[dict], mo: list[dict], am: dict) -> dict:
    """일봉 상한가 자리를 주봉·월봉 거래량으로 다시 잰다 (2026-11-19 07:38 지시).

    일봉 봉 거래량은 10년 일봉 최대에 비하면 늘 작아서 하루 상한가가 전부 '뒤'로 나왔다.
    그 상한가 봉이 들어 있는 **주봉·월봉 한 봉**의 거래량 ÷ 그 봉 앞 10년 최대 주·월봉
    거래량으로 재고, 주봉·월봉 중 큰 쪽으로 앞/중/뒤를 판정한다 — "이 일봉 상한가가
    주·월봉상 앞쪽에서 뜬 건지 뒷쪽에서 뜬 건지"가 바로 보이게.
    값은 차트에 보이는 그 봉의 실제 거래량 그대로다(진행 중인 주·월봉은 아직 덜 찼으므로
    낮게 나오는 것이 맞다) — 주봉·월봉 탭의 숫자와 같은 잣대다.
    돌려주는 값: {"vr_week": .., "vr_month": .., "vr_all": .., "pos_src": "주봉"|"월봉"}
    """
    out: dict = {}
    partial: dict = {}
    for key, bars, full in (("week", wk, WEEK_DAYS), ("month", mo, MONTH_DAYS)):
        i = next((k for k, b in enumerate(bars) if b["start"] <= when <= b["end"]), None)
        if i is None:
            continue
        mx = prior_max((am or {}).get(key[0]), bars[i]["start"])
        if not mx:
            continue
        out["vr_" + key] = round(bars[i]["v"] / mx, 3)
        if bars[i]["days"] < full:
            partial[key] = bars[i]["days"]     # 아직 차고 있는 주·월봉 — 숫자가 낮게 나오는 게 당연하다는 표시
    best = None
    for key, label in (("week", "주봉"), ("month", "월봉")):
        v = out.get("vr_" + key)
        if v is not None and (best is None or v > best[0]):
            best = (v, label, key)
    if best:
        out["vr_all"] = best[0]
        out["pos_src"] = best[1]
        if best[2] in partial:
            out["pos_partial"] = f"이번 {'주' if best[2] == 'week' else '달'} {partial[best[2]]}거래일"
    return out


# ------------------------------------------------------------------ 일봉 1·2·3
def _pct(v: float) -> str:
    """고점 대비 — 고점이면 '', 아니면 '-23%'(또는 '+4%')."""
    v = float(v or 0)
    return "" if abs(v) < 0.5 else (f"-{abs(v):.0f}%" if v < 0 else f"+{v:.0f}%")


def day_lu(rows: list[list], i: int) -> bool:
    """그날이 실제 상한가였나 — 전일 종가 대비 +28.5% 이상,
    또는 고가=종가로 계산상 상한가(전일×1.3)의 95% 이상(수정주가·호가 차이로 27%대로 찍히는 잠긴 상한가)."""
    if i < 1:
        return False
    pc = rows[i - 1][4]
    if not pc or rows[i][4] <= 0:
        return False
    r = rows[i][4] / pc - 1
    return r >= LU_RET or (rows[i][4] == rows[i][2] and rows[i][4] >= LU_CEIL * pc * 1.3)


def ma240_side(rows: list[list], i0: int | None) -> str | None:
    """일봉 240선 위/아래 — 상한가 전날 종가로 잰다(10단계와 같은 잣대)."""
    j = (i0 or 0) - 1
    if j + 1 < 240 or j + 1 > len(rows):
        return None
    ma = sum(r[4] for r in rows[j + 1 - 240:j + 1]) / 240
    return "위" if rows[j][4] > ma else "아래"


def first_vol(rows: list[list], i0: int | None) -> tuple[float | None, str | None]:
    """첫 거래량 — 상한가 봉 거래량 ÷ 앞 125봉 최대. 1.0배 넘으면 그 구간 첫 거래량."""
    if i0 is None or i0 < 1 or i0 >= len(rows):
        return None, None
    prior = [r[5] for r in rows[max(0, i0 - 125):i0]]
    if len(prior) < 60 or not max(prior):
        return None, None
    x = round(rows[i0][5] / max(prior), 1)
    return x, ("첫" if x >= 1.0 else "아직")


def latest_hotbar_pair(rows: list[list], i0: int) -> dict | None:
    """가장 최근의 '②하락 음봉 → ③ 윗꼬리 긴 양봉(핫바)' 짝을 찾는다 — 2026-11-21 지시.

    한싹(1번 11-03)처럼 1번 상한가 직후의 첫 눌림(2,650원)만 기준선으로 고정하지 않는다.
    상승 파동 고점(①) 뒤에 **앞 3봉보다 낮은 저점까지 밀린 하락 음봉(②)**이 멈서고
    바로 **몸통 크고 아랫꼬리 작고 윗꼬리 긴 양봉(③)**이 나오면, 기준선은 그 ②③ 아래
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
                continue                                 # 앱 3봉보다 낮은 저점까지 민 음봉만
            if j + 1 < n and rows[j + 1][3] < lo:
                continue                                 # 그 자리에서 멈춘 저점(다음 봉이 더 낮으면 아직 내려오는 중)
            return {"b2": j, "b3": i, "line": min(rows[j][4], l3)}
    return None


def day_pivots(rows: list[list], start: int) -> list[tuple[int, str]]:
    """봉 하나하나의 고점(H)·저점(L) — 양 옆 봉보다 확실히 높거나 낮은 자리만.
    같은 종류가 이어지면 더 극단인 것만 남겨서 고점·저점이 번갈아 나오게 한다."""
    n = len(rows)
    pts: list[tuple[int, str]] = []
    for i in range(start + 1, n - 1):
        h, l = rows[i][2], rows[i][3]
        if l < rows[i - 1][3] and l < rows[i + 1][3]:
            pts.append((i, "L"))
        elif h > rows[i - 1][2] and h > rows[i + 1][2]:
            pts.append((i, "H"))
    out: list[tuple[int, str]] = []
    for i, t in pts:
        if out and out[-1][1] == t:
            j = out[-1][0]
            if (t == "L" and rows[i][3] < rows[j][3]) or (t == "H" and rows[i][2] > rows[j][2]):
                out[-1] = (i, t)
        else:
            out.append((i, t))
    return out


def day_stage(rows: list[list], theme_ok: bool = False) -> dict | None:
    """일봉 1 → 2 → 3 → 4 → 5·6·7… — 상한가가 나온 종목을 하루씩 따라가며 번호를 매긴다.

    (2026-11-19 푸른하늘님 지시: 시가·종가·저가 같은 말 없이 번호만. 상한가가 나오면 무조건 넣고,
     1번에서 테마를 구분하고, 4번은 사는 자리, 그 뒤는 5·6·7…로 끝까지 기록.)

    1번 = 상한가 봉(최근 1달). 앞 180봉에 상한가가 없으면 '첫 상한가'.
    2번 = 상한가 뒤 고점에서 눌림. 이 자리의 저점이 '줄'(미리 그어 두는 매수 가격대).
    3번 = 그 눌림 뒤 거래량 실린 첫 양봉(추세 전환 = 핫바).
    4번 = 3번 뒤 다시 줄 쪽으로 내려온 자리(사는 자리). 아직 안 내려왔으면 진행 중.
    5번부터 = 4번 뒤 고점·저점을 번갈아 5·6·7·8… 로 끝까지. (홀수=고점, 짝수=저점)

    그림이 깨진 종목도 빼지 않는다 — 2번(눌림)에 그대로 남겨 둔다.
    """
    n = len(rows)
    if n < MIN_DAYS_DAY:
        return None
    close = [r[4] for r in rows]
    high = [r[2] for r in rows]
    low = [r[3] for r in rows]
    op = [r[1] for r in rows]
    vol = [r[5] for r in rows]
    lu = [day_lu(rows, i) for i in range(n)]

    # 최근 1달 안의 상한가 — 가장 이른 것부터 한 줄로 따라간다(빠짐없이)
    cut = (date.fromisoformat(rows[-1][0]) - timedelta(days=DAY_WINDOW_DAYS)).isoformat()
    hits = [j for j in range(n) if rows[j][0] >= cut and lu[j]]
    if not hits:
        return None
    s = hits[0]                                   # 1번 봉
    first_lu = not any(lu[j] for j in range(max(0, s - LU_LOOKBACK), s))

    p = max(range(s, n), key=lambda i: high[i])   # 1번 뒤 고점
    n_day = n - 1 - s
    after = n - 1 - p
    last = close[n - 1]
    prev_high = max(high[s:n - 1]) if n - 1 > s else high[s]
    over = (last / prev_high - 1) * 100 if prev_high else 0.0

    info: dict = {
        "base_date": rows[s][0], "base_close": close[s],
        "lu_date": rows[s][0], "lu_dates": [rows[j][0] for j in hits],
        "lu_n": len(hits), "lu_first": first_lu,
        "peak_date": rows[p][0], "peak_high": high[p],
        "days_after_peak": after, "cycle_days": n_day,
        "prev_high": prev_high, "over_pct": round(over, 1),
        "peak_dd": round((last / high[p] - 1) * 100, 1),
        "v0": vol[s], "v0_start": rows[s][0], "v0_bar": rows[s][0],
        "line": None, "line_tent": False, "seq": [], "prog": "",
    }

    # 차트 팝업용 일봉 — 1번 봉 5거래일 앞부터 40~55봉
    c_start = max(0, s - 5)
    if n - c_start < 40:
        c_start = max(0, n - 40)
    if n - c_start > 55:
        c_start = max(s, n - 55)
    info["candles"] = [[rows[i][0], round(rows[i][1], 2), round(rows[i][2], 2),
                        round(rows[i][3], 2), round(rows[i][4], 2), int(rows[i][5])]
                       for i in range(c_start, n)]
    info["lu_open"] = round(op[s], 2)     # 1번 봉 시가 — 기준선이 아니라 참고값
    stage_dates = {"1": rows[s][0]}

    def mm(d: str) -> str:
        return d[5:]

    def _lu_note(d: str, first: bool, cnt: int, days: int) -> str:
        head = f"{'첫 상한가' if first else '재상한가'} {mm(d)} · " + ("오늘" if days <= 0 else f"{days}일째")
        return head + (f" · 상한가 {cnt}번" if cnt > 1 else "")

    def _days(n: int) -> str:
        return "오늘" if n <= 0 else f"{n}일"

    def done(stage: int, note: str) -> dict:
        info["stage_dates"] = stage_dates
        return {"stage": stage, "info": info, "note": note}

    # ---- 1번: 상한가 봉이 고점 자리(아직 안 내려옴)
    at_peak = last >= high[p] * 0.98
    if s == n - 1 or at_peak:
        info["prog"] = "고점" if last >= high[p] * 0.995 else "고점 부근"
        return done(1, _lu_note(rows[s][0], first_lu, len(hits), n_day))

    piv = day_pivots(rows, p)
    lows = [i for i, t in piv if t == "L"]
    reb = [i for i in range(p + 1, n)
           if close[i] > op[i] and vol[i] > vol[i - 1] and close[i] > close[i - 1]]

    # ---- 더 높은 자리에서 새로 나온 ②③(한싹 11-17 → 11-18) — 새 그림 기준선으로 갱신(2026-11-21 지시)
    pair = latest_hotbar_pair(rows, s)
    if pair and any(rows[k][4] > high[pair["b3"]] for k in range(pair["b3"] + 1, n)):
        pair = None                                     # ③ 뒤에 고점을 넣었으면 다음 단계로 넘어간 자리

    # ---- 2번: 눌림 — 3번(반등 양봉)이 나오기 전에는 기준선을 미리 긋지 않는다(2026-11-21 지시)
    if not lows and not pair:
        li = min(range(p + 1, n), key=lambda i: low[i]) if p + 1 < n else p
        line = low[li] if p + 1 < n else high[p]
        info.update({"line": None, "line_tent": False, "line_wait": "3번 대기",
                     "line_bar": rows[li][0], "line_body": row_body_clear(rows[li])})
        info["line_pct"] = round((last / line - 1) * 100, 1)
        info["prog"] = "내려오는 중"
        return done(2, f"3번 대기 · 고가 {_pct(info['peak_dd'])} · {_days(after)}")

    if pair:
        line_i, rb, line = pair["b2"], pair["b3"], pair["line"]
    else:
        line_i = lows[0]
        line = low[line_i]
    info["line"] = None                 # 3번이 나온 뒤에야 긋는다(아래 rb 판정)
    info["line_bar"] = rows[line_i][0]
    info["line_body"] = row_body_clear(rows[line_i])
    info["line_pct"] = round((last / line - 1) * 100, 1)
    stage_dates["2"] = rows[line_i][0]

    # 2번에서 3번(첫 반등) 전까지 — 반등이 없으면 아직 눌림 자리
    if not pair:
        rb = next((i for i in reb if i > line_i), None)
    if rb is None:
        info["line_wait"] = "3번 대기"
        if last >= high[p] * 0.99:
            info["prog"] = "고가 위 버팀"
        elif last >= line * 1.03:
            info["prog"] = "줄 위 버팀"
        elif last >= line * 0.97:
            info["prog"] = "줄 닿음"
        else:
            info["prog"] = "줄 아래"
        return done(2, f"3번 대기 · 고가 {_pct(info['peak_dd'])} · {_days(after)} 눌림")

    # ③ 반등 양봉이 실제로 나왔다 — 이제 ② 눌림 저점에 그림 기준선을 긋는다
    info["line"] = round(line, 2)
    info["line_pct"] = round((last / line - 1) * 100, 1)
    info.pop("line_wait", None)
    vr = vol[rb] / vol[rb - 1] if vol[rb - 1] else 0.0
    body = (close[rb] / op[rb] - 1) * 100 if op[rb] else 0.0
    wick = (high[rb] - max(close[rb], op[rb])) / max(close[rb], op[rb]) * 100
    form = "장대" if body >= 7 else ("윗꼬리" if wick > body else "양봉")
    info.update({"rb_date": rows[rb][0], "ratio": round(vr, 2), "rb_body": round(body, 1), "rb_form": form})
    stage_dates["3"] = rows[rb][0]
    # ④ — ③ 뒤 ② 기준선 위 3% 안까지 다시 내려온 첫 봉(10단계 생성기와 같은 잣대 · 2026-11-24)
    #   속도(상한가일→④ 거래일, 25일 안이면 '빠른 ④')와 형태(B = 상한가 봉 고가를 먼저 넘고 내려온 ④)를 잰다.
    d4_i = next((i for i in range(rb + 1, n) if low[i] <= line * 1.03), None)
    if d4_i is not None:
        info["d4_date"] = rows[d4_i][0]
        info["d4_days"] = d4_i - s
        info["d4_type"] = "B" if any(high[k] > high[s] for k in range(s + 1, d4_i + 1)) else "A"

    # 3번 뒤 고점 → 그 다음 저점 = 4번 → 5·6·7…
    after_rb = [(i, t) for i, t in piv if i > rb]
    seq = [{"n": 1, "d": rows[s][0], "p": round(close[s], 2)},
           {"n": 2, "d": rows[line_i][0], "p": round(line, 2)},
           {"n": 3, "d": rows[rb][0], "p": round(close[rb], 2)}]
    top_i = next((i for i, t in after_rb if t == "H"), None)
    num = 3
    if top_i is not None:
        pts_rest = [(i, t) for i, t in after_rb if i > top_i]
        for i, t in pts_rest:
            num = min(DAY_MAX_NUM, num + 1)
            seq.append({"n": num, "d": rows[i][0], "p": round(low[i] if t == "L" else high[i], 2), "k": t})
            stage_dates[str(num)] = rows[i][0]

    info["seq"] = seq

    def pct_vs(pidx: int, t: str) -> float:
        ref = low[pidx] if t == "L" else high[pidx]
        return (last / ref - 1) * 100 if ref else 0.0

    if top_i is None:
        # 3번 반등이 아직 이어지는 중(고점 확인 전)
        info["prog"] = "반등 진행" if rb >= n - 3 else "반등 뒤"
        return done(3, f"3번 {mm(rows[rb][0])} {form} · 거래량 {vr:.1f}배 · 줄 {price_text(line)}")

    # 4번 자리 이후 — 어디에 있는지
    nos = [x for x in info["seq"] if x["n"] >= 4]
    if not nos:
        info["prog"] = "진행"
        return done(4, f"줄 {price_text(line)} · 지금 {info['line_pct']:+.1f}% · 3번 뒤 {n - 1 - rb}일")
    cur = nos[-1]
    if cur["n"] == 4:
        # 4번 아래로 더 빠진 자리 — 테마 있는 종목이면 손절이 아니라 추가매수 자리(2026-11-19 지시)
        lp = info["line_pct"]
        add_ok = bool(theme_ok) and -12 <= lp <= -5
        info["add_buy"] = add_ok
        if last > high[top_i]:
            info["prog"] = "고점 돌파"
        elif abs(lp) <= 3:
            info["prog"] = "줄 닿음"
        elif add_ok:
            info["prog"] = "추가매수 자리"
        elif lp < 0:
            info["prog"] = "줄 아래"
        else:
            info["prog"] = "줄 위"
        return done(4, f"줄 {price_text(line)} · 지금 {info['line_pct']:+.1f}% · 3번 뒤 {n - 1 - rb}일")
    prev = [x for x in info["seq"] if x["n"] == cur["n"] - 1][0]
    chg = (cur["p"] / prev["p"] - 1) * 100 if prev["p"] else 0.0
    info["prog"] = "고점" if cur.get("k") == "H" else "저점"
    info["last_chg"] = round(chg, 1)
    return done(min(cur["n"], DAY_MAX_NUM),
                f"{cur['n']}번 {mm(cur['d'])} {chg:+.1f}% · 지금 {info['line_pct']:+.1f}% · 줄 {price_text(line)}")



# ------------------------------------------------------------ 주봉·월봉 공통 (2026-11-19 개편)
#  푸른하늘님 지시: "주봉.월봉 테마재료 + 이전 거래량들보다 큰 것. 고가 이후 단기 이평선이 역배열이 아님.
#  거래량이 바닥 최소 6개월 횡보 후 시작 거래량으로 배치. 장기 이평선(주봉 240선 위 / 월봉 120선 위).
#  단기이평 20선이 60선을 데드크로스인 경우 = -60% 이상 빠진 뒷자리."
#  → 2026-11-19 22:5x 정정: **뒷자리를 빼지 않고** '앞쪽/뒤쪽'으로 표시한다.
#     앞쪽 = 6개월 조용한 바닥 뒤 시작 거래량 + 20일선이 60일선 위(역배열 아님) + 장기선 아래
#     뒤쪽 = 장기 이평선(주봉 240·월봉 120) 위에 있거나 20일선<60일선(데드크로스)인 자리

def _parts_signature() -> str:
    """10년 원본(hotbar_parts) 서명 — 파일 이름·크기·수정시각. 이게 그대로면 다시 안 읽는다."""
    sig = []
    for path in sorted(glob.glob(os.path.join(DELTA_DIR, "hotbar_parts", "part_*.json.gz"))):
        try:
            st = os.stat(path)
            sig.append(f"{os.path.basename(path)}:{st.st_size}:{int(st.st_mtime)}")
        except OSError:
            continue
    return hashlib.sha1("|".join(sig).encode("utf-8")).hexdigest()[:16] if sig else "none"


def _cache_load(path: str):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _cache_save(path: str, obj) -> None:
    try:
        tmp = path + ".part"
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception as e:
        print(f"⚠ 캐시 저장 실패 {os.path.basename(path)}: {e}", flush=True)


def cluster_table_cached(fresh: bool = False) -> dict[str, dict]:
    """cluster_table() 결과를 10년 원본 서명별로 한 번만 계산해 둔다(2026-11-23).

    30분마다 도는 갱신에서 26초짜리 10년 전수 훑기를 매번 다시 하지 않게 한다.
    선뭉침은 10년 주봉으로 재는 값이라 원본(hotbar_parts)이 그대로면 값도 그대로다.
    """
    path = os.path.join(DELTA_DIR, f"cluster_table_{_parts_signature()}.json.gz")
    if not fresh:
        got = _cache_load(path)
        if isinstance(got, dict) and got:
            print(f"· 선뭉침 표는 캐시에서 읽었습니다({os.path.basename(path)})", flush=True)
            return got
    tab = cluster_table()
    _cache_save(path, tab)
    return tab


def long_history_cached(codes: set[str], fresh: bool = False) -> dict[str, list[list]]:
    """long_history() 결과도 같은 서명으로 한 번만 읽어 둔다 — 2,700종목 파일을 매번 풀지 않는다."""
    path = os.path.join(DELTA_DIR, f"long_history_{_parts_signature()}.json.gz")
    all_hist = None if fresh else _cache_load(path)
    if isinstance(all_hist, dict) and all_hist:
        return {c: all_hist[c] for c in codes if c in all_hist}
    hist = long_history(codes)
    _cache_save(path, hist)
    return hist


def long_history(codes: set[str]) -> dict[str, list[list]]:
    """10년 일봉 원본(brain/cache/hotbar_parts)에서 **테마 종목만** 골라 읽는다.

    주봉 240선·월봉 120선은 450봉(약 21개월) 캐시로는 잴 수 없어 2015-06~ 원본이 필요하다.
    2,770종목을 다 메모리에 올리지 않고 테마 종목(약 410개)만 담는다 — 오늘 봉은 analyze()가 이어 붙인다.
    """
    out: dict[str, list[list]] = {}
    for path in sorted(glob.glob(os.path.join(DELTA_DIR, "hotbar_parts", "part_*.json.gz"))):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                daily = (json.load(f) or {}).get("daily") or {}
        except Exception:
            continue
        for c, rows in daily.items():
            if c in codes and rows:
                out[c] = rows
    return out


def merged_rows(hist: dict[str, list[list]] | None, code: str, rows: list[list]) -> list[list]:
    """10년 원본 + 오늘 캐시 — 겹치는 구간은 오늘 캐시(최신)를 쓴다."""
    old = (hist or {}).get(code) or []
    if not old:
        return rows
    if not rows:
        return old
    cut = rows[0][0]
    return [r for r in old if r[0] < cut] + rows


def sma(vals: list[float], n: int) -> float | None:
    """단순이평 — 봉이 모자라면 None(그 선은 그 자리에 없다)."""
    return sum(vals[-n:]) / n if len(vals) >= n else None


def ma_series(closes: list[float], n: int) -> list:
    """봉마다의 단순이동평균 배열 — 차트가 봉과 한 칸씩 맞춰 긋는 선.

    2026-11-23 지시 "일봉 240선 주봉240선 월봉120선 넣어줘 하늘색".
    앞 n-1봉은 그 선이 아직 없으므로 None(그 자리에는 선을 긋지 않는다), 나머지는 원 단위 정수.
    길이는 넣은 봉 개수와 반드시 같다 — 차트가 봉 i 의 선 값을 series[i] 로 읽는다.
    """
    out: list = []
    run = 0.0
    for i, v in enumerate(closes):
        run += float(v or 0)
        if i >= n:
            run -= float(closes[i - n] or 0)
        out.append(int(round(run / n)) if i >= n - 1 else None)
    return out


def body_clear(b: dict) -> bool:
    """그 봉이 양봉인지 음봉인지 눈으로 구분되는가 — 도지·몸통 없는 봉이면 False."""
    rng = b["h"] - b["l"]
    body = abs(b["c"] - b["o"])
    if rng <= 0 or not b["o"]:
        return False
    return (body / rng) >= BODY_MIN and (body / b["o"] * 100) >= BODY_MIN_PCT


def prep_base_line(item: dict) -> str | None:
    """그림 기준선(② 눌림 저점 가로선)을 그릴지 정한다 — 2026-11-21 푸른하늘님 지시로 바로잡음.

    "핫바탭 기준선은 가격 기준선이 아님. 어제올린그림과 차트 그리고 내가 이해한 핫바 봉 임"
      ① 상한가 → ② 하락 음봉(눌림) → ③ 반등 양봉(핫바)이 **실제로 나온 뒤**에야
      ② 저점에 가로선을 긋고, ④ 그 선까지 다시 내려올 때 사는 자리로 본다.
    · ③(3번)이 아직 없으면 선을 미리 긋지 않고 '3번 대기'로 둔다.
    · 3번 뒤에도 선은 그대로 둔다 — 4번(추가매수)을 재는 자리다.
    돌려주는 값: '남김' · '3번 대기' · '양봉·음봉 불분명'
    """
    st = item.get("stage") or 0
    line = item.get("line")
    if st < 3 or line is None:
        item["line"] = None
        item["base_open"] = None
        item["line_off"] = "3번 대기"
        item["line_wait"] = "3번 대기"
        return "3번 대기"
    ok = item.get("b1_body") if item.get("period") in ("week", "month") else item.get("line_body")
    if ok is False:
        item["line"] = None
        item["base_open"] = None
        item["line_off"] = "양봉·음봉 불분명"
        return "도지·몸통 없음"
    item["base_open"] = line          # 차트가 긋는 자리 = 그림 기준선(② 저점)
    item["line_off"] = None
    item.pop("line_wait", None)
    return "남김"


def row_body_clear(r: list) -> bool:
    """일봉 한 줄([날짜,시,고,저,종,거래량])이 양봉/음봉으로 구분되는가 — 도지면 False."""
    rng, body = r[2] - r[3], abs(r[4] - r[1])
    if rng <= 0 or not r[1]:
        return False
    return (body / rng) >= BODY_MIN and (body / r[1] * 100) >= BODY_MIN_PCT


def bar_pivots(B: list[dict], start: int) -> list[tuple[int, str]]:
    """주봉·월봉 고점(H)·저점(L) — 양 옆 봉보다 확실히 높거나 낮은 자리만(일봉 day_pivots 와 같은 잣대)."""
    pts: list[tuple[int, str]] = []
    for i in range(start + 1, len(B) - 1):
        if B[i]["l"] < B[i - 1]["l"] and B[i]["l"] < B[i + 1]["l"]:
            pts.append((i, "L"))
        elif B[i]["h"] > B[i - 1]["h"] and B[i]["h"] > B[i + 1]["h"]:
            pts.append((i, "H"))
    out: list[tuple[int, str]] = []
    for i, t in pts:
        if out and out[-1][1] == t:
            j = out[-1][0]
            if (t == "L" and B[i]["l"] < B[j]["l"]) or (t == "H" and B[i]["h"] > B[j]["h"]):
                out[-1] = (i, t)
        else:
            out.append((i, t))
    return out


def tf_start_bars(B: list[dict], look: int, scan: int, full_days: int) -> list[int]:
    """시작 거래량 후보 — 최근 scan봉 안에서
       ① 뚜렷한 양봉(도지·몸통 없는 봉은 1번이 아니다 — 사진 3장의 뚜렷한 빨간 몸통)
       ② 앞 look봉(주봉 26주·월봉 6개월) 최대 거래량을 **뚜렷하게(START_MULT 2배)** 넘는 거래량
          — 진행 중인 이번 주·이번 달 봉은 환산 거래량으로 잰다.
       ③ 그 직전 종가가 6개월 최저가 근처(바닥)였던 봉.
    이른 봉부터 돌려준다 — 핫바는 고점 뒤 반짝이 아니라 '앞쪽 시작 거래량' 자리에 세운다.
    2026-11-20 정리: '+1%·+0%' 같은 약한 봉, 6개월 최대의 1.0~1.8배짜리 어중간한 봉,
    도지·몸통 없는 봉이 1번 칸에 섞이던 것을 걷어낸다(푸른하늘님 "주봉.월봉은 지금사진 처럼 1번으로 정리 해").
    """
    n = len(B)
    out: list[int] = []
    for k in range(max(look + 1, n - scan), n):
        b = B[k]
        if b["c"] <= b["o"]:
            continue
        if not body_clear(b):          # 도지·몸통 없는 봉은 '1번 거래량 양봉'이 아니다
            continue
        base = B[k - look:k]
        pv = max((x["v"] for x in base), default=0.0)
        if not pv:
            continue
        v = vol_pace(b, full_days) if k == n - 1 else b["v"]   # 이번 주·이번 달은 아직 차는 중
        if v < pv * START_MULT:
            continue
        # 바닥권 출발 — 1년 고점 대비 -40% 이상 빠진 자리(고점 뒤 반짝이 아니라 바닥에서 시작)
        yr = B[max(0, k - 52):k] or B[:k]
        hi52 = max(x["h"] for x in yr)
        if not hi52 or B[k - 1]["c"] > hi52 * BOTTOM_1Y:
            continue
        out.append(k)
    return out


def _lu_flags(rows: list[list]) -> list[bool]:
    """상한가 봉 — build_hotbar_buy(stage10_core.lu_flags)와 같은 잣대(+29.5% 또는 고가=종가 +27%+)."""
    out = [False] * len(rows)
    for i in range(1, len(rows)):
        p = rows[i - 1][4]
        r = rows[i][4] / p - 1 if p else 0
        if r >= 0.295 or (0.27 <= r < 0.295 and rows[i][2] == rows[i][4]):
            out[i] = True
    return out


def pullback_entry(daily_rows: list[list]) -> tuple[bool, str]:
    """큰 테마 초입 -40% 내외 조정 뒤 2차 핫바가 기준선을 지키는 자리인가 (2026-11-25 지시).

    · 고점 대비 -20~-45%만 식히고 출발선(1파 직전 종가)은 안 반납
    · 조정 뒤 새 상한가(2차 핫바)가 최근 40봉 안에 붙어 그 봉 시가를 지킴
    인디에프처럼 -50% 이상 밀려 출발선까지 다 반납한 자리는 걸리지 않는다(뒤쪽 유지).
    """
    rows = daily_rows or []
    n = len(rows)
    if n < 60:
        return False, ""
    win = rows[-125:]
    first = next((i for i in range(1, len(win))
                  if win[i - 1][4] and win[i][4] / win[i - 1][4] - 1 >= 0.15), None)
    if first is None:
        return False, ""
    peak_i = max(range(first, len(win)), key=lambda i: win[i][2])
    peak, c = win[peak_i][2], rows[-1][4]
    if not peak or not c:
        return False, ""
    drop = c / peak - 1
    if not (-0.45 <= drop <= -0.20):
        return False, ""
    off = n - len(win)
    luf = _lu_flags(rows)
    lus = [i for i in range(max(1, off), n) if luf[i] and i > off + peak_i]
    if not lus or (n - 1 - lus[-1]) > 40:
        return False, ""
    last_lu = lus[-1]
    launch = win[max(0, first - 1)][4]
    if launch and c <= launch * 1.10:
        return False, ""
    if c < rows[last_lu][1] * 0.95:
        return False, ""
    return True, "큰 테마 초입 %+.0f%% 조정 뒤 %s 2차 핫바 · 시가 사수" % (
        drop * 100, str(rows[last_lu][0])[5:].replace("-", "."))


def wave_done(daily_rows: list[list]) -> tuple[bool, str]:
    """최근 125봉 안에 큰 급등(15%+) 파동이 생겼다가 끝나 꺾여 내려온 자리인가 (2026-11-25 지시).

    앞쪽(진짜) = 앞에 큰 파동 없이 깊은 바닥에서 막 첫 상한가가 나온 초입 · 한싹처럼 첫 상한가 뒤
    기준선·추세를 깨지 않고 버티는 자리 / 뒤쪽 = 125봉 안 파동 고점 뒤 20% 이상 밀리고
    20일선까지 깨 내려온 자리(인디에프·에스피소프트·SGA솔루션즈).
    -50% 이상 빠져 출발선까지 반납한 자리는 확실히 뒤쪽, 큰 테마 초입 -40% 조정 뒤 2차 핫바가
    붙어 기준선을 지키는 자리는 버리지 않는다.
    """
    rows = daily_rows or []
    if len(rows) < 30:
        return False, ""
    win = rows[-125:]
    first = None
    for i in range(1, len(win)):
        if win[i - 1][4] and win[i][4] / win[i - 1][4] - 1 >= 0.15:
            first = i
            break
    if first is None:
        return False, ""
    peak_i = max(range(first, len(win)), key=lambda i: win[i][2])
    peak, c = win[peak_i][2], rows[-1][4]
    if not peak or not c:
        return False, ""
    drop = c / peak - 1
    dcl = [r[4] for r in rows]
    d20, d60 = sma(dcl, 20), sma(dcl, 60)
    broken = bool((d20 and c < d20) or (d20 and d60 and d20 < d60))
    if drop <= -0.50:
        return True, f"125봉 파동 고점({peak:,.0f}) 뒤 {drop * 100:+.0f}% · 출발선까지 반납"
    if pullback_entry(rows)[0]:
        return False, ""
    if drop <= -0.20 and broken and (len(win) - 1 - peak_i) >= 3:
        return True, f"125봉 파동 고점({peak:,.0f}) 뒤 {drop * 100:+.0f}% · 추세 이탈"
    return False, ""


def tf_stage(B: list[dict], daily_rows: list[list], look: int, scan: int,
             long_n: int, unit: str) -> dict | None:
    """주봉·월봉 1·2·3 — '바닥 6개월 조용한 거래량 → 시작 거래량' 하나만 따라간다.

    1번 = 시작 거래량 봉(이번/지난 주·달)  2번 = 그 뒤 눌림(1번 시가 안 깨고)
    3번 = 눌림 뒤 거래량 실린 첫 양봉(이번/지난 주·달). 그 뒤로 지나면 싣지 않는다.
    앞/뒤: 장기 이평선(주봉 240·월봉 120) 위이거나 20일선<60일선(데드크로스)이면 '뒤쪽'.
    """
    n = len(B)
    if n < look + 3:
        return None
    starts = tf_start_bars(B, look, scan, WEEK_DAYS if unit == "주" else MONTH_DAYS)
    if not starts:
        return None
    k = starts[0]
    start = B[k]
    closes = [b["c"] for b in B]
    last = closes[-1]
    prev_c = B[k - 1]["c"]
    pv = max(x["v"] for x in B[k - look:k])
    lo = min(x["l"] for x in B[k - look:k])

    # ---- 앞/뒤 판정 (2026-11-19 22:5x 정정 — 빼지 않고 표시)
    dcl = [r[4] for r in daily_rows] if daily_rows else closes
    d20, d60 = sma(dcl, 20), sma(dcl, 60)
    dead = d20 is not None and d60 is not None and d20 < d60
    long_ma = sma(closes, long_n)
    above = (last > long_ma) if long_ma else None
    # 2026-11-25 지시 — 이미 큰 파동이 끝나 꺾여 내려온 자리는 '뒤쪽'(깊은 바닥 첫 출발은 살린다)
    #   단 큰 테마 초입 -40% 조정 뒤 2차 핫바가 기준선을 지키는 자리는 '초입'으로 따로 남긴다.
    over, over_why = wave_done(daily_rows or [])
    early, early_why = pullback_entry(daily_rows or [])
    pos2 = ("뒤쪽" if over else ("초입" if (above and early) else
            ("뒤쪽" if (dead or above) else "앞쪽")))
    why: list[str] = []
    if over:
        why.append(over_why)
    elif above and early:
        why.append(early_why)
    if dead:
        why.append("20일선<60일선")
    if above and not early:
        why.append(f"{unit}봉{long_n}선 위 +{(last / long_ma - 1) * 100:.0f}%")

    full_days = WEEK_DAYS if unit == "주" else MONTH_DAYS
    partial = (k == n - 1) and start.get("days", full_days) < full_days
    v_pace = vol_pace(start, full_days)
    chg = (start["c"] / prev_c - 1) * 100 if prev_c else 0.0
    label = (f"{start['start'][5:]}~{start['end'][5:]}" if unit == "주" else start["k"])
    info = {
        "ratio": round(start["v"] / pv, 2) if pv else None,
        "ratio_pace": round(v_pace / pv, 2) if pv else None, "bar_partial": partial,
        "week": label if unit == "주" else None, "month": start["k"] if unit == "월" else None,
        "v0": int(start["v"]), "v0_start": start["start"], "v0_bar": label,
        "b1_date": start["end"], "b1_open": round(start["o"], 2),
        "b1_body": body_clear(start),
        "ref_vol": int(pv), "bar_vol": int(start["v"]), "ref_bars": look,
        "chg": round(chg, 1), "start_gap_low": round((prev_c / lo - 1) * 100, 1) if lo else None,
        "mid_band": round((max(closes[k - look:k]) / min(closes[k - look:k]) - 1) * 100, 1),
        "ma20_d": round(d20, 2) if d20 else None, "ma60_d": round(d60, 2) if d60 else None,
        "dead": dead, "ma_long": round(long_ma, 2) if long_ma else None,
        "long_bars": n, "long_need": long_n,
        "above_long": above, "pos2": pos2, "pos2_why": why,
    }
    if info["week"] is None:
        info.pop("week")
    if info["month"] is None:
        info.pop("month")

    keep = last > start["o"]                       # 시작 봉 몸통을 다 토해내지 않았나
    reb = next((i for i in range(k + 1, n)
                if B[i]["c"] > B[i]["o"] and B[i]["v"] > B[i - 1]["v"] and B[i]["c"] > B[i - 1]["c"]), None)
    tail = f" · {pos2}" + (f" (이번 {unit} 진행 중 · 환산 {info['ratio_pace']:.1f}배)" if partial else "")
    if k == n - 1:
        return {"stage": 1, "info": info,
                "note": f"{label} 시작 거래량 {chg:+.0f}% · 6개월 최대의 {info['ratio']:.1f}배{tail}"}
    if k == n - 2:
        now = B[n - 1]
        if now["c"] < now["o"] and now["v"] < start["v"] and keep:
            return {"stage": 2, "info": info,
                    "note": f"{label} 시작 뒤 눌림 · 6개월 최대의 {info['ratio']:.1f}배{tail}"}
        return {"stage": 1, "info": info,
                "note": f"{label} 시작 거래량 {chg:+.0f}% · 6개월 최대의 {info['ratio']:.1f}배{tail}"}
    if reb is None:
        if keep:
            return {"stage": 2, "info": info,
                    "note": f"{label} 시작 뒤 눌림 · 6개월 최대의 {info['ratio']:.1f}배{tail}"}
        return None
    if reb >= n - 2:
        info["b3_date"] = B[reb]["end"]
        # ② 눌림 저점 = 그림 기준선 — ③ 반등 양봉이 나왔으니 이제 긋는다
        b2bars = B[k + 1:reb]
        if b2bars:
            b2 = min(range(k + 1, reb), key=lambda i: B[i]["l"])
            line2 = B[b2]["l"]
            b2_date = B[b2]["end"]
        else:                     # 1번 바로 다음 봉이 3번 — 눌림 봉이 없으면 1번 봉 저점을 줄로
            line2, b2_date = B[k]["l"], B[k]["end"]
        info.update({"line": round(line2, 2), "line_pct": round((last / line2 - 1) * 100, 1),
                     "b2_date": b2_date})
        return {"stage": 3, "info": info,
                "note": f"{label} 시작 뒤 첫 반등 {(B[reb]['c'] / B[reb - 1]['c'] - 1) * 100:+.0f}% · 거래량 {B[reb]['v'] / B[reb - 1]['v']:.1f}배{tail}"}

    # ---- 4번: 3번 반등 뒤 다시 2번 눌림 저점(기준선) 부근까지 내려온 재확인 자리
    #      2026-11-21 지시 — 기준선은 가격이 아니라 그림(② 저점)이다.
    #      줄을 깨고 내려오면 그림 깨짐이라 싣지 않고, 아직 줄 근처로 안 내려왔으면 3번 진행으로 본다.
    line = info.get("line") or min((x["l"] for x in B[k + 1:reb]), default=start["l"])
    lp = (last / line - 1) * 100 if line else 0.0
    high3 = max((x["h"] for x in B[reb + 1:]), default=None)
    low3 = min((x["l"] for x in B[reb + 1:]), default=None)
    touch = next((i for i in range(reb + 1, n) if B[i]["l"] <= line * LINE_NEAR), None)
    info.update({"line": round(line, 2), "line_pct": round(lp, 1), "b3_date": B[reb]["end"],
                 "high3": round(high3, 2) if high3 else None,
                 "low3": round(low3, 2) if low3 else None})
    if last < line * LINE_KEEP:
        return None                       # 기준선을 깨고 내려왔다 — 그림 깨짐
    if touch is None:
        return None                       # 아직 줄 근처로 안 내려왔다 — 3번 반등이 이어지는 중
    info["b4_date"] = B[touch]["end"]
    # ---- 5번부터: 4번 뒤 고점·저점을 번갈아 5·6·7…12번 (2026-11-20 지시 "주·월봉 5번 이후도 일봉처럼")
    seq = [{"n": 1, "d": start["end"]}, {"n": 3, "d": B[reb]["end"]}, {"n": 4, "d": B[touch]["end"]}]
    num = 4
    for i, t in bar_pivots(B, touch):
        num = min(TF_MAX_NUM, num + 1)
        seq.append({"n": num, "d": B[i]["end"], "k": t,
                    "p": round(B[i]["l"] if t == "L" else B[i]["h"], 2)})
        if num >= TF_MAX_NUM:
            break
    info["seq"] = seq
    if num > 4:
        cur = seq[-1]
        return {"stage": cur["n"], "info": info,
                "note": f"{label} 4번 뒤 {cur['n']}번 {cur['d'][5:]} · 줄 {price_text(line)} 대비 {lp:+.0f}%"}
    return {"stage": 4, "info": info,
            "note": f"{label} 3번 뒤 다시 줄 {price_text(line)} · 지금 {lp:+.0f}% · 3번 뒤 {n - 1 - reb}{unit}"}


def week_stage(rows: list[list], wk: list[dict] | None = None,
               daily_rows: list[list] | None = None) -> dict | None:
    """주봉 1·2·3 — 바닥 6개월 조용한 뒤 시작 거래량 (2026-11-19 개편)."""
    if len(rows) < 60:
        return None
    wk = wk or make_bars(rows, week_key)
    return tf_stage(wk, daily_rows or rows, WEEK_LOOKBACK, WEEK_SCAN, WEEK_MA_LONG, "주")


def month_stage(rows: list[list], mo: list[dict] | None = None,
                daily_rows: list[list] | None = None) -> dict | None:
    """월봉 1·2·3 — 바닥 6개월 조용한 뒤 시작 거래량 (2026-11-19 개편)."""
    if len(rows) < 120:
        return None
    mo = mo or make_bars(rows, month_key)
    return tf_stage(mo, daily_rows or rows, MONTH_LOOKBACK, MONTH_SCAN, MONTH_MA_LONG, "월")


# ------------------------------------------------------------------ 월봉 차트용 긴 시세
def fetch_bars(symbol: str, timeframe: str, count: int) -> list[list]:
    """네이버 fchart 봉(timeframe=week|month) — 날짜는 그 봉의 마지막 거래일."""
    url = (f"https://fchart.stock.naver.com/sise.nhn?symbol={symbol}"
           f"&timeframe={timeframe}&count={count}&requestType=0")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("euc-kr", errors="replace")
        root = ET.fromstring(raw)
        out = []
        for item in root.findall(".//item"):
            p = item.attrib.get("data", "").split("|")
            if len(p) < 6 or "null" in p[1:5]:
                continue
            d = p[0]
            out.append([f"{d[:4]}-{d[4:6]}-{d[6:8]}", float(p[1]), float(p[2]),
                        float(p[3]), float(p[4]), float(p[5])])
        return out
    except Exception:
        return []


MONTH_RX = re.compile(r'\["(\d{8})"\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)')
MONTH_LONG_START = "20130101"      # 120개월선을 재려면 10년보다 조금 넉넉하게


def fetch_month_long(symbol: str, start: str = MONTH_LONG_START) -> list[list]:
    """월봉 10년이상 — fchart 는 월봉을 120개월까지만 주므로 siseJson(2013~)으로 받는다.

    월봉 120개월선(10년)은 120 + 차트에 실을 달(30)이 필요하다. 봉 날짜는 그 달의 마지막 거래일.
    """
    end = datetime.now(KST).strftime("%Y%m%d")
    url = (f"https://api.finance.naver.com/siseJson.naver?symbol={symbol}&requestType=1"
           f"&startTime={start}&endTime={end}&timeframe=month")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("euc-kr", errors="replace")
        out = []
        for d, o, h, l, c, v in MONTH_RX.findall(raw):
            out.append([f"{d[:4]}-{d[4:6]}-{d[6:8]}", float(o), float(h), float(l), float(c), float(v)])
        return out
    except Exception:
        return []


def _ma_map(rows: list[list], n: int) -> dict:
    """봉 날짜 → 그 봉의 n봉 단순이평 (값이 있는 자리만)."""
    rows = sorted([r for r in (rows or []) if r], key=lambda r: r[0])
    ser = ma_series([r[4] for r in rows], n)
    return {r[0]: ser[i] for i, r in enumerate(rows) if ser[i] is not None}


def _bar_ma_map(bars: list[dict], n: int) -> dict:
    """make_bars 로 묶은 주봉·월봉에서 봉 끝날짜 → n봉 단순이평."""
    ser = ma_series([b["c"] for b in bars], n)
    return {b["end"]: ser[i] for i, b in enumerate(bars) if ser[i] is not None}


def fill_long_ma(sec: dict, today: str, workers: int = 8) -> None:
    """모든 카드의 하늘색 장기선 — 주봉 240주 · 월봉 120개월 (2026-11-23 지시).

    10년 원본(brain/cache/hotbar_parts)이 있는 테마 종목은 이미 analyze()가 값을 실어 왔다.
    원본이 없는 종목(테마 밖 상한가·10단계 종목)은 네이버에서 주봉 300주·월봉 10년을 받아
    **봉 날짜로 맞춰** 채운다 — 봉이 모자란 앞 구간은 None 그대로(선을 안 긋는다).
    받은 표는 하루 한 번만 받도록 brain/cache/tf_long_ma_YYYYMMDD.json.gz 에 둔다.
    """
    jobs: list[tuple[dict, list, str, str]] = []      # (카드, 봉배열, 채울 칸, 'w'|'m')

    def want(item, bars, field, kind):
        if not bars:
            return
        cur = item.get(field) or []
        if any(v is not None for v in cur):
            return                                   # 이미 값이 있다 — 그대로 둔다
        jobs.append((item, bars, field, kind))

    for k in STAGE_ORDER:
        for s in STAGE_ORDER[k]:
            for it in sec[k].get(s) or []:
                if k == "day":
                    want(it, it.get("w"), "w_ma240", "w")
                    want(it, it.get("m"), "m_ma120", "m")
                elif k == "week":
                    want(it, it.get("candles"), "w_ma240", "w")
                else:
                    want(it, it.get("candles"), "m_ma120", "m")
    if not jobs:
        return

    cache_path = os.path.join(DELTA_DIR, f"tf_long_ma_{today.replace('-', '')}.json.gz")
    cache: dict = {}
    if os.path.exists(cache_path):
        try:
            with gzip.open(cache_path, "rt", encoding="utf-8") as f:
                cache = json.load(f) or {}
        except Exception:
            cache = {}

    todo = {(str(it["code"]), kind) for it, _b, _f, kind in jobs}
    todo = {(c, k) for c, k in todo if k not in (cache.get(c) or {})}
    got = 0
    if todo:
        codes_todo = sorted({c for c, _k in todo})
        # ① 10년 일봉 원본(brain/cache/hotbar_parts) — 네이버가 8~10년에서 끊는 종목도 여기엔 10년이 있다.
        #    오늘 봉은 오늘 시세 캐시로 이어 붙인다(끝 봉까지 선이 이어지게).
        hist = long_history(set(codes_todo))
        if hist:
            print(f"10년 원본에서 장기선 재는 종목 {len(hist)} — 하늘색 장기선", flush=True)
            today_rows = {c: r for c, r in iter_delta(today) if c in hist}
            for code, _o in hist.items():
                rows = merged_rows(hist, code, today_rows.get(code) or [])
                rec = cache.setdefault(code, {})
                if "w" not in rec:
                    rec["w"] = _bar_ma_map(make_bars(rows, week_key), 240)
                if "m" not in rec:
                    rec["m"] = _bar_ma_map(make_bars(rows, month_key), 120)
        # ② 원본에 없는 종목만 네이버에서 — 주봉 300주, 월봉 10년치(실패하면 120개월)
        naver = [(c, k) for c, k in sorted(todo) if c not in hist]

        def long_map(code: str, kind: str):
            rows = (fetch_bars(code, "week", 300) if kind == "w"
                    else (fetch_month_long(code) or fetch_bars(code, "month", 160)))
            return code, kind, (_ma_map(rows, 240 if kind == "w" else 120) if rows else None)

        if naver:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                for code, kind, mp in ex.map(lambda t: long_map(t[0], t[1]), naver):
                    if mp is None:
                        continue                  # 못 받았으면 캐시에 안 넣는다 — 다음 실행에 다시
                    cache.setdefault(code, {})[kind] = mp
        with gzip.open(cache_path, "wt", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))

    for it, bars, field, kind in jobs:
        mp = (cache.get(str(it["code"])) or {}).get(kind) or {}
        if not mp:
            continue
        vals = [mp.get(str(b[0])) for b in bars]
        if any(v is not None for v in vals):
            it[field] = vals
            got += 1
    print(f"하늘색 장기선 — {len(jobs)}칸 중 {got}칸 채움", flush=True)


def enrich_month_candles(month_sec: dict, base_date: str) -> None:
    """월봉 카드의 차트를 24~36개월로 넓힌다.

    오늘 시세 캐시는 450봉(약 21개월)이라 그보다 앞선 달만 네이버 월봉에서 받아 붙인다.
    받는 달은 이미 끝난 달이라 장중 값이 섞이지 않고, 겹치는 달은 캐시 값(기준일 종가 기준)을 쓴다.
    """
    items = [x for s in month_sec.values() for x in s]
    if not items:
        return
    got = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_bars, x["code"], "month", 36): x for x in items}
        for fut in as_completed(futs):
            it = futs[fut]
            cs = it.get("candles") or []
            if not cs:
                continue
            first_key = str(cs[0][0])[:7]
            older = [b for b in (fut.result() or []) if b[0][:7] < first_key]
            if not older:
                continue
            older = [[b[0], round(b[1], 2), round(b[2], 2), round(b[3], 2), round(b[4], 2), int(b[5])]
                     for b in older]
            it["candles"] = (older + cs)[-30:]
            got += 1
    print(f"월봉 차트 30개월 채움 {got}/{len(items)}종목", flush=True)


# ------------------------------------------------------------------ 종목 한 건
def price_text(p: float) -> str:
    return f"{int(round(p)):,}원"


def analyze(code: str, name: str, rows: list[list], tmap: dict | None = None,
            amax: dict | None = None, newsmap: dict | None = None,
            aplus: dict | None = None, long_rows: list[list] | None = None,
            drop_off: list | None = None, cltab: dict | None = None) -> dict | None:
    if len(rows) < MIN_DAYS_DAY:
        return None
    n = len(rows)
    close, vol = rows[-1][4], rows[-1][5]
    amt3 = statistics.mean([rows[i][4] * rows[i][5] for i in range(n - 3, n)])
    thin = amt3 < MIN_AMT3          # 얇은 종목 — 일봉에는 싣고 딱지, 주봉·월봉은 싣지 않는다
    prev = rows[-2][4] if n > 1 else close
    hi = max(r[2] for r in rows[-250:]) if n >= 60 else max(r[2] for r in rows)
    dd = int(round((close / hi - 1) * 100))
    base = {
        "code": code, "name": name,
        "price": int(round(close)), "price_text": price_text(close),
        "chg": round((close / prev - 1) * 100, 2),
        "dd": dd,
        "bottom": dd <= BOTTOM_DD,        # 1년 고점 대비 -45% 이하 = 바닥권(카드에 배지로 강조)
        "base_date": rows[-1][0],
        "thin": thin,
        "themes": bar((tmap or {}).get(code), 3),
    }
    out = {}
    lr = long_rows if (long_rows and len(long_rows) > len(rows)) else rows
    wk = make_bars(lr, week_key)          # 주봉·월봉은 10년 원본까지 붙인 봉으로 잰다(240선·120선)
    mo = make_bars(lr, month_key)
    # 차트에 봉과 나란히 그을 하늘색 장기선 — 주봉 240주선 · 월봉 120개월선(2026-11-23 지시).
    #   일봉 240선은 아래에서 오늘 봉(rows)으로 잰다. 봉 모자란 앞 구간은 None 이라 선을 안 긋는다.
    wk_ma240 = ma_series([b["c"] for b in wk], 240)
    mo_ma120 = ma_series([b["c"] for b in mo], 120)
    osc = osc_pos(lr)                     # 480봉 0~100 눈금 (2026-11-20 상위 버전)
    am = (amax or {}).get(code) or {}
    reason, theme = reason_of(code, tmap, newsmap)
    keep, off_why = material_ok(theme, reason)          # 진짜 무재료 종목만 뺀다(2026-11-19 정정)
    label = theme_label(theme, reason)                  # 카드 오른쪽 — 테마명 또는 '개별 · 키워드'
    theme_ok = bool(theme) and not is_indiv_theme(theme)  # 테마가 확실한 종목(개별은 맨 아래로)
    for key, fn in (("day", lambda: day_stage(rows, theme_ok)),
                    ("week", lambda: week_stage(lr, wk, lr)),
                    ("month", lambda: month_stage(lr, mo, lr))):
        if key != "day" and (thin or len(rows) < MIN_DAYS):
            continue
        st = fn()
        if not st:
            continue
        if not keep:
            # 테마도 없고 확인된 재료도 없는 종목만 뺀다. 뺀 종목은 보고용으로 모아 둔다.
            if drop_off is not None:
                drop_off.append({"key": key, "stage": st["stage"], "code": code, "name": name,
                                 "why": off_why, "theme": theme, "reason": reason,
                                 "date": rows[-1][0]})
            continue
        item = {**base, "stage": st["stage"], "note": st["note"], **st["info"]}
        if osc:
            item.update(osc)              # 지금이 480봉 위에서 몇 점인지 — 카드·차트 작은 숫자
        # 선뭉침 — 10년 주봉 240주 기준(테이블에서 종목코드로 가져온다). 숫자는 그대로 싣는다.
        cl = (cltab or {}).get(code)
        if cl:
            item.update(cl)               # 선뭉침 여부 + 잰 숫자(간격·하단·거리·거래량 배수)
        item["reason"] = reason          # 카드에 함께 보이는 재료 한 줄
        item["theme"] = theme            # 테마 DB·달력 이름(없으면 '')
        item["theme_label"] = label      # 카드 오른쪽에 보이는 글자 — 테마명 또는 '개별 · 수주'
        item["theme_ok"] = theme_ok      # 테마가 확실한지(정렬·묶음용)
        item["period"] = key             # 차트 팝업이 어느 봉인지 안다(일봉/주봉/월봉)
        if key != "day":
            # 주봉·월봉 카드도 차트를 연다(2026-11-19 지시 "핫바탭 1.2.3번도 차트 보게") —
            # 최근 52주봉·30월봉을 그대로 싣고, 1번 봉 날짜를 마커로 쓴다.
            bars = wk if key == "week" else mo
            k = 52 if key == "week" else 30
            item["candles"] = [[b["end"], round(b["o"], 2), round(b["h"], 2), round(b["l"], 2),
                                round(b["c"], 2), int(b["v"])] for b in bars[-k:]]
            # 주봉 카드면 240주선, 월봉 카드면 120개월선 — 이 카드의 봉과 한 칸씩 맞춘 배열
            if key == "week":
                item["w_ma240"] = wk_ma240[-k:]
            else:
                item["m_ma120"] = mo_ma120[-k:]
            item["lu_date"] = st["info"].get("b1_date")
            item["lu_open"] = st["info"].get("b1_open")   # 1번 시가 — 기준선이 아니라 참고값
            item["rb_date"] = st["info"].get("b3_date")
            sd = {k2: v for k2, v in (("1", st["info"].get("b1_date")),
                                      ("3", st["info"].get("b3_date")),
                                      ("4", st["info"].get("b4_date"))) if v}
            for q in (st["info"].get("seq") or []):     # 5·6·7… 도 차트에 번호로 찍는다
                if q.get("n") and q.get("d") and q["n"] >= 5:
                    sd[str(q["n"])] = q["d"]
            item["stage_dates"] = sd
        if key == "day":
            # 2026-11-25 지시 — 일봉 카드도 '앞쪽/뒷쪽'을 **차트 자리**로 잰다(거래량 비율 pos 와 별개).
            #   이미 125봉 안에 큰 파동이 생겼다가 끝나 꺾여 내려온 자리(인디에프·에스피소프트·
            #   SGA솔루션즈)는 뒷쪽 — 오늘 픽(팝업)에서도 이 값으로 거른다.
            _dcl = [r[4] for r in rows]
            _d20, _d60 = sma(_dcl, 20), sma(_dcl, 60)
            _w240, _m120 = sma([b["c"] for b in wk], 240), sma([b["c"] for b in mo], 120)
            _c = _dcl[-1] if _dcl else 0
            _over, _over_why = wave_done(rows)
            _early, _early_why = pullback_entry(rows)
            _above = bool((_w240 and _c > _w240) or (_m120 and _c > _m120))
            _dead = bool(_d20 and _d60 and _d20 < _d60)
            # 2026-11-25 — 큰 테마 초입 -40% 조정 뒤 2차 핫바가 기준선을 지키는 자리는
            #   '뒷쪽'으로 버리지 않고 **'초입'**으로 따로 세운다(팝업·레이더 필터에서도 살아남는다).
            item["pos2"] = ("뒷쪽" if _over else
                            ("초입" if _early else
                             ("뒷쪽" if (_dead or _above) else "앞쪽")))
            item["pos2_why"] = [x for x in ([_over_why] if _over else [])
                                + ([_early_why] if (_early and not _over) else [])
                                + (["20일선<60일선"] if (_dead and not _over and not _early) else [])
                                + (["장기 이평선 위"] if (_above and not _early and not _over) else []) if x]
            # 1단계 첫 단추 — 테마 크기·240선 위/아래·첫 거래량을 한눈에 (2026-11-21 지시)
            if st["stage"] == 1:
                i0 = next((i for i in range(len(rows) - 1, -1, -1)
                           if rows[i][0] == st["info"].get("lu_date")), None)
                item["ma240_side"] = ma240_side(rows, i0)     # '위'/'아래' 글자(선은 아래 ma240 배열)
                item["v1x"], item["fvol"] = first_vol(rows, i0)
            # 분홍 ↑(후보 G) — 240·448선 아래 바닥에서 5·20·33·전환·기준선을 한꺼번에 넘어선
            #   양봉이 난 날. 차트에 그리는 자리만 담는다(최근 40~55봉). 잠긴 자료 밖으로는 나가지 않는다.
            if item.get("candles"):
                # 2026-11-23 지시 #12104·#12128 — 상한가 당일·직후 화살은 뺀다(식은 바닥만).
                #   테마달력·형광↑ 알림 팝업과 같은 기준을 쓴다.
                item["pink"] = PINK.dates_cooled(rows, since=item["candles"][0][0])
            # ④ 자리 — 빠른 ④(25거래일 안) · 고가 위 ④(B형). 카드·팝업 배지와 정렬에 쓴다(2026-11-24)
            if st["info"].get("d4_date"):
                item["d4"] = {"d": st["info"]["d4_date"], "days": st["info"].get("d4_days"),
                               "type": st["info"].get("d4_type")}
                item["fast4"] = bool(item["d4"]["days"] is not None and item["d4"]["days"] <= 25)
                item["over4"] = item["d4"].get("type") == "B"
            # 일봉 상한가 자리의 앞/중/뒤는 그 봉이 속한 주봉·월봉 거래량으로 잰다(2026-11-19 07:38 지시)
            cp = cycle_pos(st["info"].get("v0_start") or "", wk, mo, am)
            item.update(cp)
            if cp.get("vr_all") is not None:
                item["pos"] = pos_of(cp["vr_all"])
            # 2·3·4번 가운데 앞선 고가를 넘어 올라선 종목은 '눌림'이 아니라 상승으로 보이게 표시한다
            #   (2026-11-19 사용자 지시 "고가 위로 가면 상승표시로 해줘요")
            if item["stage"] in (2, 3, 4) and (st["info"].get("over_pct") or 0) > 0:
                item["up"], item["up_pct"], item["up_ref"] = True, st["info"]["over_pct"], "1번 고점"
            # 테마 칸 — 테마를 구분해 보이게(2026-11-19 지시). 개별은 '개별 · 키워드'로 보인다.
            item["theme_ok"] = theme_ok
            # A++ — 손으로 찍은 도장만(brain/hotbar_a_plus.json). 코드가 스스로 찍지 않는다.
            stamp = (aplus or {}).get(code)
            item["aplus"], item["aplus_why"] = ("A++", list(stamp)) if stamp else ("", [])
            # 2026-11-23 지시 #12008 — 일봉 카드 하나로 차트 안에서 주봉·월봉까지 본다.
            #   10년 원본에서 만든 주봉 52주 · 월봉 30개월 실봉을 카드에 함께 싣는다
            #   (차트는 이 실봉을 먼저 쓰고, 없으면 일봉 캔들에서 합산한다).
            item["w"] = [[b["end"], round(b["o"], 2), round(b["h"], 2), round(b["l"], 2),
                          round(b["c"], 2), int(b["v"])] for b in wk[-52:]]
            item["m"] = [[b["end"], round(b["o"], 2), round(b["h"], 2), round(b["l"], 2),
                          round(b["c"], 2), int(b["v"])] for b in mo[-30:]]
            # 차트 안 주기 전환 때 그릴 하늘색 장기선 — 봉과 같은 자리 수로 맞춰 둔다
            CS = item.get("candles") or []
            at = {r[0]: i for i, r in enumerate(rows)}
            day_ma = ma_series([r[4] for r in rows], 240)
            item["ma240"] = [day_ma[at[c[0]]] if c[0] in at else None for c in CS]
            item["w_ma240"] = wk_ma240[-len(item["w"]):] if item["w"] else []
            item["m_ma120"] = mo_ma120[-len(item["m"]):] if item["m"] else []
            out[key] = item
            continue
        # 앞/뒤: ① 봉 거래량 ÷ 그 봉 전까지의 10년 최대(같은 봉)
        mx = prior_max(am.get(key[0]), st["info"].get("v0_start") or "")
        v0 = st["info"].get("v0")
        if v0 and mx:
            item["vr_all"] = round(v0 / mx, 3)
            item["pos"] = pos_of(item["vr_all"])
        out[key] = item
    return out or None
    return out or None


# ------------------------------------------------------------------ 형광↑ 알림 팝업(#cfOv) 재료
# 2026-11-24 전수조사(brain/study_pink_pre_vs_post_limitup.md §8) 권고안 — 팝업이 쓸 숫자를 여기서 한 번에 잰다.
#   화면(cfList)이 이 숫자로 등급(★·○·◆·△ + B 관찰)을 정하고, 이 파일은 핫바와 같은 비밀코드로 잠근다.
#   팝업은 잠금이 풀린 본인 화면에서만 뜨므로 잠긴 화면·공개 저장소에는 내용이 보이지 않는다.
def cf_stage10(rows, luf, i):
    """i번 봉이 '직전 상한가 → 1~10단계' 중 어디인지 — 10단계 복기와 같은 함수(S10.stage_path).

    돌려주는 값: (번호, 10단계 이후 여부). 닻(상한가)이 없거나 계산이 안 되면 (0, False).
      2 = 첫 고점 직후 눌림 초입 · 3 = 눌림 횡보 상자(돌파 전) · 5 = 윗선 돌파 봉
      6 = 분출 · 7·8 = 숨쉬고 마지막 분출 · 9 = 하락 멈춤 상자 · 10+late = 10단계 이후(새 바닥 재출발)

    2026-11-24 수정 — 예전에는 8단계 뒤 9단계 멈춤 상자가 없으면 **무조건 8**을 돌려줘,
    아직 내려오는 중인 종목과 이미 멈춘 종목이 뒤섞혔고(피앤에스로보틱스 같은 4단계 매수가 8로 잘림),
    10단계 뒤 재출발도 구분되지 않았다. 10단계 생성기(scripts/build_hotbar_buy.py `analyze`)와
    같은 갈래로 맞춘다 — 8단계 뒤는 ① 멈춤 상자(9) ② 그 안이면 9 ③ 상자를 지나 재출발했으면 10 이후
    ④ 멈춤 상자가 아직 없으면 하락 -28%·15봉 폭 18%로 9/8을 가른다.
    """
    i0 = next((j for j in range(min(i, len(rows) - 1), -1, -1) if luf[j]), None)
    if i0 is None:
        return 0, False
    # 우선 — 10단계 탭과 같은 판정(build_hotbar_buy.analyze). 닻 선택·새 ②③ 그림·유형 C까지 같다.
    #   2026-11-24: 팝업이 자체 계산으로 4단계 매수를 8단계로 잡아 빼던 문제를 이걸로 막는다.
    if B10 is not None and i == len(rows) - 1 and len(rows) >= 140:
        try:
            a10 = B10.analyze(rows)
            if a10 and a10.get("stage"):
                st = int(a10["stage"])
                return st, bool(st >= 10)
        except Exception:
            pass
    try:
        p = S10.stage_path(rows, i0, luf)
    except Exception:
        return 0, False
    if not p:
        return 1, False
    p1, q, b, p6 = p.get("p1"), p.get("q"), p.get("b"), p.get("p6")
    top, s = p.get("top"), p.get("s")
    if p1 is not None and i <= p1:
        return 1, False
    if q is not None and i <= q:
        return 2, False
    if b is not None and i < b:
        return 3, False
    if b is not None and i == b:
        return 5, False
    if b is not None and p6 is not None and i <= p6:
        return 6, False
    if top is not None and i <= top + 3:
        return 7, False
    if top is None:
        return 8, False
    if s is not None:
        if i < s:
            return 8, False                       # 멈춤 상자 전 — 아직 내려오는 중
        if i <= s + 14:
            return 9, False                       # 멈춤 상자 안 — 기다리는 자리(레이더 대기)
        return 10, True                           # 상자를 지나 재출발/이후
    # 멈춤 상자가 아직 없다 — 하락 깊이·폭으로 9(멈춤)·8(내려오는 중)을 가른다(10단계 analyze와 같은 잣대)
    dd = rows[i][4] / rows[top][2] - 1 if rows[top][2] else 0
    w = rows[max(0, i - 14):i + 1]
    rng = (max(r[2] for r in w) / min(r[3] for r in w) - 1) if len(w) == 15 and min(r[3] for r in w) > 0 else 9
    return (9 if (dd <= -0.28 and rng <= 0.18) else 8), False


def cf_val20(rows, i=None):
    """i번 봉까지 최근 20거래일 평균 거래대금(억원) — 팝업 10억 필터용."""
    i = len(rows) - 1 if i is None else i
    w = [rows[j][4] * rows[j][5] for j in range(max(0, i - 19), i + 1)]
    return round(sum(w) / len(w) / 1e8, 1) if w else 0.0


def cf_dd1y(rows, i=None):
    """1년(250봉) 고점 대비 오늘 종가(%) — 깊이 -50%↓ 판정용(핫바 카드 dd와 같은 잣대)."""
    i = len(rows) - 1 if i is None else i
    seg = rows[max(0, i - 249):i + 1]
    hi = max(r[2] for r in seg) if seg else 0
    return int(round((rows[i][4] / hi - 1) * 100)) if hi else 0


def cf_admin_flags(codes, today, skip=False):
    """관리종목·거래정지 확인 — 네이버 종목 기본정보(하루치 캐시). 실패하면 빈 칸으로 두고 팝업을 막지 않는다."""
    out: dict[str, dict] = {}
    if skip or not codes:
        return out
    os.makedirs(POPUP_ADMIN, exist_ok=True)
    path = os.path.join(POPUP_ADMIN, f"{today}.json")
    try:
        cached = json.load(open(path, encoding="utf-8"))
    except Exception:
        cached = {}
    todo = [c for c in dict.fromkeys(codes) if c not in cached]
    if todo:
        hdr = {"User-Agent": "Mozilla/5.0 (Linux; Android 13) Chrome/120 Mobile"}

        def one(code):
            try:
                url = f"https://m.stock.naver.com/api/stock/{code}/basic"
                req = urllib.request.Request(url, headers=hdr)
                with urllib.request.urlopen(req, timeout=8) as r:
                    d = json.loads(r.read().decode())
                stop = ((d.get("tradeStopType") or {}).get("name") or "").upper()
                return code, {"mgmt": bool(d.get("isManagement")),
                              "halt": bool(stop) and stop not in ("TRADING", "NORMAL"),
                              "name": d.get("stockName") or "",
                              "end": d.get("stockEndType") or ""}
            except Exception:
                return code, None

        with ThreadPoolExecutor(max_workers=8) as ex:
            for code, rec in ex.map(one, todo):
                if rec is not None:
                    cached[code] = rec
        try:
            json.dump(cached, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
    for c in codes:
        out[str(c)] = cached.get(str(c)) or {}
    return out


def cf_monthly():
    """10단계 생성기가 적어 둔 요약(평문 · 저장소 밖) — {'base_date':..., 'stocks':[{code,stage,...}]}.

    2026-11-24 — 팝업의 `stage10` 번호를 여기서 그대로 받아 쓴다. 예전에는 팝업이 봉으로 다시 재다가
    피앤애스로보틱스(10단계 4단계 매수)를 8단계로 오인해 잘라 버렸다.
    """
    try:
        d = json.load(open(MONTHLY_PLAIN, encoding="utf-8"))
        out = {str(x.get("code")): x for x in (d.get("stocks") or []) if x.get("code")}
        return out, str(d.get("base_date") or "")
    except Exception:
        return {}, ""


def cf_theme_kind():
    """테마 이름 → 테마구분(동반테마/개별상한가) — 테마 DB 그대로."""
    out = {}
    try:
        db = json.load(open(THEME_DB, encoding="utf-8"))
        for t in db.get("목록") or []:
            nm = (t.get("테마") or "").strip()
            if nm:
                out[nm] = (t.get("테마구분") or "").strip()
    except Exception:
        pass
    return out


def cf_d4_of(item):
    """일봉 카드의 ④ — ③(반등 양봉) 뒤 ② 기준선 위 3% 안까지 다시 내려온 첫 봉.

    돌려주는 값: (속도 = 상한가일→④ 거래일, 형태 'A'/'B', ④ 날짜). 봉이 모자라면 (None, None, None).
    10단계 생성기(build_hotbar_buy.py)와 같은 잣대(LINE_TOUCH 1.03)를 쓴다.
    """
    cd = item.get("candles") or []
    sd = item.get("stage_dates") or {}
    line = item.get("line")
    d1, d3 = sd.get("1"), sd.get("3")
    if not (cd and line and d1 and d3):
        return None, None, None
    dates = [c[0] for c in cd]
    if d1 not in dates or d3 not in dates:
        return None, None, None
    i1, i3 = dates.index(d1), dates.index(d3)
    if i3 <= i1:
        return None, None, None
    for k in range(i3 + 1, len(cd)):
        if cd[k][3] <= line * 1.03:
            typ = "B" if any(cd[j][2] > cd[i1][2] for j in range(i1 + 1, k + 1)) else "A"
            return k - i1, typ, cd[k][0]
    return None, None, None


def cf_buy_list(day3, day4, monthly, tmap, members, lu_date, stat_of, names,
                reason_of_fn, kinds, last_date, admin, newsmap=None, day2=None, risk_of=None):
    """🎯 실전 매수 적중 — 지금이 '사는 자리'인 종목만 모은다(2026-11-24 지시).

    입구: ① 일봉 핫바 3번·4번(핫바 매수 자리) ② 10단계 3·4단계 + 상태 '매수'(4단계 음봉·줄 자리)
          ③ 2번 중 ②줄까지 안 내려오고 버티며 오르는 강세 자리(적극매수 조건을 다 갖춘 것만)
    조건: 테마 무리(동반테마) 소속이거나 · 빠른 ④(상한가 후 25거래일 안) · 고가 위 ④(B형) ·
          깊이(1년 고점 -50%↓) · 4단계 형광↑(오늘 화살) 중 하나 이상
    거름: 20일 평균 거래대금 10억 미만(초저유동성) · 관리종목·거래정지 · 우선주
    표시: 한 줄 — 구분(3번 / 4번 / 3번 · 적극매수) + 종목명 + 테마명.
          배지·날짜·이유는 자료에만 남기고 화면은 index.html 이 한 줄로 그린다.

    적극매수 의견의 근거는 전수조사(brain/study_news_chart_theme_10stage_integrated.md)에서
    실제로 검증된 네 축만 쓴다 — ① 빠른 ④(+20% 73.1~78.2%) ② 고가 위 ④(62.5%)
    ③ 깊은 바닥 -50%↓(재상한가 22.9%) ④ 테마 무리(60.6% vs 51.2%) + 20일 평균 10억↑.
      · 확정 4번 = 10단계 4단계 '매수' 확정 또는 ④가 상한가 뒤 10거래일 이내(최상위 칸 78.2%).
        (네 축 중 2개 이상으로 잡으면 이 팝업 입구가 이미 걸러 놓은 목록이라 전원이 걸린다 — 2026-11-24 확인.)
      · 3번·2번 직행형 = 동반 + 깊은 바닥 + 10억↑ + 오늘 반등/강세 — ④가 안 오고 바로 가는
        22.5%(240봉 최고 중간값 +157%)를 미리 잡는 자리.
    정렬은 '오늘 먼저 반응한 순' — 당일 새로 생긴 4번(④·형광↑ 오늘) → 적극매수 → 오늘 등락률 센 순.
    """
    by = {}

    def val20_of(code):
        return round(float((stat_of.get(code) or (0, 0))[1] or 0), 1)

    def theme_names(code, extra):
        out = [str(t.get("name") or "").strip() for t in (tmap.get(code) or [])]
        for x in extra or []:
            x = str(x or "").strip()
            if x and x not in out:
                out.append(x)
        return [x for x in out if x]

    def add_day(it, stage):
        code = str(it.get("code") or "")
        if not code:
            return
        cur = by.get(code) or {"code": code, "name": it.get("name") or names.get(code, code),
                               "theme": "", "reason": "", "date": last_date,
                               "stage10": None, "badges": [], "val20": val20_of(code),
                               "dd": it.get("dd"), "src_day": True, "src_10": False}
        cur["src_day"] = True
        cur["day_stage"] = stage if not cur.get("day_stage") else min(cur["day_stage"], stage)
        cur["dd"] = it.get("dd") if it.get("dd") is not None else cur.get("dd")
        cur["chg"] = it.get("chg")            # 오늘(마지막 봉) 등락률 — '먼저 반응한 순' 정렬에 쓴다
        cur["pos2"] = it.get("pos2") or cur.get("pos2")   # 앞/뒤 — 뒤쪽은 팝업에서 거른다(2026-11-25)
        cur["up"] = bool(it.get("up"))        # 1번 고점 위로 올라선 강세
        cur["line_pct"] = it.get("line_pct")  # ②줄(기준선)에서 지금 몇 % 위/아래
        ths = theme_names(code, it.get("themes"))
        if ths and not cur["theme"]:
            cur["theme"] = ths[0]
        cur["themes"] = ths
        if it.get("reason") and not cur["reason"]:
            cur["reason"] = str(it["reason"])
        if str(it.get("base_date") or "") == last_date:
            cur["new_today"] = True
        by[code] = cur

    for it in day3 or []:
        add_day(it, 3)
    for it in day4 or []:
        add_day(it, 4)
    for it in day2 or []:
        add_day(it, 2)          # 2번은 아래에서 적극매수 조건을 다 갖춘 것만 남긴다
    # 10단계 3·4단계 + 상태 '매수' — 숫자·④ 배지·테마구분을 10단계 그대로 받는다
    for code, m in (monthly or {}).items():
        st = m.get("stage")
        if st not in (3, 4) or (m.get("state") or "") != "매수":
            continue
        cur = by.get(code) or {"code": code, "name": m.get("name") or names.get(code, code),
                               "theme": "", "reason": "", "date": last_date,
                               "badges": [], "val20": val20_of(code),
                               "dd": (m.get("dd") if (m.get("dd") is not None and m["dd"] < -2) else None),
                               "src_day": False, "src_10": False, "themes": theme_names(code, [m.get("theme")])}
        cur["src_10"] = True
        cur["stage10"] = int(st)
        cur["state"] = m.get("state") or ""
        cur["fast4"] = bool(m.get("fast4"))
        cur["over4"] = bool(m.get("over4"))
        cur["d4"] = m.get("d4") or None
        cur["theme_kind"] = m.get("theme_kind") or ""
        cur["t_n"] = m.get("t_n") or 1
        cur["why10"] = m.get("why") or ""
        if not cur["theme"] and m.get("theme"):
            cur["theme"] = m["theme"]
        if m.get("pink_arrow_date"):
            cur["pink_date"] = m["pink_arrow_date"]
        by[code] = cur

    out = []
    risk_out = []
    for code, x in by.items():
        nm = str(x.get("name") or "")
        if re.search(r"(우|우B|우C)$", nm) or "스팩" in nm or "리츠" in nm:
            continue                                  # 우선주·스팩·리츠는 주식 자리가 아니다
        a = admin.get(code) or {}
        if a.get("mgmt") or a.get("halt"):
            continue                                  # 관리종목·거래정지 — 팝업에 올리지 않는다
        val20 = round(float(x.get("val20") or 0), 1)
        if val20 < CF_VAL_MIN:
            continue                                  # 초저유동성(20일 평균 10억 미만) — 체결이 안 되는 자리
        ths = x.get("themes") or theme_names(code, [])
        # 2026-11-25 지시 — 일봉 자리가 '뒤쪽'(큰 파동 끝나 꺾인 자리)이면 오늘 픽에 세우지 않는다.
        #   인디에프·에스피소프트·SGA솔루션즈 같은 뒷쪽이 '3번'으로 찍히던 것을 막는다.
        if (x.get("pos2") or "") in ("뒷쪽", "뒤쪽") and not x.get("src_10"):
            continue
        kd = [kinds.get(t) or "" for t in ths]
        dong = any(k == "동반테마" for k in kd) or (x.get("t_n") or 1) >= 2 or (x.get("theme_kind") == "동반테마")
        # 일봉 카드의 ④(속도·형태)는 봉으로 잰다 — 10단계 카드가 있으면 그 값을 우선
        day_item = next((it for it in (day3 or []) + (day4 or []) if str(it.get("code")) == code), None)
        if day_item is not None and not x.get("src_10"):
            if day_item.get("d4"):
                x["fast4"] = bool(day_item.get("fast4"))
                x["over4"] = bool(day_item.get("over4"))
                x["d4"] = day_item.get("d4")
            else:
                days4, typ4, d4date = cf_d4_of(day_item)
                x["fast4"] = bool(days4 is not None and days4 <= 25)
                x["over4"] = (typ4 == "B")
                x["d4"] = {"d": d4date, "days": days4, "type": typ4} if days4 is not None else None
        dd = x.get("dd")
        deep = (dd is not None and dd <= CF_DD_MAX)
        pk_today = str(x.get("pink_date") or "") == last_date
        pk4 = bool(pk_today and (x.get("stage10") == 4 or x.get("day_stage") == 4))
        # 번호 — 일봉 자리와 10단계 자리가 같이 있으면 더 강한 '사는 자리'인 4번으로 적는다
        nums = ([int(x["day_stage"])] if x.get("day_stage") else []) \
            + ([int(x["stage10"])] if (x.get("src_10") and x.get("stage10")) else [])
        num = 4 if 4 in nums else (3 if 3 in nums else (nums[0] if nums else 3))
        # 전수조사에서 검증된 네 축 — 화면에는 안 쓰고 적극매수 판정에만 쓴다
        axes = []
        if x.get("fast4"):
            axes.append("빠른 ④")
        if x.get("over4"):
            axes.append("고가 위 ④")
        if deep:
            axes.append("깊은 바닥")
        if dong and val20 >= CF_VAL_MIN:
            axes.append("테마 무리")
        if pk4:
            axes.append("4단계 형광↑")
        stage_ok = bool(x.get("src_10") and int(x.get("stage10") or 0) == 4
                        and (x.get("state") or "") == "매수")     # 10단계 4단계 매수 확정
        react = x.get("chg")                        # 오늘(마지막 봉) 등락률 — 없으면 None
        react = None if react is None else float(react)
        strong_re = bool(x.get("up") or (react is not None and react > 0))   # 오늘 반등·강세 반응
        lp = x.get("line_pct")
        active = False
        if num == 4:
            # 확정 4번 — ① 10단계 4단계 '매수' 확정 ② ④가 상한가 뒤 10거래일 이내(전수조사 최상위 칸 78.2%).
            #   2축 이상으로 넓히면 이 팝업의 입구가 이미 걸러 놓은 목록이라 전원이 걸린다 → 최상위 칸만.
            d4d = (x.get("d4") or {}).get("days")
            active = bool(stage_ok or (d4d is not None and int(d4d) <= CF_FAST4_DAYS))
        elif num == 3:
            # 직행형 — 동반 + 깊은 바닥 + 10억↑ + 오늘 반등(④가 안 오고 바로 가는 자리)
            active = bool(dong and deep and val20 >= CF_VAL_MIN and strong_re)
        elif num == 2:
            # ②줄까지 안 내려오고 버티며 치고 오르는 강세 — 줄 위에서 오늘 오르는 것만
            active = bool(dong and deep and val20 >= CF_VAL_MIN and strong_re
                          and lp is not None and lp >= 0)
            if not active:
                continue                              # 2번은 적극매수 자리만 세운다(눌림 중인 것은 아래 칸에)
        if not (dong or x.get("fast4") or x.get("over4") or deep or pk4):
            continue                                  # 핵심 기준 하나도 안 걸리면 팝업에 세우지 않는다
        # 재무·공시 위험(18-7 · 2026-11-24 보완 1번) — 3점 이상·고유 악재는 🎯 칸에서 빼고,
        #   2점은 적극매수만 막아 ⚠를 달아 둔다(지슨처럼 적자+차입인 자리).
        rk = (risk_of or {}).get(code) or {}
        if rk.get("level") == "위험" and ((rk.get("score") or 0) >= CF_RISK_CUT
                                          or "고유악재" in (rk.get("flags") or [])):
            risk_out.append("%s(%s)" % (nm, rk.get("txt") or "악재"))
            continue
        if rk.get("level") in ("위험", "주의"):
            active = False
        stage_txt = ("10단계 %d단계" % x["stage10"]) if x.get("src_10") else ("일봉 %d번" % (x.get("day_stage") or 3))
        badges = [{"t": stage_txt, "c": "st"}]
        d4 = x.get("d4") or {}
        if x.get("fast4"):
            badges.append({"t": "빠른 ④ D+%s" % d4.get("days"), "c": "f4"})
        elif d4.get("days") is not None:
            badges.append({"t": "④ D+%s" % d4.get("days"), "c": "slow"})
        if x.get("over4"):
            badges.append({"t": "고가 위 ④", "c": "o4"})
        if dong:
            badges.append({"t": "동반", "c": "dong"})
        if deep:
            badges.append({"t": "깊은 바닥", "c": "deep"})
        if pk4:
            badges.append({"t": "4단계 형광↑", "c": "pk"})
        badge_amt = "20일 %s" % (("%.0f억" % val20) if val20 < 1000 else ("%.1f천억" % (val20 / 1000)))
        badges.append({"t": badge_amt, "c": "val"})
        if rk.get("txt"):
            badges.append({"t": ("⚠위험" if rk.get("level") == "위험" else "주의"), "c": "risk"})
        score = (2 if x.get("fast4") else 0) + (2 if x.get("over4") else 0) + (1 if dong else 0) \
            + (1 if deep else 0) + (2 if pk4 else 0) + (1 if x.get("src_10") else 0)
        reason = str(x.get("reason") or "")
        if not reason and x.get("why10"):
            reason = re.sub(r"\s*[—-]\s*[+-]?\d+(\.\d+)?%\s*$", "", str(x["why10"])).strip()
        # '4단계 자리 유지' · '지수 약세…' 같은 상태 문장은 이유가 아니다 — 뉴스·테마 한 줄로 바꾼다
        if re.match(r"^(\d단계|[0-9]단계|지수 약세|돌파|분출|관망)", reason or ""):
            reason = ""
        reason0, theme0 = reason_of_fn(code, tmap, newsmap)
        if not reason or reason == "재료 미확인":
            reason = (reason0 if reason0 != "재료 미확인" else "") or theme0 or (ths[0] if ths else "")
        if rk.get("txt"):
            # 사유 한 줄은 둘 다 보이게 — 앞에 위험 한 가지(짧게), 뒤에 원래 재료
            head = re.sub(r"\([^)]*\)", "", (rk.get("notes") or [rk["txt"]])[0]).strip()[:24]
            reason = (("⚠" if rk.get("level") == "위험" else "주의 ") + head
                      + (" · " + reason if reason else ""))
        out.append({"code": code, "name": nm, "theme": short_theme(x.get("theme") or (ths[0] if ths else "")),
                    "reason": reason[:70], "date": last_date, "stage10": x.get("stage10"),
                    "day_stage": x.get("day_stage"), "state": x.get("state") or ("매수" if x.get("src_day") else ""),
                    "badges": badges, "val20": val20, "dd": dd, "score": score,
                    "num": num, "label": ("%d번" % num) + (" · 적극매수" if active else ""),
                    "active": bool(active), "axes": axes,
                    "react": (round(react, 2) if react is not None else None),
                    "new4": bool(num == 4 and (str(((x.get("d4") or {}).get("d")) or "") == last_date
                                 or pk_today)),
                    "stage_ok": stage_ok, "risk": (rk.get("level") if rk.get("txt") else "")})
    # 정렬 — 2026-11-24 밤 지시: '오늘 먼저 반응한 순'. 당일 새로 생긴 4번(④·형광↑ 오늘) →
    #   적극매수 의견 → 오늘 등락률 센 순(등락률 없는 종목은 뒤로) → 3번 먼저·그다음 4번 → 기존 점수.
    def _react(z):
        return z["react"] if z["react"] is not None else -999.0
    out.sort(key=lambda z: (0 if z["new4"] else 1, 0 if z["active"] else 1,
                            -_react(z), 0 if z["num"] == 3 else (1 if z["num"] == 4 else 2),
                            -z["score"], z.get("name") or ""))
    more = max(0, len(out) - CF_BUY_MAX)
    return out[:CF_BUY_MAX], len(out), more, risk_out


def cf_radar_list(radar, cwait, stat_of, tmap, names, reason_of_fn, news_codes, news_themes,
                  kinds, admin, last_date, newsmap=None):
    """📡 레이더 길목 — 상한가 전 '앞쪽 깊은 바닥' + 유형 C(9단계) 재출발 대기(2026-11-24).

    거르는 순서: 테마 DB 소속 · 1년 고점 -50%↓ · 20일 평균 10억↑ · 관리종목 제외.
    앞쪽 바닥은 레이더 카드(tiers)·오늘 뉴스가 부른 테마 종목만, 9단계 대기는 유형 C 명단을 쓴다.
    """
    out, seen = [], set()

    def add(code, name, theme, tag, news, why, dd, val20, score):
        code = str(code or "")
        if not code or code in seen:
            return
        a = admin.get(code) or {}
        if a.get("mgmt") or a.get("halt"):
            return
        dd2, val2 = stat_of.get(code) or (None, 0)
        dd_v = dd2 if dd2 is not None else dd
        val20_v = round(float(val2 or val20 or 0), 1)
        if val20_v < CF_VAL_MIN:
            return
        if tag != "9단계 대기" and (dd_v is None or dd_v > CF_DD_MAX):
            return                                  # 앞쪽 깊은 바닥만(9단계 대기는 예외 — 레이더 규칙)
        seen.add(code)
        rz = str(why or "")
        if not rz and tag != "9단계 대기":      # 9단계 대기는 배지·테마만 (설명 늘리지 않는다)
            r0, _t0 = reason_of_fn(code, tmap, newsmap)
            rz = r0 if r0 and r0 != "재료 미확인" else ""
        out.append({"code": code, "name": name or names.get(code, code),
                    "theme": short_theme(theme or ((tmap.get(code) or [{}])[0].get("name") or "")),
                    "tag": tag, "news": bool(news), "reason": rz[:60],
                    "dd": dd_v, "val20": val20_v, "date": last_date, "score": score})

    # ① 유형 C — 9단계 하락 멈춤(재출발 대기). 레이더 cwait 명단 그대로
    for s in (cwait or []):
        add(s.get("code"), s.get("name"), s.get("theme"), "9단계 대기", False, "",
            s.get("dd") * 100 if isinstance(s.get("dd"), float) and abs(s.get("dd")) <= 1 else s.get("dd"),
            0, 6)
    # ② 레이더 카드(미리 뽑아 둔 테마·종목) — 오늘 뉴스가 붙은 카드 먼저
    for t in (radar or {}).get("tiers") or []:
        th = (t.get("theme") or "").strip()
        has_news = bool(t.get("news")) or any(n.startswith(th[:6]) for n in news_themes)
        for s in (t.get("stocks") or []):
            drop = s.get("drop")
            add(s.get("code"), s.get("name"), th, "앞쪽 바닥", has_news, "",
                (-abs(drop) if drop is not None else None), 0, 5 if has_news else 3)
    # ③ 오늘 뉴스가 부른 테마의 종목 — 테마 DB 소속만(깊이·두께는 add 안에서 거른다)
    for ln in (radar or {}).get("news_links") or []:
        th = (ln.get("theme") or "").strip()
        for s in (ln.get("stocks") or []):
            add(s.get("code"), s.get("name"), th, "앞쪽 바닥", True, "", None, 0, 4)
    out.sort(key=lambda z: (-z["score"], z.get("dd") if z.get("dd") is not None else 0))
    more = max(0, len(out) - CF_RADAR_MAX)
    return out[:CF_RADAR_MAX], len(out), more


def run(args):
    today = datetime.now(KST).strftime("%Y-%m-%d")
    codes, names = universe()
    print(f"대상 {len(codes)}종목")

    jp = delta_jsonl(today)
    carried = False
    if getattr(args, "fast", False) and not args.fetch_only and not os.path.exists(jp):
        carried = carry_delta(today)
    if not args.fetch_only and not os.path.exists(jp) and os.path.exists(delta_path(today)):
        print("· 오늘 받아 둔 시세 캐시를 종목별 파일로 바꿉니다(한 종목씩 읽어 메모리를 적게 씁니다)", flush=True)
        _split_dict_cache(delta_path(today), jp)
        nm = _names_from_dict(delta_path(today))
        if nm:
            json.dump(nm, open(delta_names_path(today), "w", encoding="utf-8"), ensure_ascii=False)
    if args.fetch_only or not os.path.exists(jp):
        names.update(fetch_all(codes, today))
    else:
        names.update({k: v for k, v in load_names(today).items() if v})

    if args.fetch_only:
        return

    # 30분 갱신(--fast): 시세는 배치로 한 번에 받아 오늘 봉만 덮어쓴다(종목당 520봉 재수신 없이).
    live: dict[str, list] = {}
    if getattr(args, "fast", False) and not args.no_fetch:
        t0 = time.time()
        live = fetch_quotes(codes)
        print(f"· 실시간 시세 {len(live)}/{len(codes)}종목 배치 수신 {time.time() - t0:.1f}s", flush=True)
        if carried:
            flush_live(today, live)

    # 10년 전체 거래량 기준표 + 오늘 캐시의 봉을 한 종목씩 합쳐 갱신하고, 그 자리에서 바로 분석한다
    amax = load_allmax()
    radar_codes = set()
    try:
        rr = json.load(open(RADAR, encoding="utf-8"))
        for t in (rr.get("tiers") or []):
            for s in (t.get("stocks") or []):
                if s.get("code"):
                    radar_codes.add(str(s["code"]))
    except Exception:
        pass

    sec = {k: {s: [] for s in STAGE_ORDER[k]} for k in STAGE_ORDER}
    tmap = theme_map()
    newsmap = news_map()
    monthly, monthly_base = cf_monthly()      # 10단계 카드 요약(평문) — 팝업 stage10 숫자의 정본
    if monthly:
        print(f"10단계 요약 {len(monthly)}종목 확보({monthly_base}) — 팝업 stage10 숫자를 여기서 받습니다", flush=True)
    # 주봉 240선·월봉 120선을 재려면 10년 원본이 필요하다 — 테마 종목만 골라 미리 읽어 둔다.
    print(f"10년 원본에서 테마 종목 이력 읽는 중… (테마 {len(tmap)}종목)", flush=True)
    hist = long_history_cached(set(tmap), fresh=getattr(args, "refresh_cache", False))
    print(f"10년 원본 {len(hist)}종목 확보", flush=True)
    aplus = load_a_plus()          # 손으로 찍은 A++ 도장(빈 {} 이면 A++ 0)
    leaders = load_leaders()       # 테마별 대장주 — 정렬에서 대장을 맨 위로(2026-11-20 지시)
    print(f"테마 대장주 {len(leaders)}테마 확보", flush=True)
    print("10년 원본에서 주봉 240주 선뭉침 재는 중…", flush=True)
    cltab = cluster_table_cached(fresh=getattr(args, "refresh_cache", False))   # 종목별 선뭉침 숫자(10년 원본 서명별 캐시)
    print(f"선뭉침 계산 {len(cltab)}종목"
          f" (선뭉침 {sum(1 for v in cltab.values() if v.get('cl'))} · 불씨전 {sum(1 for v in cltab.values() if v.get('cl_wait'))})",
          flush=True)
    print(f"A++ 수동 도장 {len(aplus)}종목" + (": " + ", ".join(aplus) if aplus else " — 배지 없음"), flush=True)
    thin, seen, radar_rows, results = 0, {}, {}, []
    lu_recent = {}                # 종목코드 → 최근 상한가 날짜 집합 (1단계 테마 크기 — 동반 상한가)
    drop_off = []                  # 테마·재료가 확실하지 않아 뺀 종목(보고용)
    cf_seed, cf_dates = [], set()  # 형광↑ 팝업 후보(오늘 화살) · 최근 거래일(테마 20거래일 창)
    stat_of = {}                   # 종목코드 → (1년 고점 대비 %, 20일 평균 거래대금 억) — 3칸 팝업의 깊이·두께
    for code, rows in iter_delta(today):
        if live:
            rows = overlay_row(rows, live.get(code))
        if not rows:
            continue
        merge_tops(amax, code, rows)
        stat_of[str(code)] = (cf_dd1y(rows), cf_val20(rows))
        lo_i = max(0, len(rows) - 45)
        lu_recent[str(code)] = {rows[i][0] for i in range(max(1, lo_i), len(rows)) if day_lu(rows, i)}
        cf_dates.update(r[0] for r in rows[-30:])
        # 형광↑ 알림 팝업(#cfOv) 후보 — 오늘(마지막 봉) 화살이 뜬 종목의 등급 재료를 여기서 잰다.
        #   화면이 이 숫자로 등급(★·○·◆·△)을 정한다(2026-11-24 전수조사 §8-2·8-3).
        if len(rows) >= 60:
            pdate, _pback, pag = PINK.recent_cooled(rows, days=1)
            if pdate:
                st10, late10 = cf_stage10(rows, PINK.lu_flags(rows), len(rows) - 1)
                cf_seed.append({"code": str(code), "name": names.get(code, code),
                                "date": str(pdate), "dd": cf_dd1y(rows),
                                "lu_ago": pag, "val20": cf_val20(rows),
                                "stage10": st10, "stage10_late": bool(late10),
                                "theme": "", "themes": [], "summary": "",
                                "theme_lu20": False})
        if code in radar_codes:
            radar_rows[code] = rows
        seen[rows[-1][0]] = seen.get(rows[-1][0], 0) + 1
        if args.debug:
            if code != args.debug:
                continue
            rows = rows[-90:]
            print("일봉", day_stage(rows))
            print("주봉", week_stage(rows))
            print("월봉", month_stage(rows))
            return
        res = analyze(code, names.get(code, code), rows, tmap, amax, newsmap, aplus,
                      merged_rows(hist, code, rows), drop_off, cltab)
        if not res:
            thin += 1
            continue
        results.append((rows[-1][0], res))
    print(f"10년 최대 거래량 기준표 {len(amax)}종목", flush=True)

    # 시세 캐시의 마지막 거래일이 곧 핫바 기준일
    last_date = max(seen, key=seen.get) if seen else today
    for d0, res in results:
        if d0 != last_date:
            continue
        for key, item in res.items():
            sec[key][item["stage"]].append(item)

    # ---- 1단계 첫 단추: 테마 크기 — 같은 테마에서 최근 1주 안에 상한가 낸 종목 수(나 포함)
    #      2026-11-21 지시. 테마 DB에 여럿으로 나뉜 이름은 그 이름 그대로 센다(임의로 묶지 않는다).
    members: dict[str, set] = {}
    lu_date: dict[str, set] = {}
    for c, lst in tmap.items():
        for t in lst:
            members.setdefault((t.get("name") or "").strip(), set()).add(str(c))
            lu_date.setdefault(str(c), set()).update(d for d in (t.get("dates") or []) if d)
    for c, ds in lu_recent.items():            # 일봉(+28.5%)에서 잰 상한가 날도 함께
        lu_date.setdefault(c, set()).update(ds)
    for it in sec["day"][1]:
        th, d1 = (it.get("theme") or "").strip(), it.get("lu_date")
        if not th or not d1:
            continue
        cut = (date.fromisoformat(d1) - timedelta(days=7)).isoformat()
        n = 1
        for c2 in members.get(th, ()):
            if c2 == str(it["code"]):
                continue
            if any(cut <= x <= d1 for x in lu_date.get(c2, ())):
                n += 1
        it["t_n"] = n
        it["t_sz"] = "대" if n >= 4 else ("중" if n >= 2 else "소")

    # ---- 형광↑ 알림 팝업(#cfOv) — 오늘 화살 후보에 테마 진행 여부를 붙이고 잠근 파일로 내보낸다.
    #   2026-11-24 전수조사 §8-4: 같은 테마 다른 종목 상한가가 20거래일 안에 있었는지가 A에서 가장 큰 알파
    #   (재상한가 14.6% → 32.6%). B(무상한가)는 과거 검증이 미래 정보로 오염돼 테마 필터를 쓰지 않는다.
    cf_recent = set(sorted(d for d in cf_dates if d <= last_date)[-CF_THEME_DAYS:])
    cf_items = []
    for x in cf_seed:
        if x["date"] != last_date:
            continue                               # 기준일(오늘) 화살만
        ths = [str(t.get("name") or "").strip() for t in (tmap.get(x["code"]) or [])]
        ths = [t for t in ths if t]
        reason, theme = reason_of(x["code"], tmap, newsmap)
        theme = theme or (ths[0] if ths else "")
        x["theme"] = short_theme(theme) if theme else ""
        x["themes"] = [x["theme"]] if x["theme"] else []
        # 2026-11-25 지시 — 팝업 줄의 테마가 **빈칸으로 남지 않게**.
        #   theme_db 에 없거나 '재료 미확인…' 테마뿐이면 종목 뉴스·기사 제목의 섬터 낱말로 채우고,
        #   그것도 없으면 '개별'(테마 없이 종목만)로 적는다. '재료 미확인'은 라벨로 쓰지 않는다.
        if not x["theme"]:
            _nw = (newsmap or {}).get(str(x["code"])) or {}
            _blob = " ".join(str(_nw.get(k) or "") for k in ("today", "title", "stock"))
            _alt = ""
            for _sec, _kws in SECTOR_KEYS:
                if any(str(k).lower() in _blob.lower() for k in _kws):
                    _alt = "개별 · " + _sec
                    break
            x["theme"] = _alt or "개별"
            x["themes"] = [x["theme"]]
        x["summary"] = reason if reason and reason != "재료 미확인" else ""
        alive = False
        if x["lu_ago"] is not None and x["lu_ago"] <= CF_LU_MAX:      # A만 테마 필터(§4-1)
            for th in ths:
                for c2 in members.get(th, ()):
                    if c2 == x["code"]:
                        continue
                    if any(d in cf_recent for d in lu_date.get(c2, ())):
                        alive = True
                        break
                if alive:
                    break
        x["theme_lu20"] = alive
        # 2026-11-24 — 10단계 카드의 숫자를 그대로 받아 쓴다(팝업 stage10 오기 수정).
        #   피앤에스로보틱스처럼 4단계 매수인 종목이 봉 재계산에서 8로 잡혀 빠지는 일을 없앤다.
        m = monthly.get(x["code"]) or {}
        if m.get("stage"):
            x["stage10"] = int(m["stage"])
            x["stage10_late"] = bool(m["stage"] >= 10)
            x["fast4"] = bool(m.get("fast4"))
            x["over4"] = bool(m.get("over4"))
            x["state10"] = m.get("state") or ""
        cf_items.append(x)
    admin = cf_admin_flags([x["code"] for x in cf_items], last_date,
                           bool(getattr(args, "no_admin", False)))
    cf_keep, cf_dropped = [], []
    for x in cf_items:
        a = admin.get(x["code"]) or {}
        if a.get("mgmt") or a.get("halt"):
            cf_dropped.append(f"{x['name']}({x['code']})")     # 관리종목·거래정지 — 화살표가 이뻐도 뺀다
            continue
        cf_keep.append(x)
    cf_items = sorted(cf_keep, key=lambda x: (x["dd"], x["name"] or ""))
    cf_a = [x for x in cf_items if x["lu_ago"] is not None and CF_LU_MIN <= x["lu_ago"] <= CF_LU_MAX]
    cf_counts = {"arrows": len(cf_items), "a": len(cf_a), "b": len(cf_items) - len(cf_a),
                 "deep": sum(1 for x in cf_a if x["dd"] <= CF_DD_MAX),
                 "deep_val": sum(1 for x in cf_a if x["dd"] <= CF_DD_MAX and x["val20"] >= CF_VAL_MIN),
                 "theme20": sum(1 for x in cf_a if x["theme_lu20"]),
                 "dropped": len(cf_dropped)}
    cf_now = datetime.now(KST)

    # ---- 3칸 종합 팝업(2026-11-24 지시) — 실전 매수 적중 · 레이더 길목 · 형광↑ 정예
    #   형광↑(오늘 화살)만 입구로 받으면 테마 DB·10단계·핫바 적중 종목이 빠진다.
    #   입구를 셋으로 늘리고, 표시는 날짜(또는 배지) · 종목명 · 테마명 · 한 줄 이유로 짧게 유지한다.
    day2 = (sec.get("day") or {}).get(2) or []
    day3 = (sec.get("day") or {}).get(3) or []
    day4 = (sec.get("day") or {}).get(4) or []
    kinds = cf_theme_kind()
    buy_codes = {str(it.get("code")) for it in day2 + day3 + day4}
    buy_codes |= {c for c, m in monthly.items() if m.get("stage") in (3, 4) and (m.get("state") or "") == "매수"}
    try:
        radar_plain = json.load(open(RADAR_MASTER, encoding="utf-8"))
    except Exception:
        radar_plain = {}
    cw = (radar_plain.get("cwait") or {}).get("stocks") or []
    radar_cand = {str(s.get("code")) for s in cw}
    for t in (radar_plain.get("tiers") or []):
        radar_cand |= {str(s.get("code")) for s in (t.get("stocks") or []) if s.get("code")}
    for ln in (radar_plain.get("news_links") or []):
        radar_cand |= {str(s.get("code")) for s in (ln.get("stocks") or []) if s.get("code")}
    admin2 = cf_admin_flags(sorted(buy_codes | radar_cand), last_date,
                            bool(getattr(args, "no_admin", False)))
    # 재무·공시 위험(18-7 · 2026-11-24 보완 1번) — 🎯 매수 후보만 네이버에서 새로 받고(그날 첫 실행만),
    #   레이더·형광↑는 같은 캐시에 있으면 배지로만 쓴다(30분 갱신을 느리게 하지 않는다).
    risk_reason = {}
    for c in buy_codes:
        try:
            risk_reason[str(c)] = reason_of(str(c), tmap, newsmap)[0] or ""
        except Exception:
            risk_reason[str(c)] = ""
    risk_buy = {} if getattr(args, "no_risk", False) else RISK.load(
        sorted(buy_codes), last_date, risk_reason, workers=10)
    risk_radar = {} if getattr(args, "no_risk", False) else RISK.load(
        sorted(radar_cand), last_date, no_fetch=True)
    risk_all = dict(risk_radar)
    risk_all.update(risk_buy)
    for x in cf_items:                       # 🟢 형광↑ 칸 — 위험은 뺀지 않고 사유에 먼저 적는다
        rk = risk_all.get(x["code"]) or {}
        if not rk.get("txt"):
            continue
        x["risk"] = rk.get("level") or ""
        x["risk_txt"] = rk["txt"]
        if rk.get("level") == "위험":
            x["summary"] = ("⚠ " + rk["txt"] + (" · " + x["summary"] if x.get("summary") else ""))[:120]
    buy_items, buy_all, buy_more, risk_cut = cf_buy_list(day3, day4, monthly, tmap, members, lu_date,
                                                        stat_of, names, reason_of, kinds, last_date, admin2,
                                                        newsmap, day2=day2, risk_of=risk_buy)
    news_themes = [str(ln.get("theme") or "") for ln in (radar_plain.get("news_links") or [])]
    news_codes = set()
    radar_items, radar_all, radar_more = cf_radar_list(radar_plain, cw, stat_of, tmap, names,
                                                      reason_of, news_codes, news_themes, kinds,
                                                      admin2, last_date, newsmap)
    # 형광↑ 정예 — 위 두 칸에 이미 올라간 종목은 겹치지 않게 뺀다(같은 종목 두 번 보이지 않도록)
    used = {x["code"] for x in buy_items} | {x["code"] for x in radar_items}
    cf_pink = [x for x in cf_items if x["code"] not in used]
    # ---- 추가 시각(added_at) — 2026-11-25 지시: "픽 실전에 상단 배치.(30분 단위 추가되면 제일상단 순)"
    #   오늘 픽에 서는 종목(🎯 매수 + 🟢 형광↑)이 **처음 픽에 들어온 시각**을 저장소 밖에 남긴다.
    #   목록에서 빠지면 지우고, 다시 들어오면 그때 시각으로 새로 적는다 → 새로 잡힌 종목이 맨 위에 온다.
    pick_now = cf_now.isoformat(timespec="seconds")
    pick_codes = [str(x.get("code")) for x in buy_items] + [str(x.get("code")) for x in cf_pink]
    try:
        old_added = json.load(open(PICK_ADDED, encoding="utf-8"))
    except Exception:
        old_added = {}
    added_at = {c: (old_added.get(c) or pick_now) for c in pick_codes if c}
    for x in buy_items:
        x["added_at"] = added_at.get(str(x.get("code")))
    for x in cf_pink:
        x["added_at"] = added_at.get(str(x.get("code")))
    if not getattr(args, "dry", False):
        try:
            os.makedirs(os.path.dirname(PICK_ADDED), exist_ok=True)
            with open(PICK_ADDED, "w", encoding="utf-8") as f:
                json.dump(added_at, f, ensure_ascii=False)
        except Exception as e:  # noqa: BLE001
            print("⚠ 추가 시각(added_at)을 적지 못했습니다:", e, flush=True)

    cf_doc = {"v": 2,
              "generated_at": cf_now.isoformat(timespec="seconds"),
              "generated_at_kst": cf_now.strftime("%Y.%m.%d %H:%M"),
              "base_date": last_date,
              "rules": {"lu_min": CF_LU_MIN, "lu_max": CF_LU_MAX, "dd_max": CF_DD_MAX,
                        "val_min": CF_VAL_MIN, "theme_days": CF_THEME_DAYS, "obs_max": CF_OBS_MAX,
                        "buy_max": CF_BUY_MAX, "radar_max": CF_RADAR_MAX},
              "counts": dict(cf_counts, buy=len(buy_items), buy_all=buy_all, radar=len(radar_items),
                             radar_all=radar_all),
              "sections": {"buy": buy_items, "radar": radar_items, "pink": cf_pink},
              "items": cf_items}
    if not getattr(args, "dry", False):
        os.makedirs(os.path.dirname(POPUP_OUT), exist_ok=True)
        with open(POPUP_OUT, "w", encoding="utf-8") as f:
            json.dump(seal(cf_doc, HOTBAR_PW), f, ensure_ascii=False, separators=(",", ":"))
    print("형광↑ 팝업 후보 — 오늘 화살 %d(A %d · B %d) · 깊이 -50%%↓ %d · 10억↑ %d · 테마 20일 %d%s"
          % (cf_counts["arrows"], cf_counts["a"], cf_counts["b"], cf_counts["deep"],
             cf_counts["deep_val"], cf_counts["theme20"],
             (" · 관리·정지 제외 " + ", ".join(cf_dropped)) if cf_dropped else ""), flush=True)
    print("3칸 종합 팝업 — 🎯 매수 %d%s · 📡 레이더 %d%s · 🟢 형광↑ %d"
          % (len(buy_items), (" (전체 %d)" % buy_all) if buy_more else "",
             len(radar_items), (" (전체 %d)" % radar_all) if radar_more else "", len(cf_pink)), flush=True)
    if risk_cut:
        print("   재무·공시 위험으로 뺀 자리 %d — %s" % (len(risk_cut), " · ".join(risk_cut[:6])), flush=True)
    n_warn = sum(1 for x in buy_items if x.get("risk") == "주의")
    if n_warn:
        print("   주의(적자·차입·공시) — 적극매수 없이 %d종목" % n_warn, flush=True)
    for x in buy_items:
        if x.get("active"):
            print("   적극매수 — [%s] %s · %s (축 %s%s)"
                  % (x["label"], x["name"], x["theme"],
                     "/".join(x.get("axes") or []) or "-",
                     " · 10단계 확정" if x.get("stage_ok") else ""), flush=True)

    # ---- 앞/뒤: 일봉은 상한가 자리를 하나도 놓치지 않는다(앞·중·뒤 모두 배지로 구분).
    #      주봉·월봉은 2026-11-19 개편으로 '테마 + 바닥 6개월 뒤 시작 거래량'만 싣고,
    #      뒤쪽(장기 이선 위·20일선<60일선)도 빼지 않고 '앞쪽/뒤쪽'으로 표시한다.
    pos_n = {"앞": 0, "중": 0, "뒤": 0, None: 0}
    for k in STAGE_ORDER:
        for s in STAGE_ORDER[k]:
            for it in sec[k][s]:
                pos_n[it.get("pos")] = pos_n.get(it.get("pos"), 0) + 1

    # ---- 기준선(그림 기준선 = ② 눌림 저점): ③ 반등 양봉이 나온 종목만 긋는다(2026-11-21 지시).
    line_off = {"3번 대기": 0, "도지·몸통 없음": 0, "남김": 0}
    for k in STAGE_ORDER:
        for s in STAGE_ORDER[k]:
            for it in sec[k][s]:
                why = prep_base_line(it)
                if why:
                    line_off[why] = line_off.get(why, 0) + 1

    # ---- 대장 표시 — 그 테마의 대장주(brain/theme_leaders.json)면 leader=1.
    #      2026-11-20 지시 "대장이 위에 배치 첫상한가 첫거래량 테마 재료 우선"
    lead_n = 0
    for k in STAGE_ORDER:
        for s in STAGE_ORDER[k]:
            for it in sec[k][s]:
                L = leaders.get((it.get("theme") or "").strip())
                if L and str(L.get("code")) == str(it.get("code")):
                    it["leader"] = 1
                    lead_n += 1

    # 정렬 — 2026-11-20 지시로 모든 단계가 같은 순서를 탄다:
    #   ① 첫 상한가·첫 거래량 자리(앞쪽) 먼저 — 이미 더 큰 거래량 파동이 지나간 자리(뒤쪽)는 아래
    #      (아이씨에이치처럼 8~9월 파동 뒤 10.26 상한가가 온 종목은 뒤쪽 → 앞쪽 종목보다 아래)
    #   ② 같은 자리면 테마·재료가 확실한 종목(테마 DB 소속) 먼저, 개별은 아래
    #   ③ 테마 묶음끼리는 그 테마에서 가장 강한 종목(월·주봉=거래량 배수, 일봉=상한가 횟수)이 선 테마부터,
    #      같은 테마 안에서는 그 테마의 대장주가 맨 위
    # 그 뒤에 단계별 기존 기준(2·4번=줄에 가까운 순, 3번=최근 반등, 5번+=최근 순)이 붙는다.
    def _rev(d):
        return "".join(chr(0x10FFFF - ord(ch)) for ch in str(d or ""))
    POS_SORT = {"앞쪽": 0, "앞": 0, "초입": 1, "중간": 1, "중": 1, "뒤쪽": 2, "뒤": 2}
    def _tname(x):
        return (x.get("theme") or "").strip() or (x.get("theme_label") or "")
    def base_key(rows, strength):
        """테마 묶음 순서를 '그 테마에서 가장 강한 종목' 순으로 잡은 공통 키."""
        best: dict[str, float] = {}
        for x in rows:
            t, v = _tname(x), strength(x)
            if v > best.get(t, -1e9):
                best[t] = v
        def k(x):
            pos = x.get("pos2") or x.get("pos")
            t = _tname(x)
            return (POS_SORT.get(pos, 3), 0 if x.get("theme_ok") else 1,
                    -best.get(t, 0), t, 0 if x.get("leader") else 1)
        return k
    k1 = base_key(sec["day"][1], lambda x: x.get("lu_n") or 0)
    sec["day"][1].sort(key=lambda x: k1(x) + (-(x.get("lu_n") or 0), x.get("lu_date") or ""))
    for s in (2, 4):
        kb = base_key(sec["day"][s], lambda x: x.get("lu_n") or 0)
        sec["day"][s].sort(key=lambda x: kb(x) + (0 if x.get("bottom") else 1,
                                                  abs(x.get("line_pct") if x.get("line_pct") is not None else 99)))
    kb3 = base_key(sec["day"][3], lambda x: x.get("lu_n") or 0)
    sec["day"][3].sort(key=lambda x: kb3(x) + (0 if x.get("bottom") else 1,
                                              0 if x.get("fast4") else 1, _rev(x.get("rb_date"))))
    # 4번(④ 줄 자리) — 빠른 ④·고가 위 ④가 붙은 종목을 먼저(전수조사 §4: 빠를수록·B형이 성적이 좋다)
    kb4 = base_key(sec["day"][4], lambda x: x.get("lu_n") or 0)
    sec["day"][4].sort(key=lambda x: kb4(x) + (0 if x.get("bottom") else 1,
                                              -((1 if x.get("fast4") else 0) + (1 if x.get("over4") else 0)),
                                              abs(x.get("line_pct") if x.get("line_pct") is not None else 99)))
    for s in range(5, DAY_MAX_NUM + 1):
        k5 = base_key(sec["day"][s], lambda x: x.get("lu_n") or 0)
        sec["day"][s].sort(key=lambda x: k5(x) + (-(x.get("stage") or 0), _rev(x.get("base_date"))))
    # 주봉·월봉도 같은 순서 — 앞쪽 먼저, 그 안에서 1번=거래량 배수 큰 순 / 2번=고점 대비 덜 빠진 순 / 3번=최근 반등
    for k in ("week", "month"):
        kw = base_key(sec[k][1], lambda x: x.get("ratio") or 0)
        sec[k][1].sort(key=lambda x: kw(x) + (-(x.get("ratio") or 0),))
        kw2 = base_key(sec[k][2], lambda x: x.get("ratio") or 0)
        sec[k][2].sort(key=lambda x: kw2(x) + (-(x.get("dd") or 0),))
        kw3 = base_key(sec[k][3], lambda x: x.get("ratio") or 0)
        sec[k][3].sort(key=lambda x: kw3(x) + (_rev(x.get("b3_date")),))
        kw4 = base_key(sec[k][4], lambda x: x.get("ratio") or 0)
        sec[k][4].sort(key=lambda x: kw4(x) + (abs(x.get("line_pct") if x.get("line_pct") is not None else 99),))
        # 5번 이후 — 최근 자리(번호 큰 것) 먼저, 같은 번호면 최근 날짜 먼저
        for s in range(5, TF_MAX_NUM + 1):
            k5t = base_key(sec[k][s], lambda x: x.get("ratio") or 0)
            sec[k][s].sort(key=lambda x: k5t(x) + (_rev(x.get("base_date")),))

    # 월봉 카드의 차트는 24~36개월이 필요하다 — 오늘 캐시(450봉 ≈ 21개월)보다 앞의 달은
    # 네이버 월봉에서 앞쪽 몇 달만 받아 붙인다(닫힌 달이라 장중 값과 섞이지 않는다).
    enrich_month_candles(sec["month"], last_date)
    # 하늘색 장기선(주봉 240주 · 월봉 120개월) — 10년 원본이 없는 종목은 네이버에서 받아 채운다
    fill_long_ma(sec, today)

    def stage_doc(k: str, s: int, d: str) -> dict:
        st = sec[k][s]
        out = {"stage": s, "label": f"{s}번", "desc": d, "stocks": st,
               "count": len(st), "bottom_count": sum(1 for x in st if x.get("bottom"))}
        h = (STAGE_HELP.get(k) or {}).get(s)
        if h:
            out["help"] = h          # 기본 화면엔 안 보이고 카드 tooltip 에서만
        return out

    # 일봉 — 1번은 '이번 달 상한가 전부(테마별 명부)', 2·3·4는 늘 보이고 5번부터는 종목이 있는 번호까지만.
    #   명부는 종목을 다시 싣지 않고 [코드, 지금번호] 짝만 보낸다(2번 이하 카드에서 찾아 그린다).
    day_all = [x for s in range(1, DAY_MAX_NUM + 1) for x in sec["day"][s]]
    def _roster_key(x):
        # 명부도 같은 순서 — 테마 확실 → 앞쪽(첫 상한가) → 테마 안 대장 → 상한가 많이·최근
        return k1(x) + (-(x.get("lu_n") or 0), _rev(x.get("lu_date")))
    roster = [[x["code"], x["stage"], 1 if x.get("theme_ok") else 0]
              for x in sorted([x for x in day_all if x.get("theme_ok")], key=_roster_key)]
    roster_indiv = [[x["code"], x["stage"], 0, x.get("theme") or ""]
                    for x in sorted([x for x in day_all if not x.get("theme_ok")], key=_roster_key)]
    day_stages = [s for s in range(1, DAY_MAX_NUM + 1) if sec["day"][s]]
    day_counts = {"1": len(day_all)}
    day_counts.update({s: len(sec["day"][s]) for s in range(2, DAY_MAX_NUM + 1)})
    now = datetime.now(KST)
    tf_stages = {k: [s for s in range(1, TF_MAX_NUM + 1) if s <= 4 or sec[k][s]]
                 for k in ("week", "month")}
    score = scorecard(last_date)
    doc = {
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_at_kst": now.strftime("%Y.%m.%d %H:%M"),
        "base_date": last_date,
        "base_date_text": f"{last_date[:4]}.{last_date[5:].replace('-', '.')} 종가 기준",
        "universe": seen.get(last_date, 0),
        "bottom_dd": BOTTOM_DD,
        "sections": [
            {"key": "day", "title": "일봉", "sub": "상한가 1 → 2 → 3 → 4 → 5·6·7…",
             "total": len(day_all), "counts": day_counts,
             "roster": roster, "roster_indiv": roster_indiv,
             "roster_desc": "상한가 · 테마별 전체",
             "at1": len(sec["day"][1]),
             "stages": [stage_doc("day", s, STAGE_DESC["day"][s]) for s in day_stages]},
            {"key": "week", "title": "주봉", "sub": "테마 · 1 → 2 → 3 → 4 → 5…",
             "sub_help": "바닥에서 6개월 조용하던 거래량을 뚜렷하게 넘어선 주봉 양봉을 1번으로 본다(6개월 최대 2배 이상)",
             "stages": [stage_doc("week", s, STAGE_DESC["week"][s]) for s in tf_stages["week"]]},
            {"key": "month", "title": "월봉", "sub": "테마 · 1 → 2 → 3 → 4 → 5…",
             "sub_help": "바닥에서 6개월 조용하던 거래량을 뚜렷하게 넘어선 월봉 양봉을 1번으로 본다(6개월 최대 2배 이상)",
             "stages": [stage_doc("month", s, STAGE_DESC["month"][s]) for s in tf_stages["month"]]},
        ],
        "score": score,
        "counts": {k: {s: len(v) for s, v in sec[k].items()} for k in sec},
        "bottom_counts": {k: {s: sum(1 for x in sec[k][s] if x.get("bottom")) for s in STAGE_ORDER[k]}
                          for k in sec},
    }
    # 오늘 분홍↑ 종목 명단(평문) — 잠근 hotbar.json 을 풀지 않고도 공개 125봉 자료가
    #   이 종목 봉까지 받을 수 있게 brain/cache(공개 저장소 밖)에만 적는다(2026-11-23).
    pink_items = [x for secd in doc["sections"] for sd in (secd.get("stages") or [])
                  for x in (sd.get("stocks") or [])]
    pink_n = PINKX.write(PINK_TODAY, last_date, PINKX.rows_of(pink_items, last_date, "pink"))
    if pink_n >= 0:
        print("오늘 분홍↑ 종목 명단 %d개 → %s" % (pink_n, PINK_TODAY))
    # 팝업 후보(오늘 화살·전 종목)도 같은 명단에 남긴다 — 공개 125봉 자료(build_day125.py)가
    #   이 종목 봉까지 받아, 팝업에서 눌렀을 때 '일봉 시세가 아직 없습니다'가 뜨지 않게(2026-11-24).
    pop_n = PINKX.write(POPUP_PINK, last_date, [{"code": x["code"], "name": x["name"]} for x in cf_items])
    if pop_n >= 0:
        print("팝업 후보 명단 %d개 → %s" % (pop_n, POPUP_PINK))
    # 핫바 카드 종목의 평문 코드 명단 — 공개 일봉 125봉 자료가 이 종목까지 받게(2026-11-25 v122)
    hb_codes, hb_seen = [], set()
    for secd in doc["sections"]:
        for sd in (secd.get("stages") or []):
            for x in (sd.get("stocks") or []):
                c = str(x.get("code") or "")
                if c and c not in hb_seen:
                    hb_seen.add(c)
                    hb_codes.append({"code": c, "name": x.get("name") or ""})
    hb_n = PINKX.write(HOTBAR_CODES, last_date, hb_codes)
    if hb_n >= 0:
        print("핫바 카드 종목 코드 명단 %d개 → %s" % (hb_n, HOTBAR_CODES))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    sealed = seal(doc, HOTBAR_PW)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(sealed, f, ensure_ascii=False, separators=(",", ":"))
    print("기준일", last_date, "| 유동성 미달·자료부족 제외", thin)
    print("일봉 앞/중/뒤", pos_n, "| 기준선", line_off)
    # 테마·재료가 전혀 없는 무재료 종목은 일봉·주봉·월봉 모두에서 뺐다(2026-11-19 지시 → 같은 날 정정)
    drop_off = [x for x in drop_off if x["date"] == last_date]     # 기준일 종목만(정지·결측 종목 제외)
    off_day = [x for x in drop_off if x["key"] == "day"]
    print(f"무재료 제외 — 일봉 {len(off_day)}종목 · 주봉 {sum(1 for x in drop_off if x['key'] == 'week')}종목"
          f" · 월봉 {sum(1 for x in drop_off if x['key'] == 'month')}종목")
    if off_day:
        by_why = {}
        for x in off_day:
            by_why[x["why"]] = by_why.get(x["why"], 0) + 1
        print("  뺀 이유:", ", ".join(f"{k} {v}" for k, v in by_why.items()))
        print("  일봉에서 뺀 종목(번호): "
              + ", ".join(f"{x['name']}({x['stage']})" for x in off_day))
    for k in ("week", "month"):
        off = [x for x in drop_off if x["key"] == k]
        if off:
            print(f"  {k}에서 뺀 종목 {len(off)}:"
                  + ", ".join(f"{x['name']}({x['stage']}·{x['why']}·{x['theme'] or '-'})" for x in off))
    hit = [x for x in day_all if x.get("aplus") == "A++"]
    missed = [c for c in aplus if c not in {x["code"] for x in day_all}]
    print(f"A++ 수동 도장 붙은 종목 {len(hit)}개" +
          (": " + ", ".join(f"{x['name']}({x['code']})" for x in hit) if hit else " — 배지 없음"))
    if missed:
        print(f"  ⚠ 오늘 핫바 일봉 대상이 아니라 못 붙은 도장: {', '.join(missed)}")
    print(json.dumps(day_counts, ensure_ascii=False))
    for k in sec:
        if k == "day":
            print(f"  day 1번(명부) {len(day_all)}종목 · 지금 1번 자리 {len(sec['day'][1])}종목")
        for s in STAGE_ORDER[k]:
            sample = ", ".join(x["name"] for x in sec[k][s][:8])
            print(f"  {k} {s}번 {len(sec[k][s])}종목: {sample}")
        if k != "day":
            a = sum(1 for s in STAGE_ORDER[k] for x in sec[k][s] if x.get("pos2") == "앞쪽")
            b = sum(1 for s in STAGE_ORDER[k] for x in sec[k][s] if x.get("pos2") == "뒤쪽")
            print(f"  {k} 앞쪽 {a} · 뒤쪽 {b} · 대장 "
                  f"{sum(1 for s in STAGE_ORDER[k] for x in sec[k][s] if x.get('leader'))}")
            for s in STAGE_ORDER[k]:
                for x in sec[k][s]:
                    print(f"    {k}{s} {x['name']}({x['code']}) {x.get('pos2')} {'/'.join(x.get('pos2_why') or []) or '-'} | {x['note']} | {x.get('theme')}")
    for x in sec["day"][4]:
        print(f"    4번 {x['name']} {x.get('note')} | {x.get('prog')} | 1번고점대비 {x.get('peak_dd')}% · 1년 {x.get('dd')}% · "
              f"차트 {len(x.get('candles') or [])}봉 · {x.get('reason')}")
    print("→", OUT, f"{os.path.getsize(OUT)/1024:.0f}KB")
    if getattr(args, "radar", False):
        apply_radar(amax, radar_rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true",
                    help="시세를 새로 받지 않고 오늘 캐시로만 계산")
    ap.add_argument("--fast", action="store_true",
                    help="30분 갱신용 — 오늘 봉만 배치로 받아 덮어쓰고(전 종목 재수신 없이) 10년 계산은 캐시로")
    ap.add_argument("--refresh-cache", action="store_true",
                    help="10년 원본 캐시(선뭉침·장기 이력)를 다시 계산")
    ap.add_argument("--fetch-only", action="store_true")
    ap.add_argument("--debug", default=None)
    ap.add_argument("--no-admin", action="store_true",
                    help="관리종목·거래정지 확인(네이버 기본정보)을 건너뛴다 — 시험 실행용")
    ap.add_argument("--no-risk", action="store_true",
                    help="재무·공시 위험 플래그(18-7)를 재지 않는다 — 시험 실행용")
    ap.add_argument("--dry", action="store_true",
                    help="형광↑ 팝업 자료(data/popup.json)를 쓰지 않고 요약만 본다")
    ap.add_argument("--radar", action="store_true",
                    help="레이더(data/radar.json · 잠금) 종목도 정리 — 평문 원본은 brain/cache/radar_plain.json")
    run(ap.parse_args())
