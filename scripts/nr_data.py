#!/usr/bin/env python3
"""자료 파일 공용 도우미 — 평문 사본은 저장소 밖, 공개 파일은 늘 잠금본.

  · 평문 사본   <저장소 밖>/private-plain/data/<이름>.json   (git 에 올리지 않는다)
  · 공개 파일   <저장소>/data/<이름>.json                    ({enc:1, salt, iv, ct})
  · 비밀코드    환경변수 NR_CODE / private-plain/.picks_code / --code (저장소에 적지 않는다)

이 모듈 하나만 있으면 다른 스크립트는 자료를 이렇게 다룬다.

    import nr_data as NR
    doc = NR.load("calendar.json", {})      # 평문 사본 → 없으면 잠금본을 풀어서
    NR.save("calendar.json", doc)           # 평문 사본 저장 + data/ 에 잠금본 저장

잠금 형식은 index.html 의 hotDecrypt 와 같다(AES-256-GCM · PBKDF2-SHA256 10만회).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
DATA = os.path.join(SITE, "data")

PBKDF2_ITER = 100000            # index.html 의 HOT_ITER 와 같아야 한다
PKG_ITER = 100000

CODE_ENVS = ("NR_CODE", "PICKS_PW")


# ------------------------------------------------------------------ 경로
def plain_root() -> str:
    """저장소 밖 비공개 폴더 — private-plain (환경변수로 바꿀 수 있다)."""
    env = os.environ.get("NEWSRADAR_PLAIN_DIR", "").strip()
    return env or os.path.join(os.path.dirname(SITE), "private-plain")


def plain_dir() -> str:
    """data/*.json 의 평문 사본을 두는 폴더."""
    return os.path.join(plain_root(), "data")


def flat_path(name: str) -> str:
    """예전부터 비공개 보드 자료를 두던 자리(private-plain/<이름>) — 사본을 겹쳐 만들지 않는다."""
    return os.path.join(plain_root(), name)


def plain_path(name: str) -> str:
    p = os.path.join(plain_dir(), name)
    if os.path.exists(p):
        return p
    f = flat_path(name)
    if os.path.exists(f):
        return f
    return p


def public_path(name: str) -> str:
    return os.path.join(DATA, name)


def ensure_plain_dir() -> str:
    d = plain_dir()
    os.makedirs(d, exist_ok=True)
    return d


# ------------------------------------------------------------------ 비밀코드
def code(explicit: str = "") -> str:
    """비밀코드 — 인자 → 환경변수 → private-plain/.picks_code → private-plain/.nr_code."""
    c = str(explicit or "").strip()
    if c:
        return c
    for k in CODE_ENVS:
        v = os.environ.get(k, "").strip()
        if v:
            return v
    for fn in (".picks_code", ".nr_code"):
        p = os.path.join(plain_root(), fn)
        try:
            with open(p, encoding="utf-8") as f:
                v = f.read().strip()
            if v:
                return v
        except OSError:
            continue
    return ""


# ------------------------------------------------------------------ 잠금
def seal(payload, pw: str) -> dict:
    """브라우저 Web Crypto 가 그대로 풀 수 있는 형태(AES-256-GCM · PBKDF2-SHA256 10만회)."""
    from Crypto.Cipher import AES
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    key = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, PBKDF2_ITER, dklen=32)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ct, tag = AES.new(key, AES.MODE_GCM, nonce=iv).encrypt_and_digest(raw)
    b64 = lambda x: base64.b64encode(x).decode("ascii")  # noqa: E731
    return {"enc": 1, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct + tag)}


def unseal(sealed: dict, pw: str):
    """잠금본을 푼다 — 태그가 맞지 않으면 ValueError."""
    from Crypto.Cipher import AES
    salt = base64.b64decode(sealed["salt"])
    iv = base64.b64decode(sealed["iv"])
    blob = base64.b64decode(sealed["ct"])
    key = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, PBKDF2_ITER, dklen=32)
    plain = AES.new(key, AES.MODE_GCM, nonce=iv).decrypt_and_verify(blob[:-16], blob[-16:])
    return json.loads(plain.decode("utf-8"))


def is_sealed(doc) -> bool:
    return isinstance(doc, dict) and doc.get("enc") == 1 and "ct" in doc


# ------------------------------------------------------------------ 읽기 · 쓰기
def read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path: str, doc, indent=None) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if indent is None:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(doc, f, ensure_ascii=False, indent=indent)
        f.write("\n")
    os.replace(tmp, path)


def load(name: str, default=None, pw: str = ""):
    """자료 하나를 평문으로 읽는다 — 평문 사본 → data/ 의 평문 → 잠금본을 풀어서."""
    p = plain_path(name)
    d = read_json(p, None)
    if d is not None:
        return d
    d = read_json(public_path(name), None)
    if d is None:
        return default
    if not is_sealed(d):
        return d
    key = code(pw)
    if not key:
        print(f"[warn] {name}: 평문 사본이 없고 비밀코드도 없습니다", file=sys.stderr)
        return default
    try:
        out = unseal(d, key)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] {name}: 잠금을 풀지 못했습니다({type(e).__name__})", file=sys.stderr)
        return default
    try:
        ensure_plain_dir()
        write_json(p, out)
    except OSError:
        pass
    return out


def save(name: str, doc, pw: str = "") -> None:
    """평문 사본을 남기고 data/ 에는 잠금본을 쓴다."""
    key = code(pw)
    if not key:
        raise SystemExit("비밀코드가 없습니다 — NR_CODE · private-plain/.picks_code 중 하나가 필요합니다")
    ensure_plain_dir()
    write_json(flat_path(name) if os.path.exists(flat_path(name)) else plain_path(name), doc)
    write_json(public_path(name), seal(doc, key))


# ------------------------------------------------------------------ 전체 잠금
def seal_all(pw: str = "", verbose: bool = True) -> dict:
    """data/*.json 전부를 잠근다.

    · 평문 파일이 있으면 평문 사본을 남기고 잠근다.
    · 이미 잠근 파일은 그대로 두고, 평문 사본이 없으면 풀어서 사본만 만들어 둔다.
    평문이 남아 있으면 마지막에 목록을 알려 준다(0 이어야 한다).
    """
    key = code(pw)
    if not key:
        raise SystemExit("비밀코드가 없습니다 — NR_CODE · private-plain/.picks_code 중 하나가 필요합니다")
    ensure_plain_dir()
    stats = {"sealed": [], "kept": [], "mirrored": [], "refreshed": [], "plain_left": [], "failed": []}
    if not os.path.isdir(DATA):
        return stats
    for fn in sorted(os.listdir(DATA)):
        if not fn.endswith(".json"):
            continue
        p = public_path(fn)
        d = read_json(p, None)
        if d is None:
            stats["failed"].append(fn)
            continue
        if is_sealed(d):
            stats["kept"].append(fn)
            if not os.path.exists(plain_path(fn)) and not os.path.exists(flat_path(fn)):
                try:
                    write_json(plain_path(fn), unseal(d, key))
                    stats["mirrored"].append(fn)
                except Exception as e:  # noqa: BLE001
                    print(f"[warn] {fn}: 사본을 만들지 못했습니다({type(e).__name__})", file=sys.stderr)
            continue
        write_json(plain_path(fn), d)
        write_json(p, seal(d, key))
        stats["sealed"].append(fn)
    # ② 평문 사본이 공개본보다 새로우면 다시 잠근다 — 수집기가 private-plain/data 에 새로 쓴 자료가
    #    data/ 로 올라오는 길이다(공개본이 없거나 사본이 더 최근일 때만).
    stats["refreshed"] = []
    pd = plain_dir()
    if os.path.isdir(pd):
        for fn in sorted(os.listdir(pd)):
            if not fn.endswith(".json"):
                continue
            src = os.path.join(pd, fn)
            dst = public_path(fn)
            try:
                if os.path.exists(dst) and os.path.getmtime(src) <= os.path.getmtime(dst):
                    continue
                doc = read_json(src, None)
                if doc is None:
                    continue
                write_json(dst, seal(doc, key))
                stats["refreshed"].append(fn)
            except Exception as e:  # noqa: BLE001
                print(f"[warn] {fn}: 잠그지 못했습니다({type(e).__name__})", file=sys.stderr)
                stats["failed"].append(fn)
    for fn in sorted(os.listdir(DATA)):
        if fn.endswith(".json") and not is_sealed(read_json(public_path(fn), None)):
            stats["plain_left"].append(fn)
    if verbose:
        print(f"[seal] 새로 잠금 {len(stats['sealed'])} · 이미 잠금 {len(stats['kept'])}"
              f" · 평문 사본 보충 {len(stats['mirrored'])} · 사본에서 갱신 {len(stats['refreshed'])}")
        if stats["plain_left"]:
            print(f"[seal] !! 아직 평문이 남은 파일: {', '.join(stats['plain_left'])}", file=sys.stderr)
    return stats
