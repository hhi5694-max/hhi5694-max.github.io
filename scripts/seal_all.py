#!/usr/bin/env python3
"""data/*.json 전부 잠그기 — 평문은 저장소 밖 사본으로만 남긴다.

  python3 scripts/seal_all.py                 # data/*.json 전체를 {enc:1} 로 (평문 사본은 private-plain/data/)
  python3 scripts/seal_all.py --check         # 잠금 상태만 확인(고치지 않음), 평문이 있으면 exit 1
  python3 scripts/seal_all.py --code 1234     # 비밀코드를 직접 준다(기본: NR_CODE · private-plain/.picks_code)

비밀코드는 저장소에 적지 않는다. 이 스크립트는 collect_news · build_day125 · build_picks 끝에서도 불린다.
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nr_data as NR  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="data/*.json 전부 잠그기")
    ap.add_argument("--code", default="", help="비밀코드(기본: NR_CODE · private-plain/.picks_code)")
    ap.add_argument("--check", action="store_true", help="상태만 확인하고 고치지 않는다")
    ap.add_argument("--force", action="store_true",
                    help="평문 사본으로 data/*.json 전체를 다시 잠근다(비밀코드를 바꿀 때)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.check:
        names = sorted(f for f in os.listdir(NR.DATA) if f.endswith(".json"))
        bad = [f for f in names if not NR.is_sealed(NR.read_json(NR.public_path(f), None))]
        print(f"[check] data/*.json {len(names)}개 · 잠금 {len(names) - len(bad)}개"
              + (f" · 평문 {len(bad)}개: {', '.join(bad)}" if bad else " · 평문 0개"))
        raise SystemExit(1 if bad else 0)

    stats = NR.seal_all(args.code, verbose=not args.quiet, force=args.force)
    if stats["failed"]:
        print(f"[seal] 읽지 못한 파일: {', '.join(stats['failed'])}", file=sys.stderr)
    raise SystemExit(1 if stats["plain_left"] or stats["failed"] else 0)


if __name__ == "__main__":
    main()
