# [나(본인)] 핵심 데이터 모델 개발용 파일
# OSMnx 보행망 탐색 및 그림자 가중치 부여 알고리즘

import osmnx as ox
import networkx as nx
import geopandas as gpd

print("그늘 가중치 라우팅 모델 엔진 초기화 중...")

def build_street_graph():
    """
    신논현역 반경 500m 도로망(그래프)을 다운로드하는 함수
    """
    # TODO: OSMnx 라이브러리 활용
    pass

def apply_shadow_weights(graph, shadow_geojson_path):
    """
    도로와 그림자 지도의 교집합을 구해, 도로(Edge)에 쾌적성 점수를 부여하는 함수
    """
    # TODO: Shapely와 GPD를 이용한 공간 겹침 연산
    pass

def calculate_optimal_shadow_route(start_coords, end_coords, traffic_data):
    """
    가중치가 부여된 맵에서 A->B 최적 경로를 다익스트라(Dijkstra)로 뽑는 메인 함수
    """
    # TODO: nx.shortest_path 활용 (weight='shadow_comfort_score')
    
    # 테스트용 가짜 응답 (강남역 방향 직선)
    dummy_route = [
        {"lat": 37.5045, "lng": 127.0248},
        {"lat": 37.4980, "lng": 127.0276}
    ]
    return dummy_route
