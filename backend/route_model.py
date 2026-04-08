# [나(본인)] 핵심 데이터 모델 개발용 파일
# OSMnx 보행망 탐색 및 그림자 가중치 부여 알고리즘

import math
import os
from datetime import datetime

import networkx as nx
import osmnx as ox
import geopandas as gpd
from shapely.geometry import LineString, Point

print("그늘 가중치 라우팅 모델 엔진 초기화 중...")

# GeoJSON 파일 경로 (backend/ 기준 상대경로)
_SHADOW_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "shadow_data")


# ── 그림자 GeoJSON 로드 ────────────────────────────────────────────────────────

def load_shadow_geojson(time_str: str) -> gpd.GeoDataFrame:
    """
    time_str (HH:MM) 기준으로 가장 가까운 5분 단위 GeoJSON 파일 로드.
    범위 밖(09:00 이전 / 18:00 이후)이면 빈 GeoDataFrame 반환.
    """
    try:
        hour, minute = map(int, time_str.split(":"))
        # 5분 단위 반올림
        minute = round(minute / 5) * 5
        if minute == 60:
            hour += 1
            minute = 0
        # 범위 클램프: 09:00 ~ 18:00
        total = hour * 60 + minute
        total = max(9 * 60, min(18 * 60, total))
        hour, minute = divmod(total, 60)

        fname = f"shadow_0801_{hour:02d}{minute:02d}.geojson"
        fpath = os.path.join(_SHADOW_DATA_DIR, fname)
        if not os.path.exists(fpath):
            print(f"[shadow] GeoJSON 없음: {fname}")
            return gpd.GeoDataFrame()
        gdf = gpd.read_file(fpath)
        print(f"[shadow] GeoJSON 로드: {fname} ({len(gdf)}개 폴리곤)")
        return gdf
    except Exception as e:
        print(f"[shadow] GeoJSON 로드 실패: {e}")
        return gpd.GeoDataFrame()


# ── 태양 위치 ──────────────────────────────────────────────────────────────────

def get_sun_position(lat: float, lng: float, time_str: str) -> tuple[float, float]:
    """
    주어진 위치·시간의 태양 방위각(°)과 고도각(°) 반환.
    astral 패키지가 없으면 서울 정오 기준 근사값 사용.
    """
    try:
        from astral import LocationInfo
        from astral.sun import azimuth, elevation
        import pytz

        loc = LocationInfo(latitude=lat, longitude=lng)
        tz = pytz.timezone("Asia/Seoul")
        hour, minute = map(int, time_str.split(":"))
        dt = datetime.now(tz).replace(hour=hour, minute=minute, second=0, microsecond=0)
        return azimuth(loc.observer, dt), elevation(loc.observer, dt)
    except Exception:
        return 180.0, 60.0  # fallback: 정남, 고도 60°


# ── 그래프 구축 ────────────────────────────────────────────────────────────────

def build_street_graph(north: float, south: float, east: float, west: float):
    """bbox 영역의 도보 도로망 다운로드 및 엣지 길이 추가"""
    G = ox.graph_from_bbox(
        bbox=(west, south, east, north),  # osmnx 2.x: (left, bottom, right, top)
        network_type="walk",
    )
    G = ox.distance.add_edge_lengths(G)
    return G


def get_buildings(north: float, south: float, east: float, west: float) -> gpd.GeoDataFrame:
    """bbox 영역의 건물 폴리곤 다운로드"""
    try:
        gdf = ox.features_from_bbox(
            bbox=(west, south, east, north),  # osmnx 2.x: (left, bottom, right, top)
            tags={"building": True},
        )
        return gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    except Exception:
        return gpd.GeoDataFrame()


# ── 그늘 가중치 ────────────────────────────────────────────────────────────────

def _shadow_coverage_geojson(geom: LineString, shadow_gdf: gpd.GeoDataFrame) -> float:
    """
    도로 엣지(LineString)가 그림자 폴리곤과 겹치는 비율 반환 (0.0 ~ 1.0).
    사전 계산된 그림자 GeoJSON 폴리곤 기반.
    """
    if shadow_gdf.empty:
        return 0.0

    # 엣지 bbox 기준으로 후보 폴리곤 필터링 (속도 최적화)
    minx, miny, maxx, maxy = geom.bounds
    margin = 0.001
    nearby = shadow_gdf.cx[minx - margin:maxx + margin, miny - margin:maxy + margin]

    if nearby.empty:
        return 0.0

    try:
        intersecting = nearby[nearby.geometry.intersects(geom)]
        if intersecting.empty:
            return 0.0

        # 엣지와 겹치는 그림자 총 길이 비율
        shadow_union = intersecting.geometry.union_all()
        overlap = geom.intersection(shadow_union)
        if geom.length == 0:
            return 0.0
        return min(overlap.length / geom.length, 1.0)
    except Exception:
        return 0.0


def apply_shadow_weights(G, shadow_gdf: gpd.GeoDataFrame):
    """각 도로 엣지에 shadow_weight 속성 추가 (그늘 많을수록 낮은 값)"""
    for u, v, k, data in G.edges(data=True, keys=True):
        length = data.get("length", 1.0)

        geom = data.get("geometry")
        if geom is None:
            u_node, v_node = G.nodes[u], G.nodes[v]
            geom = LineString([(u_node["x"], u_node["y"]), (v_node["x"], v_node["y"])])

        shadow = _shadow_coverage_geojson(geom, shadow_gdf)
        # 그늘이 많을수록 가중치 낮음 → 다익스트라가 선호
        G[u][v][k]["shadow_weight"] = length * (1.0 - shadow * 0.8)

    return G


# ── 메인 함수 ──────────────────────────────────────────────────────────────────

def calculate_optimal_shadow_route(kakao_coords: list[dict], time_str: str) -> list[dict]:
    """
    카카오 경로 좌표를 받아 그늘 가중치 기반 최적 경로를 반환.
    계산 실패 시 원본 카카오 경로를 그대로 반환 (fallback).
    """
    if not kakao_coords:
        return kakao_coords

    start = kakao_coords[0]
    end = kakao_coords[-1]

    lats = [c["lat"] for c in kakao_coords]
    lngs = [c["lng"] for c in kakao_coords]
    margin = 0.003  # ~330 m 여유
    north, south = max(lats) + margin, min(lats) - margin
    east, west = max(lngs) + margin, min(lngs) - margin
    center_lat = (north + south) / 2
    center_lng = (east + west) / 2

    try:
        shadow_gdf = load_shadow_geojson(time_str)

        G = build_street_graph(north, south, east, west)
        print(f"[shadow] 도로 엣지 {G.number_of_edges()}개 로드")

        G = apply_shadow_weights(G, shadow_gdf)

        start_node = ox.distance.nearest_nodes(G, X=start["lng"], Y=start["lat"])
        end_node = ox.distance.nearest_nodes(G, X=end["lng"], Y=end["lat"])

        path_nodes = nx.shortest_path(G, start_node, end_node, weight="shadow_weight")

        result = [
            {"lat": G.nodes[n]["y"], "lng": G.nodes[n]["x"]}
            for n in path_nodes
        ]
        print(f"[shadow] 최적 경로 노드 {len(result)}개 반환")
        return result

    except Exception as e:
        print(f"[shadow] 경로 계산 실패 → 카카오 경로 반환: {e}")
        return kakao_coords
