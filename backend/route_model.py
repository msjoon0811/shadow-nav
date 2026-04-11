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


# ── 이동 시간 가중치 ───────────────────────────────────────────────────────────

def assign_basic_time_weights(graph, speed_kmh=4.0):
    """
    모든 도로(Edge)의 길이를 바탕으로 사람이 걷는 데 걸리는 기본 시간(분)을 계산해 부여.
    (자전거인 경우 speed_kmh를 15로 주면 됩니다)
    """
    meters_per_minute = speed_kmh * 1000 / 60
    for u, v, key, data in graph.edges(keys=True, data=True):
        if 'length' in data:
            data['travel_time'] = data['length'] / meters_per_minute
        else:
            data['travel_time'] = 0.0
    return graph


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


_FOOTWAY_TAGS = {"footway", "pedestrian", "path", "steps", "living_street"}
_FOOTWAY_BONUS = 0.7  # 보도/인도 엣지는 가중치 30% 감소 → A*가 우선 선택


def apply_shadow_weights(G, shadow_gdf: gpd.GeoDataFrame):
    """각 도로 엣지에 shadow_weight 속성 추가 (그늘 많을수록, 보도일수록 낮은 값)"""
    for u, v, k, data in G.edges(data=True, keys=True):
        length = data.get("length", 1.0)

        geom = data.get("geometry")
        if geom is None:
            u_node, v_node = G.nodes[u], G.nodes[v]
            geom = LineString([(u_node["x"], u_node["y"]), (v_node["x"], v_node["y"])])

        shadow = _shadow_coverage_geojson(geom, shadow_gdf)
        travel_time = data.get("travel_time", length / (4.0 * 1000 / 60))

        # 보도/인도 태그 확인
        highway = data.get("highway", "")
        if isinstance(highway, list):
            highway = highway[0] if highway else ""
        is_footway = highway in _FOOTWAY_TAGS

        base = travel_time * (1.0 - shadow * 0.3)
        G[u][v][k]["shadow_weight"] = base * (_FOOTWAY_BONUS if is_footway else 1.0)

    return G


# ── OSM 횡단보도 노드 추출 ────────────────────────────────────────────────────

def extract_osm_crosswalk_nodes(G) -> list[dict]:
    """
    OSM 보행 그래프에서 highway=crossing 노드 추출.
    서울 API 데이터 없이도 횡단보도 위치 파악 가능.
    """
    nodes = []
    for _, data in G.nodes(data=True):
        hw = data.get("highway", "")
        if isinstance(hw, list):
            hw = hw[0] if hw else ""
        if hw == "crossing":
            nodes.append({"lat": data["y"], "lng": data["x"]})
    return nodes


# ── 횡단보도 제약 ──────────────────────────────────────────────────────────────

_CROSSING_RADIUS_DEG = 0.0005   # ~55m
# 횡단보도 강제 적용 대상: 큰 도로만 (골목/이면도로는 제외)
_MAJOR_ROAD_TAGS = {
    "primary", "secondary", "tertiary",
    "primary_link", "secondary_link", "tertiary_link",
}
_FOOTWAY_TAGS = {"footway", "pedestrian", "path", "steps", "crossing"}
_NO_CROSSING_PENALTY = 60.0     # 횡단보도 없는 도로 횡단 패널티 (분)


def apply_crosswalk_constraints(G, crosswalk_nodes: list[dict]):
    """
    보행 엣지가 차도를 실제로 기하학적으로 교차하는지 shapely로 검사.
    교차 지점 근처에 횡단보도 없으면 높은 패널티 부여.
    """
    from shapely.ops import unary_union
    from shapely.strtree import STRtree

    # 1. 도로 엣지 geometry 수집 + STR 공간 인덱스
    road_geoms = []
    for u, v, k, data in G.edges(data=True, keys=True):
        hw = data.get("highway", "")
        if isinstance(hw, list): hw = hw[0] if hw else ""
        if hw not in _MAJOR_ROAD_TAGS:
            continue
        geom = data.get("geometry")
        if geom is None:
            un, vn = G.nodes[u], G.nodes[v]
            geom = LineString([(un["x"], un["y"]), (vn["x"], vn["y"])])
        road_geoms.append(geom)

    if not road_geoms:
        return G

    road_union = unary_union(road_geoms)  # 버퍼 없이 선 그대로 유지
    road_tree  = STRtree(road_geoms)

    # 2. 횡단보도 포인트 STR 인덱스
    cw_points = [Point(c["lng"], c["lat"]) for c in crosswalk_nodes]
    cw_tree   = STRtree(cw_points) if cw_points else None

    penalized = 0
    for u, v, k, data in G.edges(data=True, keys=True):
        hw = data.get("highway", "")
        if isinstance(hw, list): hw = hw[0] if hw else ""
        # 도로 자체 엣지 스킵
        if hw in _MAJOR_ROAD_TAGS:
            continue
        # 이미 crossing으로 명시된 엣지는 허용
        if data.get("footway") == "crossing" or hw == "crossing":
            continue

        geom = data.get("geometry")
        if geom is None:
            un, vn = G.nodes[u], G.nodes[v]
            geom = LineString([(un["x"], un["y"]), (vn["x"], vn["y"])])

        # 도로를 실제로 가로지르는지 확인 (crosses = 완전히 통과, 평행/접선은 제외)
        if not geom.crosses(road_union):
            continue

        # 교차 지점 근처에 횡단보도 있는지 확인
        near_cw = False
        if cw_tree:
            intersection = geom.intersection(road_union)
            nearby = cw_tree.query(intersection.buffer(_CROSSING_RADIUS_DEG))
            near_cw = len(nearby) > 0
        else:
            near_cw = True  # 횡단보도 데이터 없으면 패널티 미적용

        if not near_cw:
            G[u][v][k]["shadow_weight"] = (
                G[u][v][k].get("shadow_weight", data.get("length", 1.0)) + _NO_CROSSING_PENALTY
            )
            penalized += 1

    print(f"[crosswalk] 비횡단보도 도로 횡단 엣지 {penalized}개 패널티 적용")
    return G


# ── 신호등 패널티 ──────────────────────────────────────────────────────────────

_SIGNAL_RADIUS_DEG = 0.0002   # ~22m 이내 교차로에만 패널티 적용
_SIGNAL_PENALTY_PER_SEC = 0.05  # 빨간불 1초 = 보행 50m 패널티 환산 (분 단위 가중치)


def apply_signal_penalties(G, signal_data: list[dict]):
    """
    신호 대기시간이 긴 교차로 인근 엣지에 추가 패널티 부여.
    signal_data: [{"lng", "lat", "red_remaining_sec"}, ...]
    """
    if not signal_data:
        return G

    for u, v, k, data in G.edges(data=True, keys=True):
        u_node = G.nodes[u]
        v_node = G.nodes[v]
        mid_x = (u_node["x"] + v_node["x"]) / 2
        mid_y = (u_node["y"] + v_node["y"]) / 2

        max_penalty = 0.0
        for sig in signal_data:
            if (abs(mid_x - sig["lng"]) < _SIGNAL_RADIUS_DEG and
                    abs(mid_y - sig["lat"]) < _SIGNAL_RADIUS_DEG):
                penalty = sig.get("red_remaining_sec", 0) * _SIGNAL_PENALTY_PER_SEC
                max_penalty = max(max_penalty, penalty)

        if max_penalty > 0:
            G[u][v][k]["shadow_weight"] = G[u][v][k].get("shadow_weight", data.get("length", 1.0)) + max_penalty

    return G


# ── 메인 함수 ──────────────────────────────────────────────────────────────────

def calculate_optimal_shadow_route(
    kakao_coords: list[dict],
    time_str: str,
    signal_data: list[dict] | None = None,
    crosswalk_nodes: list[dict] | None = None,
    mode: str = "walk",
) -> list[dict]:
    """
    카카오 경로 좌표를 받아 그늘 + 신호 패널티 기반 최적 경로를 반환.
    계산 실패 시 원본 카카오 경로를 그대로 반환 (fallback).

    Args:
        kakao_coords: 카카오 API에서 받은 좌표 리스트
        time_str:     그림자 계산 시간 (HH:MM)
        signal_data:  신호등 잔여시간 리스트 (없으면 패널티 미적용)
        mode:         "walk" (걷기) / "bike" (걷기+따릉이, 속도 15 km/h)
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

    speed_kmh = 15.0 if mode == "bike" else 4.0

    try:
        shadow_gdf = load_shadow_geojson(time_str)

        G = build_street_graph(north, south, east, west)
        print(f"[shadow] 도로 엣지 {G.number_of_edges()}개 로드 (speed={speed_kmh} km/h)")

        G = assign_basic_time_weights(G, speed_kmh=speed_kmh)
        G = apply_shadow_weights(G, shadow_gdf)

        # OSM 그래프에서 횡단보도 노드 추출 후 서울 API 데이터와 병합
        osm_cw = extract_osm_crosswalk_nodes(G)
        merged_cw = list(crosswalk_nodes or []) + osm_cw
        print(f"[shadow] 횡단보도 노드: 서울API {len(crosswalk_nodes or [])}개 + OSM {len(osm_cw)}개 = 총 {len(merged_cw)}개")
        G = apply_crosswalk_constraints(G, merged_cw)

        if signal_data:
            G = apply_signal_penalties(G, signal_data)
            print(f"[shadow] 신호등 패널티 {len(signal_data)}개 적용")

        start_node = ox.distance.nearest_nodes(G, X=start["lng"], Y=start["lat"])
        end_node   = ox.distance.nearest_nodes(G, X=end["lng"],   Y=end["lat"])

        # A* 휴리스틱: 목적지까지의 직선 거리 (위경도 유클리드 근사)
        end_x = G.nodes[end_node]["x"]
        end_y = G.nodes[end_node]["y"]

        def heuristic(u, _v):
            dx = G.nodes[u]["x"] - end_x
            dy = G.nodes[u]["y"] - end_y
            return math.hypot(dx, dy) * 111_000  # 위도 1° ≈ 111km → 미터 환산

        path_nodes = nx.astar_path(G, start_node, end_node, heuristic=heuristic, weight="shadow_weight")

        result = [
            {"lat": G.nodes[n]["y"], "lng": G.nodes[n]["x"]}
            for n in path_nodes
        ]
        print(f"[shadow] 최적 경로 노드 {len(result)}개 반환")
        return result

    except Exception as e:
        print(f"[shadow] 경로 계산 실패 → 카카오 경로 반환: {e}")
        return kakao_coords
