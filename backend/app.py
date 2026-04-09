from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Literal
import httpx
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from route_model import calculate_optimal_shadow_route

app = FastAPI(title="Shadow-Nav API")

_SHADOW_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "shadow_data")

KAKAO_REST_API_KEY   = os.environ.get("KAKAO_REST_API_KEY", "")
SIGNAL_API_KEY       = os.environ.get("SIGNAL_API_KEY", "")
DDAREUNGI_API_KEY    = os.environ.get("DDAREUNGI_API_KEY", "")
SEOUL_API_KEY        = os.environ.get("SEOUL_API_KEY", "")

SEOUL_CRSNG_URL      = "http://openapi.seoul.go.kr:8088/{key}/json/tbTraficCrsng/{start}/{end}/"
KAKAO_DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/directions"
KAKAO_LOCAL_URL      = "https://dapi.kakao.com/v2/local/search/keyword.json"
SIGNAL_RT_BASE_URL   = "https://apis.data.go.kr/B551982/rti"
DDAREUNGI_API_URL    = "https://apis.data.go.kr/B551982/pbdo_v2/inf_101_00010002_v2"

# 교차로 좌표 캐시 {crsrdId: {"lat": float, "lng": float, "name": str}}
_crsrd_coord_cache: dict[str, dict] = {}

# 서울 횡단보도 노드 캐시 [{"lat": float, "lng": float}]
_crosswalk_nodes: list[dict] = []


async def _load_all_crosswalk_nodes() -> list[dict]:
    """서울 횡단보도 전체 데이터를 병렬로 로드해 캐싱."""
    global _crosswalk_nodes
    if not SEOUL_API_KEY:
        return []
    PAGE_SIZE = 1000
    try:
        # 1페이지로 총 개수 파악
        async with httpx.AsyncClient(timeout=15.0) as client:
            url = SEOUL_CRSNG_URL.format(key=SEOUL_API_KEY, start=1, end=PAGE_SIZE)
            r = await client.get(url)
            body = r.json().get("tbTraficCrsng", {})
            total = int(body.get("list_total_count", 0))
            first_nodes = _parse_crsng_nodes(body.get("row", []))

        if total == 0:
            return []

        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        print(f"[crosswalk] 총 {total}개, {total_pages}페이지 병렬 로드 시작...")

        async def _fetch_page(p: int) -> list[dict]:
            s = (p - 1) * PAGE_SIZE + 1
            e = p * PAGE_SIZE
            url = SEOUL_CRSNG_URL.format(key=SEOUL_API_KEY, start=s, end=e)
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.get(url)
                rows = r.json().get("tbTraficCrsng", {}).get("row", [])
                return _parse_crsng_nodes(rows)

        tasks = [_fetch_page(p) for p in range(2, total_pages + 1)]
        pages = await asyncio.gather(*tasks)

        all_nodes = first_nodes + [n for page in pages for n in page]
        _crosswalk_nodes = all_nodes
        print(f"[crosswalk] 캐시 완료: {len(_crosswalk_nodes)}개 노드")
        return _crosswalk_nodes
    except Exception as e:
        print(f"[crosswalk] 로드 실패: {e!r}")
        return []


async def fetch_crosswalk_nodes_for_bbox(
    min_lat: float, max_lat: float, min_lng: float, max_lng: float
) -> list[dict]:
    """캐시된 횡단보도 노드에서 bbox 필터링. 캐시 없으면 전체 로드."""
    global _crosswalk_nodes
    if not _crosswalk_nodes:
        await _load_all_crosswalk_nodes()
    nearby = [
        n for n in _crosswalk_nodes
        if min_lat <= n["lat"] <= max_lat and min_lng <= n["lng"] <= max_lng
    ]
    print(f"[crosswalk] bbox 내 횡단보도 {len(nearby)}개")
    return nearby


def _parse_crsng_nodes(rows: list) -> list[dict]:
    nodes = []
    for r in rows:
        if r.get("NODE_TYPE") != "NODE":
            continue
        wkt = r.get("NODE_WKT", "")
        if not wkt.startswith("POINT("):
            continue
        try:
            coords = wkt[6:-1].split()
            nodes.append({"lng": float(coords[0]), "lat": float(coords[1])})
        except (ValueError, IndexError):
            continue
    return nodes

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발 중엔 전체 허용, 배포 시 프론트 도메인으로 교체
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(_load_all_crosswalk_nodes())



class RouteRequest(BaseModel):
    start_lat: float
    start_lng: float
    end_lat:   float
    end_lng:   float
    time_str:  str                    = "12:00"  # 그림자 계산용 시간 (HH:MM)
    mode:      Literal["walk", "bike"] = "walk"  # "walk": 걷기 / "bike": 걷기+따릉이


# ── 카카오 모빌리티 경로 API ────────────────────────────────────────────────────

async def fetch_kakao_route(start_lng, start_lat, end_lng, end_lat) -> list[dict]:
    """카카오 모빌리티 도보/자전거 경로 API 호출"""
    if not KAKAO_REST_API_KEY:
        raise HTTPException(status_code=500, detail="KAKAO_REST_API_KEY가 설정되지 않았습니다.")

    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}
    params = {
        "origin":      f"{start_lng},{start_lat}",
        "destination": f"{end_lng},{end_lat}",
        "priority":    "RECOMMEND",
    }

    async with httpx.AsyncClient() as client:
        res = await client.get(KAKAO_DIRECTIONS_URL, headers=headers, params=params)

    if res.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Kakao API 오류: {res.text}")

    data = res.json()

    try:
        sections = data["routes"][0]["sections"]
        coords = []
        for section in sections:
            for road in section["roads"]:
                verts = road["vertexes"]
                for i in range(0, len(verts), 2):
                    coords.append({"lat": verts[i + 1], "lng": verts[i]})
        return coords
    except (KeyError, IndexError) as e:
        raise HTTPException(status_code=502, detail=f"Kakao 응답 파싱 실패: {e}")


# ── 신호등 API (교차로 지오코딩 + 실시간 잔여시간) ────────────────────────────

async def _geocode_intersection(client: httpx.AsyncClient, name: str) -> tuple[float, float] | None:
    """카카오 Local API로 교차로명 → (lat, lng) 변환. 캐싱 없이 호출."""
    try:
        res = await client.get(
            KAKAO_LOCAL_URL,
            headers={"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"},
            params={"query": name, "size": 1},
        )
        docs = res.json().get("documents", [])
        if docs:
            return float(docs[0]["y"]), float(docs[0]["x"])
    except Exception:
        pass
    return None


async def fetch_traffic_signals(coords: list[dict]) -> list[dict]:
    """
    tl_drct_info의 crsrdId로 crsrd_map_info에서 위치 역조회.
    tl_drct_info → 신호 잔여시간 추출 → crsrd_map_info에서 좌표 매칭 → 지오코딩으로 경도 보완.
    API 키 미설정 시 빈 리스트 반환.

    반환 형태:
      [{"lat": float, "lng": float, "red_remaining_sec": int}, ...]
    """
    if not SIGNAL_API_KEY or not KAKAO_REST_API_KEY or not coords:
        return []

    lats = [c["lat"] for c in coords]
    lngs = [c["lng"] for c in coords]
    margin = 0.003
    min_lat = min(lats) - margin
    max_lat = max(lats) + margin
    min_lng = min(lngs) - margin
    max_lng = max(lngs) + margin

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 1. 두 API 병렬 호출
            crsrd_res, rt_res = await asyncio.gather(
                client.get(f"{SIGNAL_RT_BASE_URL}/crsrd_map_info", params={
                    "serviceKey": SIGNAL_API_KEY, "pageNo": 1, "numOfRows": 1000, "type": "json",
                }),
                client.get(f"{SIGNAL_RT_BASE_URL}/tl_drct_info", params={
                    "serviceKey": SIGNAL_API_KEY, "pageNo": 1, "numOfRows": 1000, "type": "json",
                }),
            )

            crsrd_items = crsrd_res.json().get("body", {}).get("items", {}).get("item", [])
            if isinstance(crsrd_items, dict):
                crsrd_items = [crsrd_items]

            rt_items = rt_res.json().get("body", {}).get("items", {}).get("item", [])
            if isinstance(rt_items, dict):
                rt_items = [rt_items]

            # 2. crsrd_map_info → {crsrdId: (lat, name)} 맵 구성
            crsrd_by_id: dict[str, tuple[float, str]] = {}
            for c in crsrd_items:
                try:
                    lat = float(c["mapCtptIntLat"])
                    cid = str(c["crsrdId"])
                    name = c.get("crsrdNm", "")
                    crsrd_by_id[cid] = (lat, name)
                except (KeyError, ValueError, TypeError):
                    continue

            # 3. tl_drct_info → 보행자 신호 잔여시간 추출 (>0인 것만)
            rt_signals: list[tuple[str, int]] = []  # [(crsrdId, sec), ...]
            for rt in rt_items:
                cid = str(rt.get("crsrdId", ""))
                for prefix in ["nt", "et", "st", "wt", "ne", "se", "sw", "nw"]:
                    val = rt.get(f"{prefix}PdsgRmndCs", "")
                    if val:
                        try:
                            sec = int(val)
                            if sec > 0:
                                rt_signals.append((cid, sec))
                                break
                        except ValueError:
                            continue

            print(f"[signal] 보행자 신호 있는 교차로: {len(rt_signals)}개")

            # 4. rt_signals의 crsrdId로 crsrd_map_info에서 위치 조회
            need_geocode = []
            for cid, sec in rt_signals:
                if cid in _crsrd_coord_cache:
                    coord = _crsrd_coord_cache[cid]
                    if min_lat <= coord["lat"] <= max_lat and min_lng <= coord["lng"] <= max_lng:
                        need_geocode.append((cid, sec, coord["lat"], coord["lng"]))
                elif cid in crsrd_by_id:
                    lat, name = crsrd_by_id[cid]
                    if min_lat <= lat <= max_lat and name:
                        need_geocode.append((cid, sec, lat, None, name))  # 지오코딩 필요

            # 5. 지오코딩 (경도 없는 것만, 최대 30개)
            to_geocode = [(cid, sec, lat, name) for cid, sec, lat, _, name in
                          [x for x in need_geocode if len(x) == 5]][:30]
            geocode_tasks = [_geocode_intersection(client, name) for _, _, _, name in to_geocode]
            geocode_results = await asyncio.gather(*geocode_tasks)

            for (cid, sec, lat, name), coord in zip(to_geocode, geocode_results):
                if coord:
                    g_lat, g_lng = coord
                    if abs(g_lat - lat) > 0.01:
                        continue
                    _crsrd_coord_cache[cid] = {"lat": g_lat, "lng": g_lng, "name": name}
                    if min_lng <= g_lng <= max_lng:
                        need_geocode.append((cid, sec, g_lat, g_lng))

            # 6. 최종 결과 조합 (좌표 확정된 것만)
            result = []
            for item in need_geocode:
                if len(item) == 4:
                    cid, sec, lat, lng = item
                    if lng is not None:
                        result.append({"lat": lat, "lng": lng, "red_remaining_sec": sec})

        print(f"[signal] 교차로 {len(result)}개 신호 수신")
        return result

    except Exception as e:
        print(f"[signal] 요청 실패 (라우팅은 계속): {e}")
        return []


# ── 따릉이 실시간 대여소 API ────────────────────────────────────────────────────

async def fetch_ddareungi_stations(center_lat: float, center_lng: float) -> list[dict]:
    """
    따릉이 대여소 전체 목록 조회 후 출발지 반경 1km 이내만 필터링.
    API 키 미설정 시 빈 리스트 반환.

    반환 형태:
      [{"name": str, "lng": float, "lat": float, "available": int}, ...]
    """
    if not DDAREUNGI_API_KEY:
        return []

    PAGE_SIZE = 1000

    async def _fetch_page(client: httpx.AsyncClient, page: int) -> list:
        params = {
            "serviceKey": DDAREUNGI_API_KEY,
            "pageNo":     page,
            "numOfRows":  PAGE_SIZE,
            "type":       "json",
        }
        res = await client.get(DDAREUNGI_API_URL, params=params)
        if res.status_code != 200:
            return []
        return res.json().get("body", {}).get("item", [])

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # 1페이지로 전체 수 확인
            first_params = {
                "serviceKey": DDAREUNGI_API_KEY,
                "pageNo":     1,
                "numOfRows":  PAGE_SIZE,
                "type":       "json",
            }
            res = await client.get(DDAREUNGI_API_URL, params=first_params)
            if res.status_code != 200:
                print(f"[ddareungi] API 오류 {res.status_code}")
                return []
            first_data = res.json()
            total = first_data.get("body", {}).get("totalCount", 0)
            first_items = first_data.get("body", {}).get("item", [])

            # 나머지 페이지 병렬 호출
            total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
            if total_pages > 1:
                tasks = [_fetch_page(client, p) for p in range(2, total_pages + 1)]
                rest = await asyncio.gather(*tasks)
                items = first_items + [i for page in rest for i in page]
            else:
                items = first_items

        result = []
        for item in items:
            try:
                s_lat = float(item["lat"])
                s_lng = float(item["lot"])

                # 간이 거리 필터 (~1 km)
                if abs(s_lat - center_lat) > 0.009 or abs(s_lng - center_lng) > 0.012:
                    continue

                result.append({
                    "name":      item.get("rntstnNm", ""),
                    "lat":       s_lat,
                    "lng":       s_lng,
                    "available": int(item.get("bcyclTpkctNocs", 0)),
                })
            except (KeyError, ValueError):
                continue

        print(f"[ddareungi] 반경 내 따릉이 대여소 {len(result)}개")
        return result

    except Exception as e:
        print(f"[ddareungi] 요청 실패 (라우팅은 계속): {e}")
        return []


# ── 헬스체크 ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/shadow/{time_str}")
def get_shadow_geojson(time_str: str):
    """
    시간(HH:MM) 기준 그림자 GeoJSON 반환.
    5분 단위로 반올림, 범위 09:00~18:00 클램프.
    """
    try:
        hour, minute = map(int, time_str.replace("-", ":").split(":"))
        minute = round(minute / 5) * 5
        if minute == 60:
            hour += 1
            minute = 0
        total = max(9 * 60, min(18 * 60, hour * 60 + minute))
        hour, minute = divmod(total, 60)
    except ValueError:
        raise HTTPException(status_code=400, detail="시간 형식은 HH:MM 이어야 합니다.")

    fname = f"shadow_0801_{hour:02d}{minute:02d}.geojson"
    fpath = os.path.join(_SHADOW_DATA_DIR, fname)

    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail=f"그림자 데이터 없음: {fname}")

    return FileResponse(fpath, media_type="application/geo+json")


@app.get("/api/geocode")
async def geocode(query: str = Query(..., description="장소명")):
    """Kakao Local API 프록시 — 장소명 → 위경도 변환"""
    if not KAKAO_REST_API_KEY:
        raise HTTPException(status_code=500, detail="KAKAO_REST_API_KEY가 설정되지 않았습니다.")

    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}
    params  = {"query": query, "size": 1}

    async with httpx.AsyncClient() as client:
        res = await client.get(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            headers=headers, params=params,
        )

    if res.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Kakao 지오코딩 오류: {res.text}")

    docs = res.json().get("documents", [])
    if not docs:
        raise HTTPException(status_code=404, detail=f"'{query}' 검색 결과 없음")

    doc = docs[0]
    return {
        "name": doc.get("place_name", query),
        "lat":  float(doc["y"]),
        "lng":  float(doc["x"]),
    }


# ── 메인 길찾기 엔드포인트 ──────────────────────────────────────────────────────

@app.post("/api/route")
async def get_route(req: RouteRequest):
    """
    프론트에서 A→B 길찾기 요청.
    1. 카카오 API로 기본 경로 획득
    2. 신호등 & 따릉이 API 비동기 병렬 호출
    3. route_model에 모든 정보 넘겨 그늘 + 신호 패널티 최적화
    4. 최종 경로 + 따릉이 대여소 반환
    """
    # 1. 카카오 경로 (직렬 — 이후 작업의 bbox 기준점)
    kakao_coords = await fetch_kakao_route(
        req.start_lng, req.start_lat, req.end_lng, req.end_lat
    )

    # 2. 공공 API 병렬 호출 (신호등 + 따릉이 + 횡단보도)
    async def _no_ddareungi():
        return []

    lats = [c["lat"] for c in kakao_coords]
    lngs = [c["lng"] for c in kakao_coords]
    margin = 0.003
    min_lat, max_lat = min(lats) - margin, max(lats) + margin
    min_lng, max_lng = min(lngs) - margin, max(lngs) + margin

    signal_task    = fetch_traffic_signals(kakao_coords)
    ddareungi_task = (
        fetch_ddareungi_stations(req.start_lat, req.start_lng)
        if req.mode == "bike" else _no_ddareungi()
    )
    crosswalk_task = fetch_crosswalk_nodes_for_bbox(min_lat, max_lat, min_lng, max_lng)

    signal_data, ddareungi_data, nearby_cw = await asyncio.gather(
        signal_task, ddareungi_task, crosswalk_task
    )

    # 4. 그늘 + 횡단보도 제약 + 신호 패널티 최적 경로 계산
    final_coords = calculate_optimal_shadow_route(
        kakao_coords=kakao_coords,
        time_str=req.time_str,
        signal_data=signal_data,
        crosswalk_nodes=nearby_cw,
        mode=req.mode,
    )

    # 실시간 신호 데이터를 가장 가까운 횡단보도 노드 위치로 스냅
    def _snap_to_nearest_cw(sig: dict, cw_nodes: list[dict]) -> dict:
        if not cw_nodes:
            return sig
        best = min(cw_nodes, key=lambda n: (n["lat"] - sig["lat"]) ** 2 + (n["lng"] - sig["lng"]) ** 2)
        dist = ((best["lat"] - sig["lat"]) ** 2 + (best["lng"] - sig["lng"]) ** 2) ** 0.5
        if dist < 0.002:  # ~200m 이내면 스냅
            return {**sig, "lat": best["lat"], "lng": best["lng"]}
        return sig

    snapped_signals = [_snap_to_nearest_cw(s, nearby_cw) for s in signal_data]

    # 횡단보도 노드를 추가 (실시간 신호 없는 위치는 red_remaining_sec=0)
    merged_signals = list(snapped_signals)
    for n in nearby_cw:
        already = any(
            abs(s["lat"] - n["lat"]) < 0.0003 and abs(s["lng"] - n["lng"]) < 0.0003
            for s in merged_signals
        )
        if not already:
            merged_signals.append({"lat": n["lat"], "lng": n["lng"], "red_remaining_sec": 0})

    return {
        "route":              final_coords,
        "ddareungi_stations": ddareungi_data,
        "signal_data":        merged_signals,
    }
