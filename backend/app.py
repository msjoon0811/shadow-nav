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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발 중엔 전체 허용, 배포 시 프론트 도메인으로 교체
    allow_methods=["*"],
    allow_headers=["*"],
)

KAKAO_REST_API_KEY   = os.environ.get("KAKAO_REST_API_KEY", "")
SIGNAL_API_KEY       = os.environ.get("SIGNAL_API_KEY", "")       # 공공데이터포털 신호등 API 키
DDAREUNGI_API_KEY    = os.environ.get("DDAREUNGI_API_KEY", "")    # 서울 열린데이터 따릉이 API 키

KAKAO_DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/directions"
# 경찰청 교통신호 정보 서비스 (공공데이터포털)
SIGNAL_API_URL       = "https://apis.data.go.kr/B552061/trafficSignal/getTrafficSignalList"
# 서울시 따릉이 실시간 대여소 정보 (서울 열린데이터 광장)
DDAREUNGI_API_URL    = "http://openapi.seoul.go.kr:8088/{key}/json/bikeList/{start}/{end}/"


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


# ── 신호등 실시간 잔여시간 API ──────────────────────────────────────────────────

async def fetch_traffic_signals(coords: list[dict]) -> list[dict]:
    """
    경로 좌표 bbox 내 교차로 신호등 잔여시간 조회.
    API 키 미설정 시 빈 리스트 반환 (라우팅은 계속 동작).

    반환 형태:
      [{"lng": float, "lat": float, "red_remaining_sec": int}, ...]
    """
    if not SIGNAL_API_KEY or not coords:
        return []

    lats = [c["lat"] for c in coords]
    lngs = [c["lng"] for c in coords]
    margin = 0.002  # ~220m

    params = {
        "serviceKey": SIGNAL_API_KEY,
        "pageNo":     1,
        "numOfRows":  50,
        "minX":       min(lngs) - margin,
        "maxX":       max(lngs) + margin,
        "minY":       min(lats) - margin,
        "maxY":       max(lats) + margin,
        "type":       "json",
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(SIGNAL_API_URL, params=params)

        if res.status_code != 200:
            print(f"[signal] API 오류 {res.status_code}: {res.text[:200]}")
            return []

        data = res.json()
        items = (
            data.get("response", {})
                .get("body", {})
                .get("items", {})
                .get("item", [])
        )
        if isinstance(items, dict):   # 단건 응답이면 dict로 올 수 있음
            items = [items]

        result = []
        for item in items:
            try:
                result.append({
                    "lng":               float(item["x"]),
                    "lat":               float(item["y"]),
                    "red_remaining_sec": int(item.get("pedRedRemainTime", 0)),
                })
            except (KeyError, ValueError):
                continue

        print(f"[signal] 신호등 {len(result)}개 수신")
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

    url = DDAREUNGI_API_URL.format(key=DDAREUNGI_API_KEY, start=1, end=200)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(url)

        if res.status_code != 200:
            print(f"[ddareungi] API 오류 {res.status_code}")
            return []

        data  = res.json()
        items = data.get("rentBikeStatus", {}).get("row", [])

        result = []
        for item in items:
            try:
                s_lat = float(item["stationLatitude"])
                s_lng = float(item["stationLongitude"])

                # 간이 거리 필터 (~1 km)
                if abs(s_lat - center_lat) > 0.009 or abs(s_lng - center_lng) > 0.012:
                    continue

                result.append({
                    "name":      item.get("stationName", ""),
                    "lat":       s_lat,
                    "lng":       s_lng,
                    "available": int(item.get("parkingBikeTotCnt", 0)),
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

    # 2. 공공 API 병렬 호출
    async def _no_ddareungi():
        return []

    signal_task    = fetch_traffic_signals(kakao_coords)
    ddareungi_task = (
        fetch_ddareungi_stations(req.start_lat, req.start_lng)
        if req.mode == "bike" else _no_ddareungi()
    )
    signal_data, ddareungi_data = await asyncio.gather(signal_task, ddareungi_task)

    # 3. 그늘 + 신호 패널티 최적 경로 계산
    final_coords = calculate_optimal_shadow_route(
        kakao_coords=kakao_coords,
        time_str=req.time_str,
        signal_data=signal_data,
        mode=req.mode,
    )

    return {
        "route":             final_coords,
        "ddareungi_stations": ddareungi_data,
    }
