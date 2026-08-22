"""
호출코드 2 — 적조정보 + 정선해양관측정보 (국립수산과학원 NIFS)

  id=redtideList  ·  인증키: .env 의 NIFS_REDTIDE_KEY
  id=sooList      ·  인증키: .env 의 NIFS_SOO_KEY

두 데이터셋을 각각 호출해 **하나의 JSON**으로 묶어 반환한다.
연산·병합·보정은 하지 않고 원자료를 그대로 나란히 담기만 한다.
호출 주기: 24시간에 1회. 요청 파라미터에는 주기·간격 값을 싣지 않는다.

조회 기간 기본값이 서로 다르다:
  적조정보     — 수시 발표라 최근 30일이면 충분
  정선해양관측 — 연 몇 회 정기 조사라 30일로 잡으면 0건이 나온다. 기본 365일.

사용 예:
  python3 적조_정선해양_수집.py                          # 적조 30일 + 정선 365일
  python3 적조_정선해양_수집.py --redtide-days 90
  python3 적조_정선해양_수집.py --soo-days 730
  python3 적조_정선해양_수집.py --sdate 20260101 --edate 20260822   # 둘 다 동일 기간
  python3 적조_정선해양_수집.py -o nifs.json --compact

하루 1회 실행 (crontab 예: 매일 03:30):
  30 3 * * * cd /경로 && /usr/bin/python3 적조_정선해양_수집.py -o /경로/nifs.json -q

서버 전송 시:
  from 적조_정선해양_수집 import build_dataset
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

DATASETS = {
    "redtide": {
        "id": "redtideList", "env": "NIFS_REDTIDE_KEY",
        "label": "적조정보", "default_days": 30,
    },
    "soo": {
        "id": "sooList", "env": "NIFS_SOO_KEY",
        "label": "정선해양관측정보", "default_days": 365,
    },
}


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


def call_api(dataset_id, key, sdate, edate, retries=3):
    """NIFS API를 호출해 (header, items)를 돌려준다."""
    params = {"id": dataset_id, "key": key, "sdate": sdate, "edate": edate}

    last = None
    for attempt in range(retries):
        try:
            resp = requests.get(ENDPOINT, params=params, timeout=60)
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


def fetch_section(name, sdate, edate, verbose=False):
    """데이터셋 1종을 받아 섹션 dict로 만든다. 원자료는 가공하지 않는다."""
    spec = DATASETS[name]
    key = os.environ.get(spec["env"])

    section = {
        "label": spec["label"], "api": spec["id"],
        "period": {"sdate": sdate, "edate": edate},
        "result": {}, "count": 0, "items": [], "warnings": [],
    }

    if not key:
        section["result"] = {"code": "NOKEY", "message": f'{spec["env"]} 없음'}
        section["warnings"].append(f'{spec["env"]} 가 .env 에 없다.')
        return section

    if verbose:
        print(f'{spec["label"]} 조회: {sdate} ~ {edate}', file=sys.stderr)

    try:
        header, items = call_api(spec["id"], key, sdate, edate)
        code = header.get("resultCode")
        message = header.get("resultMsg", "")
    except RuntimeError as exc:
        section["result"] = {"code": "ERR", "message": str(exc)[:120]}
        section["warnings"].append(f'{spec["label"]} 호출 실패')
        return section

    section["result"] = {"code": code, "message": message}
    section["count"] = len(items)
    section["items"] = items
    # 연산하지 않고 원자료를 그대로 싣는다

    if code != "00":
        section["warnings"].append(f'{spec["label"]} API 오류 {code}: {message}')
    elif not items:
        section["warnings"].append(
            f'{spec["label"]} {sdate}~{edate} 구간에 자료가 없다. 조회 기간을 늘릴 것.'
        )
    return section


def build_dataset(sdate=None, edate=None, redtide_days=None, soo_days=None,
                  verbose=False):
    """적조정보와 정선해양관측정보를 하나의 dict로 묶어 돌려준다.

    sdate / edate : 'YYYYMMDD'. 지정하면 두 데이터셋에 같은 기간을 적용한다.
                    미지정 시 데이터셋별 기본 일수를 각각 적용한다.
    """
    load_env()
    started = datetime.now(KST)
    today = started.strftime("%Y%m%d")

    def period_for(name, days_override):
        if sdate or edate:
            return (sdate or (started - timedelta(days=DATASETS[name]["default_days"])
                              ).strftime("%Y%m%d"),
                    edate or today)
        days = days_override or DATASETS[name]["default_days"]
        return ((started - timedelta(days=days)).strftime("%Y%m%d"), today)

    rt_s, rt_e = period_for("redtide", redtide_days)
    soo_s, soo_e = period_for("soo", soo_days)

    redtide = fetch_section("redtide", rt_s, rt_e, verbose)
    soo = fetch_section("soo", soo_s, soo_e, verbose)

    warnings = redtide["warnings"] + soo["warnings"]

    return {
        "meta": {
            "dataset": "적조정보 + 정선해양관측정보",
            "source": {"agency": "국립수산과학원", "endpoint": ENDPOINT},
            "generated_at": started.isoformat(),
            "elapsed_sec": round((datetime.now(KST) - started).total_seconds(), 1),
            "call_cycle": "24h",
            "merge_policy": "연산 없이 두 데이터셋을 나란히 담기만 함",
            "counts": {
                "redtide": redtide["count"], "soo": soo["count"],
                "total": redtide["count"] + soo["count"],
            },
            "warnings": warnings,
        },
        "redtide": redtide,
        "soo": soo,
    }


def main():
    ap = argparse.ArgumentParser(
        description="적조정보 + 정선해양관측정보(NIFS) 수집. 24시간에 1회 실행을 전제로 한다.")
    ap.add_argument("--sdate", help="조회 시작일 YYYYMMDD (지정 시 두 데이터셋 공통)")
    ap.add_argument("--edate", help="조회 종료일 YYYYMMDD (지정 시 두 데이터셋 공통)")
    ap.add_argument("--redtide-days", type=int,
                    help=f'적조 조회 일수 (기본 {DATASETS["redtide"]["default_days"]})')
    ap.add_argument("--soo-days", type=int,
                    help=f'정선해양 조회 일수 (기본 {DATASETS["soo"]["default_days"]})')
    ap.add_argument("--compact", action="store_true", help="들여쓰기 없이 출력")
    ap.add_argument("-o", "--output", help="저장할 파일 경로 (미지정 시 표준출력)")
    ap.add_argument("-q", "--quiet", action="store_true", help="진행 로그 숨김")
    args = ap.parse_args()

    data = build_dataset(sdate=args.sdate, edate=args.edate,
                         redtide_days=args.redtide_days, soo_days=args.soo_days,
                         verbose=not args.quiet)
    text = json.dumps(data, ensure_ascii=False, indent=None if args.compact else 2)

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        c = data["meta"]["counts"]
        print(f"저장: {args.output}  {len(text)/1048576:.2f}MB\n"
              f"  적조 {c['redtide']}건 / 정선해양 {c['soo']}건 (합 {c['total']}건)",
              file=sys.stderr)
    else:
        print(text)

    for w in data["meta"]["warnings"]:
        print(f"경고: {w}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
