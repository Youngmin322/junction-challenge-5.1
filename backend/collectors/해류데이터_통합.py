"""
전국 해역 해류 통합 데이터셋 생성기.

국립해양조사원 오픈API 2종을 호출해 하나의 스키마로 병합하고 JSON으로 반환한다.

  - twRecent  : 해양관측부이 (38개소) — 점 관측, 긴 시계열, 해류+수온/염분/바람/파랑
  - hfCurrent : 해수유동 HF-RADAR (13개소) — 격자 관측, 시각당 스냅샷, 해류만

두 API는 축이 서로 전치되어 있다(부이=1좌표×N시각, 레이더=N좌표×1시각).
병합은 24개 정시 슬롯에 양쪽을 스냅해 맞춘다.

호출 주기: 24시간에 1회. 하루치를 통째로 받는 구조이므로
API 요청 파라미터에는 주기·간격을 뜻하는 값(`min` 등)을 싣지 않는다.
부이는 관측소 고유 해상도(1~10분)로 그대로 받는다.

출력: 표준출력 또는 파일. CSV는 만들지 않는다.

  observations : 24개 정시 슬롯에 부이·레이더를 맞춘 통합 유속장
  buoy_series  : 부이 원해상도 시계열 (--no-series로 제외)

사용 예:
  python3 해류데이터_통합.py                        # 최근 24시간
  python3 해류데이터_통합.py --date 20260821        # 특정 날짜 하루치
  python3 해류데이터_통합.py --hours 6              # 범위 축소
  python3 해류데이터_통합.py --format geojson       # 지도용 GeoJSON
  python3 해류데이터_통합.py -o dataset.json --compact

하루 1회 실행 (crontab 예: 매일 03:10):
  10 3 * * * cd /경로 && /usr/bin/python3 해류데이터_통합.py -o /경로/dataset.json -q

서버 전송 시:
  from 해류데이터_통합 import build_dataset
  payload = build_dataset()
  requests.post(url, json=payload)
"""

import argparse
import json
import math
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

KST = timezone(timedelta(hours=9))


def load_env(filename=".env"):
    """스크립트와 같은 폴더의 .env를 읽어 환경변수로 올린다.

    이미 설정된 실제 환경변수가 있으면 그쪽을 우선한다.
    """
    from pathlib import Path
    path = Path(__file__).resolve().parent / filename
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

SERVICE_KEY = os.environ.get("KHOA_SERVICE_KEY", "")
if not SERVICE_KEY:
    raise SystemExit("KHOA_SERVICE_KEY 가 없다. .env 를 확인할 것.")

TW_ENDPOINT = "https://apis.data.go.kr/1192136/twRecent/GetTWRecentApiService"
HF_ENDPOINT = "https://apis.data.go.kr/1192136/hfCurrent/GetHFCurrentApiService"

MAX_ROWS = 300
# API 페이지당 최대 건수

DIR_CONVENTION_VERIFIED = False
# crdir이 '흘러가는 방향'인지 미검증 상태다. False인 동안 메타에 경고를 싣는다.

TW_STATIONS = {
    "HB_0001": "한수원_기장", "HB_0002": "한수원_고리", "HB_0003": "한수원_진하",
    "HB_0007": "한수원_온양", "HB_0008": "한수원_덕천", "HB_0009": "한수원_나곡",
    "KG_0021": "제주남부", "KG_0024": "대한해협", "KG_0025": "남해동부",
    "KG_0028": "제주해협", "KG_0101": "울릉도북동", "KG_0102": "울릉도북서",
    "TW_0062": "해운대해수욕장", "TW_0069": "대천해수욕장", "TW_0070": "평택당진항",
    "TW_0072": "군산항", "TW_0074": "광양항", "TW_0075": "중문해수욕장",
    "TW_0076": "인천항", "TW_0077": "경인항", "TW_0078": "완도항",
    "TW_0079": "상왕등도", "TW_0080": "우이도", "TW_0081": "생일도",
    "TW_0082": "태안항", "TW_0083": "여수항", "TW_0084": "통영항",
    "TW_0085": "마산항", "TW_0086": "부산항신항", "TW_0087": "부산항",
    "TW_0088": "감천항", "TW_0089": "경포대해수욕장", "TW_0090": "송정해수욕장",
    "TW_0091": "낙산해수욕장", "TW_0092": "임랑해수욕장", "TW_0093": "속초해수욕장",
    "TW_0094": "망상해수욕장", "TW_0095": "고래불해수욕장",
}

HF_STATIONS = {
    "HF_0039": "여수해만", "HF_0040": "부산항신항", "HF_0041": "대한해협",
    "HF_0063": "울산항", "HF_0064": "광양항", "HF_0065": "여수광양항",
    "HF_0069": "인천항", "HF_0070": "태안대산", "HF_0071": "포항항",
    "HF_0073": "동해남부", "HF_0074": "목포항외측", "HF_0075": "목포항내측",
    "HF_0076": "군산항",
}

BUOY_EXTRA_FIELDS = [
    "wtem", "slnty", "wndrct", "wspd", "maxMmntWspd",
    "artmp", "atmpr", "wvhgt", "wvpd",
]

_local = threading.local()


def session():
    """스레드별 requests 세션을 재사용한다."""
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
    return _local.s


def classify_region(lat, lon):
    """좌표로 해역을 대략 분류한다. 경계 지점은 부정확할 수 있는 참고값이다."""
    if lat is None or lon is None:
        return None
    if lat < 33.8:
        return "제주"
    if lon >= 128.8 and lat >= 35.15:
        return "동해"
    if lat < 35.5:
        return "남해"
    return "서해"


def to_uv(dir_deg, speed_cms):
    """유향(deg)·유속(cm/s)을 동/북 성분 (u, v) m/s로 변환한다.

    crdir을 '흘러가는 방향, 북 기준 시계방향'으로 가정한다.
    이 가정이 틀리면 모든 벡터가 180도 반대가 되므로 DIR_CONVENTION_VERIFIED 참고.
    """
    if dir_deg is None or speed_cms is None:
        return None, None
    theta = math.radians(dir_deg)
    speed = speed_cms / 100.0
    return round(speed * math.sin(theta), 5), round(speed * math.cos(theta), 5)


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def parse_ts(text):
    """'YYYY-MM-DD HH:MM'을 KST aware datetime으로 바꾼다."""
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    except (TypeError, ValueError):
        return None


def call_api(endpoint, params, retries=3):
    """API를 호출해 (header, items, totalCount)를 돌려준다."""
    last = None
    for attempt in range(retries):
        try:
            resp = session().get(endpoint, params=params, timeout=20)
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
    items = (body.get("items") or {}).get("item", []) or []
    if isinstance(items, dict):
        items = [items]
        # 결과 1건이면 dict로 오므로 list로 통일한다
    return header, items, body.get("totalCount")


def fetch_all_pages(endpoint, base_params):
    """totalCount를 보고 남은 페이지까지 모두 받는다."""
    params = dict(base_params, pageNo=1, numOfRows=MAX_ROWS)
    header, items, total = call_api(endpoint, params)

    code = header.get("resultCode")
    if code != "00":
        return code, header.get("resultMsg", ""), []

    rows = list(items)
    if total and total > MAX_ROWS:
        pages = -(-total // MAX_ROWS)
        for page in range(2, pages + 1):
            try:
                _, more, _ = call_api(endpoint, dict(params, pageNo=page))
                rows.extend(more)
            except RuntimeError:
                break
    return "00", "", rows


def fetch_buoy(code, name, date_str):
    """부이 1개소의 하루치를 관측소 고유 해상도로 받아 정규화한다.

    하루 1회만 호출하므로 출력 간격(`min`)을 지정하지 않고 원자료를 그대로 받는다.
    """
    params = {"serviceKey": SERVICE_KEY, "type": "json", "obsCode": code}
    if date_str:
        params["reqDate"] = date_str

    try:
        rc, msg, rows = fetch_all_pages(TW_ENDPOINT, params)
    except RuntimeError as exc:
        return {"code": code, "name": name, "status": "호출실패", "detail": str(exc)[:80]}, []

    if rc != "00":
        return {"code": code, "name": name, "status": "오류", "detail": f"{rc} {msg}"}, []

    out = []
    for r in rows:
        lat, lon = r.get("lat"), r.get("lot")
        if lat is None or lon is None or r.get("crdir") is None:
            continue
            # 좌표나 유향이 없으면 이류 계산에 못 쓴다
        ts = parse_ts(r.get("obsrvnDt"))
        if ts is None:
            continue
        u, v = to_uv(r.get("crdir"), r.get("crsp"))
        extra = {k: r.get(k) for k in BUOY_EXTRA_FIELDS if r.get(k) is not None}
        out.append({
            "src": "buoy", "code": code, "name": r.get("obsvtrNm") or name,
            "region": classify_region(lat, lon),
            "lat": lat, "lon": lon, "ts": ts,
            "dir_deg": r.get("crdir"), "speed_cms": r.get("crsp"),
            "u_ms": u, "v_ms": v,
            "extra": extra,
        })

    if not out:
        return {"code": code, "name": name, "status": "데이터없음",
                "detail": "응답은 정상이나 유효 관측값 없음"}, []

    latest = max(x["ts"] for x in out)
    return {
        "code": code, "name": name, "status": "정상", "detail": "",
        "lat": out[0]["lat"], "lon": out[0]["lon"], "region": out[0]["region"],
        "records": len(out), "latest": latest.isoformat(),
    }, out


def fetch_radar(code, name, hour_str):
    """HF-RADAR 1개소의 한 시각 격자를 받아 정규화한다."""
    params = {"serviceKey": SERVICE_KEY, "type": "json", "obsCode": code}
    if hour_str:
        params["reqDate"] = hour_str

    try:
        rc, msg, rows = fetch_all_pages(HF_ENDPOINT, params)
    except RuntimeError as exc:
        return {"code": code, "name": name, "status": "호출실패", "detail": str(exc)[:80]}, []

    if rc != "00":
        return {"code": code, "name": name, "status": "오류", "detail": f"{rc} {msg}"}, []

    out = []
    for r in rows:
        lat, lon = r.get("lat"), r.get("lot")
        if lat is None or lon is None or r.get("crdir") is None:
            continue
        ts = parse_ts(r.get("obsrvnDt"))
        if ts is None:
            continue
        u, v = to_uv(r.get("crdir"), r.get("crsp"))
        out.append({
            "src": "radar", "code": code, "name": r.get("obsvtrNm") or name,
            "region": classify_region(lat, lon),
            "lat": lat, "lon": lon, "ts": ts,
            "dir_deg": r.get("crdir"), "speed_cms": r.get("crsp"),
            "u_ms": u, "v_ms": v,
        })

    if not out:
        return {"code": code, "name": name, "status": "데이터없음",
                "detail": "응답은 정상이나 격자값이 모두 null"}, []

    lats = [x["lat"] for x in out]
    lons = [x["lon"] for x in out]
    latest = max(x["ts"] for x in out)
    return {
        "code": code, "name": name, "status": "정상", "detail": "",
        "region": out[0]["region"], "grid_points": len(out),
        "bbox": [round(min(lons), 5), round(min(lats), 5),
                 round(max(lons), 5), round(max(lats), 5)],
        "records": len(out), "latest": latest.isoformat(),
    }, out


def probe_base_hour(sample_codes=("HF_0076", "HF_0039", "HF_0069", "HF_0065")):
    """레이더 몇 곳을 찔러 실제로 발행된 최신 정시를 찾는다.

    HF-RADAR는 발행 지연이 2~3시간에 이르므로 벽시계로 기준 시각을 잡으면
    레이더가 통째로 탈락한다. 실제 자료가 있는 시각을 기준으로 삼는다.
    """
    best = None
    for code in sample_codes:
        try:
            _, items, _ = call_api(HF_ENDPOINT, {
                "serviceKey": SERVICE_KEY, "type": "json",
                "obsCode": code, "numOfRows": 1, "pageNo": 1,
            }, retries=2)
        except RuntimeError:
            continue
        if not items:
            continue
        ts = parse_ts(items[0].get("obsrvnDt"))
        if ts and (best is None or ts > best):
            best = ts
    if best is None:
        return None
    return best.replace(minute=0, second=0, microsecond=0)


def snap_to_hours(records, target_hours, tolerance_min):
    """각 관측소·시각별로 목표 시각에 가장 가까운 1건만 남긴다."""
    picked = {}
    for rec in records:
        for target in target_hours:
            gap = abs((rec["ts"] - target).total_seconds()) / 60
            if gap > tolerance_min:
                continue
            key = (rec["code"], rec["lat"], rec["lon"], target)
            # 격자형은 좌표까지 포함해야 유일키가 성립한다
            if key not in picked or gap < picked[key][0]:
                picked[key] = (gap, rec, target)

    out = []
    for gap, rec, target in picked.values():
        item = dict(rec)
        item["slot"] = target
        item["age_min"] = round(gap, 1)
        out.append(item)
    return out


def cross_validate(records, radius_km=3.0):
    """레이더 격자 안에 있는 부이를 찾아 두 관측의 차이를 계산한다.

    같은 지점을 서로 다른 방식으로 관측한 값이므로, 차이가 크면
    그 시각 유속장의 신뢰도가 낮다는 신호로 쓴다.
    """
    results = []
    by_slot = {}
    for r in records:
        by_slot.setdefault(r["slot"], {"buoy": [], "radar": []})[r["src"]].append(r)

    for slot, group in by_slot.items():
        for b in group["buoy"]:
            best = None
            for g in group["radar"]:
                d = haversine_km(b["lat"], b["lon"], g["lat"], g["lon"])
                if d <= radius_km and (best is None or d < best[0]):
                    best = (d, g)
            if best is None:
                continue
            d, g = best
            if b["speed_cms"] is None or g["speed_cms"] is None:
                continue
            diff = (b["dir_deg"] - g["dir_deg"] + 180) % 360 - 180
            # 각도 차이를 -180~180 범위로 정규화한다
            results.append({
                "slot": slot.isoformat(),
                "buoy": b["code"], "radar": g["code"],
                "distance_km": round(d, 2),
                "buoy_speed_cms": b["speed_cms"], "radar_speed_cms": g["speed_cms"],
                "speed_diff_cms": round(b["speed_cms"] - g["speed_cms"], 2),
                "dir_diff_deg": round(diff, 1),
            })
    return results


def build_dataset(date=None, at=None, hours=24, tolerance_min=60,
                  workers=6, include_extra=True, include_series=True, verbose=False):
    """전국 해역 해류 통합 데이터셋을 만들어 dict로 돌려준다.

    24시간에 1회 실행을 전제로 기본 24개 정시 슬롯을 만든다.

    date          : 대상 날짜 'YYYYMMDD'. 지정 시 그날 00~23시를 대상으로 한다.
    at            : 마지막 슬롯 시각 'YYYYMMDDHH'. 미지정 시 레이더 최신 정시를 쓴다.
    hours         : 슬롯 수 (기본 24).
    tolerance_min : 슬롯 시각과 이만큼 이내인 관측만 채택한다.
    """
    started = datetime.now(KST)

    def log(msg):
        if verbose:
            print(msg, file=sys.stderr)

    probed = None
    if date:
        base_hour = datetime.strptime(date, "%Y%m%d").replace(hour=23, tzinfo=KST)
        hours = 24
        # 날짜를 주면 그날 00~23시 전체로 고정한다
    elif at:
        base_hour = datetime.strptime(at, "%Y%m%d%H").replace(tzinfo=KST)
    else:
        probed = probe_base_hour()
        base_hour = probed or (started.replace(minute=0, second=0, microsecond=0)
                               - timedelta(hours=2))
        # 레이더 발행 지연이 커서 벽시계 기준으로는 맞출 수 없다
        log(f"기준 시각 탐침: {base_hour.isoformat()}"
            + ("" if probed else " (레이더 응답 없어 벽시계 -2시간으로 대체)"))

    target_hours = [base_hour - timedelta(hours=i) for i in range(hours)][::-1]
    dates_needed = sorted({t.strftime("%Y%m%d") for t in target_hours})

    records = []
    station_acc = {}

    buoy_jobs = [(c, n, d) for c, n in TW_STATIONS.items() for d in dates_needed]
    radar_jobs = [(c, n, t.strftime("%Y%m%d%H"))
                  for c, n in HF_STATIONS.items() for t in target_hours]

    log(f"부이 {len(buoy_jobs)}건, 레이더 {len(radar_jobs)}건 호출")

    def accumulate(st, rows):
        """관측소를 코드 단위로 합친다. 정상 응답이 하나라도 있으면 정상으로 본다."""
        cur = station_acc.get(st["code"])
        if cur is None:
            station_acc[st["code"]] = dict(st)
        elif st["status"] == "정상":
            if cur["status"] != "정상":
                station_acc[st["code"]] = dict(st)
            else:
                cur["records"] = cur.get("records", 0) + st.get("records", 0)
                if st.get("latest", "") > cur.get("latest", ""):
                    cur["latest"] = st["latest"]
        records.extend(rows)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        buoy_futs = [pool.submit(fetch_buoy, c, n, d) for c, n, d in buoy_jobs]
        radar_futs = [pool.submit(fetch_radar, c, n, h) for c, n, h in radar_jobs]
        for fut in buoy_futs + radar_futs:
            accumulate(*fut.result())

    stations = list(station_acc.values())
    raw_buoy = [r for r in records if r["src"] == "buoy"]

    merged = snap_to_hours(records, target_hours, tolerance_min)
    merged.sort(key=lambda r: (r["slot"], r["src"], r["code"]))

    xval = cross_validate(merged)

    observations = []
    for r in merged:
        item = {
            "src": r["src"], "code": r["code"], "name": r["name"],
            "region": r["region"],
            "lat": r["lat"], "lon": r["lon"],
            "ts": r["ts"].isoformat(), "slot": r["slot"].isoformat(),
            "age_min": r["age_min"],
            "dir_deg": r["dir_deg"], "speed_cms": r["speed_cms"],
            "u_ms": r["u_ms"], "v_ms": r["v_ms"],
        }
        if include_extra and r.get("extra"):
            item["extra"] = r["extra"]
        observations.append(item)

    lats = [o["lat"] for o in observations]
    lons = [o["lon"] for o in observations]
    n_buoy = sum(1 for o in observations if o["src"] == "buoy")
    n_radar = len(observations) - n_buoy

    by_region = {}
    for o in observations:
        reg = by_region.setdefault(o["region"] or "미분류", {"buoy": 0, "radar": 0})
        reg[o["src"]] += 1

    warnings = []
    if not DIR_CONVENTION_VERIFIED:
        warnings.append(
            "crdir 방향 정의(흘러가는 방향/흘러오는 방향)가 미검증 상태다. "
            "u_ms, v_ms는 '흘러가는 방향' 가정으로 계산했으며 반대일 경우 부호를 뒤집어야 한다."
        )
    stale = [s for s in stations if s["status"] == "정상" and s.get("latest")
             and (base_hour - datetime.fromisoformat(s["latest"])).total_seconds() > 6 * 3600]
    if stale:
        warnings.append(
            f"기준 시각보다 6시간 이상 오래된 관측소 {len(stale)}곳: "
            + ", ".join(f'{s["code"]}({s["name"]})' for s in stale[:8])
        )

    buoy_series = []
    if include_series:
        for r in sorted(raw_buoy, key=lambda x: (x["code"], x["ts"])):
            item = {
                "code": r["code"], "name": r["name"], "region": r["region"],
                "lat": r["lat"], "lon": r["lon"], "ts": r["ts"].isoformat(),
                "dir_deg": r["dir_deg"], "speed_cms": r["speed_cms"],
                "u_ms": r["u_ms"], "v_ms": r["v_ms"],
            }
            if include_extra and r.get("extra"):
                item["extra"] = r["extra"]
            buoy_series.append(item)

    result = {
        "meta": {
            "generated_at": started.isoformat(),
            "elapsed_sec": round((datetime.now(KST) - started).total_seconds(), 1),
            "base_hour": base_hour.isoformat(),
            "slots": [t.isoformat() for t in target_hours],
            "call_cycle": "24h",
            "params": {
                "hours": hours, "tolerance_min": tolerance_min,
                "date": date, "at": at,
            },
            "sources": {
                "buoy": {"api": "twRecent", "endpoint": TW_ENDPOINT,
                         "stations": len(TW_STATIONS)},
                "radar": {"api": "hfCurrent", "endpoint": HF_ENDPOINT,
                          "stations": len(HF_STATIONS)},
            },
            "units": {
                "dir_deg": "도(북 기준 시계방향)", "speed_cms": "cm/s",
                "u_ms": "m/s 동성분", "v_ms": "m/s 북성분",
            },
            "counts": {
                "total": len(observations), "buoy": n_buoy, "radar": n_radar,
                "buoy_series": len(buoy_series),
            },
            "by_region": by_region,
            "bbox": ([round(min(lons), 5), round(min(lats), 5),
                      round(max(lons), 5), round(max(lats), 5)] if observations else None),
            "station_status": {
                s: sum(1 for x in stations if x["status"] == s)
                for s in {x["status"] for x in stations}
            },
            "warnings": warnings,
        },
        "stations": sorted(stations, key=lambda s: s["code"]),
        "cross_validation": xval,
        "observations": observations,
    }
    if include_series:
        result["buoy_series"] = buoy_series
    return result


def to_geojson(dataset):
    """관측점을 GeoJSON FeatureCollection으로 변환한다."""
    features = []
    for o in dataset["observations"]:
        props = {k: v for k, v in o.items() if k not in ("lat", "lon")}
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [o["lon"], o["lat"]]},
            "properties": props,
        })
    return {"type": "FeatureCollection", "meta": dataset["meta"], "features": features}


def main():
    ap = argparse.ArgumentParser(
        description="전국 해역 해류 통합 데이터셋 (JSON). 24시간에 1회 실행을 전제로 한다.")
    ap.add_argument("--date", help="대상 날짜 YYYYMMDD (그날 00~23시 전체)")
    ap.add_argument("--at", help="마지막 슬롯 시각 YYYYMMDDHH (미지정 시 레이더 최신 정시)")
    ap.add_argument("--hours", type=int, default=24, help="시각 슬롯 수 (기본 24)")
    ap.add_argument("--no-series", action="store_true",
                    help="부이 원해상도 시계열(buoy_series) 제외")
    ap.add_argument("--tolerance", type=int, default=60, help="시각 허용 오차(분)")
    ap.add_argument("--workers", type=int, default=6, help="동시 호출 수")
    ap.add_argument("--format", choices=["json", "geojson"], default="json")
    ap.add_argument("--no-extra", action="store_true", help="수온·바람 등 부가 필드 제외")
    ap.add_argument("--compact", action="store_true", help="들여쓰기 없이 출력")
    ap.add_argument("-o", "--output", help="저장할 파일 경로 (미지정 시 표준출력)")
    ap.add_argument("-q", "--quiet", action="store_true", help="진행 로그 숨김")
    args = ap.parse_args()

    data = build_dataset(
        date=args.date, at=args.at, hours=args.hours,
        tolerance_min=args.tolerance, workers=args.workers,
        include_extra=not args.no_extra, include_series=not args.no_series,
        verbose=not args.quiet,
    )
    meta = data["meta"]
    if args.format == "geojson":
        data = to_geojson(data)

    text = json.dumps(data, ensure_ascii=False,
                      indent=None if args.compact else 2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        c = meta["counts"]
        print(f"저장: {args.output}  {len(text)/1048576:.1f}MB\n"
              f"  슬롯 {len(meta['slots'])}개 | 통합 {c['total']}건 "
              f"(부이 {c['buoy']} / 레이더 {c['radar']}) | 부이 시계열 {c['buoy_series']}건",
              file=sys.stderr)
    else:
        print(text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
