"""
호출코드 1 — 해파리정보 (국립수산과학원 NIFS)

  id=jellyList  ·  인증키: .env 의 NIFS_JELLY_KEY

해파리 주간보고 게시물 목록을 받아 JSON으로 반환한다.
호출 주기: 24시간에 1회. 요청 파라미터에는 주기·간격 값을 싣지 않는다.

주의: 이 API는 관측 수치가 아니라 '주간보고 게시물 목록'을 준다.
      (board_idx, board_subject, board_writer, inpt_date, gbn)
      실제 해파리 밀도·분포 수치는 각 보고서 본문(PDF/HWP)에 있다.

사용 예:
  python3 해파리정보_수집.py                      # 최근 30일
  python3 해파리정보_수집.py --days 180           # 최근 180일
  python3 해파리정보_수집.py --sdate 20260101 --edate 20260822
  python3 해파리정보_수집.py -o jelly.json --compact

하루 1회 실행 (crontab 예: 매일 03:20):
  20 3 * * * cd /경로 && /usr/bin/python3 해파리정보_수집.py -o /경로/jelly.json -q

서버 전송 시:
  from 해파리정보_수집 import build_dataset
  requests.post(url, json=build_dataset())
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

KST = timezone(timedelta(hours=9))

ENDPOINT = "https://www.nifs.go.kr/api/OpenAPI_json"
# 문서에 안내된 https://www.nifs.go.kr/OpenAPI_json 은 여기로 302 리다이렉트된다

DATASET_ID = "jellyList"
DEFAULT_DAYS = 30


def load_env(filename=".env"):
    """스크립트와 같은 폴더의 .env를 읽어 환경변수로 올린다.

    이미 설정된 실제 환경변수가 있으면 그쪽을 우선한다.
    """
    path = Path(__file__).resolve().parent / filename
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def call_api(key, sdate, edate, retries=3):
    """NIFS API를 호출해 (header, items)를 돌려준다."""
    params = {"id": DATASET_ID, "key": key, "sdate": sdate, "edate": edate}

    last = None
    for attempt in range(retries):
        try:
            resp = requests.get(ENDPOINT, params=params, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            break
        except Exception as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    else:
        raise RuntimeError(f"요청 실패: {last}")

    header = payload.get("header", {}) or {}
    body = payload.get("body", {}) or {}
    items = body.get("item", []) or []
    if isinstance(items, dict):
        items = [items]
        # 결과 1건이면 dict로 오므로 list로 통일한다
    return header, items


def build_dataset(sdate=None, edate=None, days=DEFAULT_DAYS, verbose=False):
    """해파리정보 데이터셋을 만들어 dict로 돌려준다.

    sdate / edate : 'YYYYMMDD'. 미지정 시 오늘 기준 최근 days일.
    """
    load_env()
    started = datetime.now(KST)

    key = os.environ.get("NIFS_JELLY_KEY")
    if not key:
        raise SystemExit("NIFS_JELLY_KEY 가 없다. .env 를 확인할 것.")

    if not edate:
        edate = started.strftime("%Y%m%d")
    if not sdate:
        sdate = (started - timedelta(days=days)).strftime("%Y%m%d")

    def log(msg):
        if verbose:
            print(msg, file=sys.stderr)

    log(f"해파리정보 조회: {sdate} ~ {edate}")

    warnings = []
    try:
        header, items = call_api(key, sdate, edate)
        status = header.get("resultCode")
        message = header.get("resultMsg", "")
    except RuntimeError as exc:
        header, items = {}, []
        status, message = "ERR", str(exc)[:120]
        warnings.append(f"호출 실패: {message}")

    if status not in ("00", "ERR"):
        warnings.append(f"API 오류 {status}: {message}")
    if status == "00" and not items:
        warnings.append(
            f"{sdate}~{edate} 구간에 게시물이 없다. --days 를 늘려 재시도할 것."
        )

    dates = sorted(i.get("inpt_date", "") for i in items if i.get("inpt_date"))

    return {
        "meta": {
            "dataset": "해파리정보",
            "source": {"agency": "국립수산과학원", "api": DATASET_ID,
                       "endpoint": ENDPOINT},
            "generated_at": started.isoformat(),
            "elapsed_sec": round((datetime.now(KST) - started).total_seconds(), 1),
            "call_cycle": "24h",
            "period": {"sdate": sdate, "edate": edate},
            "result": {"code": status, "message": message},
            "count": len(items),
            "inpt_date_range": ([dates[0], dates[-1]] if dates else None),
            "note": "관측 수치가 아니라 해파리 주간보고 게시물 목록이다.",
            "warnings": warnings,
        },
        "items": items,
    }


def main():
    ap = argparse.ArgumentParser(
        description="해파리정보(NIFS jellyList) 수집. 24시간에 1회 실행을 전제로 한다.")
    ap.add_argument("--sdate", help="조회 시작일 YYYYMMDD")
    ap.add_argument("--edate", help="조회 종료일 YYYYMMDD")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"sdate 미지정 시 최근 며칠 (기본 {DEFAULT_DAYS})")
    ap.add_argument("--compact", action="store_true", help="들여쓰기 없이 출력")
    ap.add_argument("-o", "--output", help="저장할 파일 경로 (미지정 시 표준출력)")
    ap.add_argument("-q", "--quiet", action="store_true", help="진행 로그 숨김")
    args = ap.parse_args()

    data = build_dataset(sdate=args.sdate, edate=args.edate, days=args.days,
                         verbose=not args.quiet)
    text = json.dumps(data, ensure_ascii=False, indent=None if args.compact else 2)

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        m = data["meta"]
        print(f"저장: {args.output}  {m['count']}건 "
              f"({m['period']['sdate']}~{m['period']['edate']})", file=sys.stderr)
    else:
        print(text)

    for w in data["meta"]["warnings"]:
        print(f"경고: {w}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
