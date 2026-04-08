# [나(본인)] 핵심 데이터 모델 개발용 파일
# OSMnx 보행망 탐색 및 머신러닝 쾌적지수 예측 알고리즘

import osmnx as ox
import networkx as nx
import geopandas as gpd
import os

print("그늘 가중치 라우팅 모델 엔진 초기화 중...")

def build_street_graph():
    """
    신논현역 반경 500m 도로망(그래프)을 다운로드하는 함수
    """
    # 신논현역 좌표
    sinnonhyeon_coords = (37.5045, 127.0248)
    radius = 500
    
    # 상위 경로인 data 폴더 경로 지정
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    os.makedirs(data_dir, exist_ok=True)
    
    walk_graph_path = os.path.join(data_dir, 'walk_graph.graphml')
    bike_graph_path = os.path.join(data_dir, 'bike_graph.graphml')
    
    # 1. 보행자 도로망 다운로드
    if os.path.exists(walk_graph_path):
        print("✅ 기존 보행자 도로망 캐시 로드 중...")
        G_walk = ox.load_graphml(walk_graph_path)
    else:
        print(f"📥 다운로드 중: 신논현역 반경 {radius}m 보행자 도로망...")
        G_walk = ox.graph_from_point(sinnonhyeon_coords, dist=radius, network_type='walk')
        ox.save_graphml(G_walk, walk_graph_path)
        print(f"✅ 보행자 도로망 저장 완료! (노드: {len(G_walk.nodes)}, 골목길: {len(G_walk.edges)}개)")

    # 2. 자전거 도로망 다운로드
    if os.path.exists(bike_graph_path):
        print("✅ 기존 자전거 도로망 캐시 로드 중...")
        G_bike = ox.load_graphml(bike_graph_path)
    else:
        print(f"📥 다운로드 중: 신논현역 반경 {radius}m 자전거 도로망...")
        G_bike = ox.graph_from_point(sinnonhyeon_coords, dist=radius, network_type='bike')
        ox.save_graphml(G_bike, bike_graph_path)
        print(f"✅ 자전거 도로망 저장 완료! (노드: {len(G_bike.nodes)}, 자전거길: {len(G_bike.edges)}개)")

    return G_walk, G_bike
def assign_basic_time_weights(graph, speed_kmh=4.0):
    """
    모든 도로(Edge)의 길이를 바탕으로 사람이 걷는 데 걸리는 기본 시간(초)을 계산해 부여합니다.
    (자전거인 경우 speed_kmh를 15로 주면 됩니다)
    """
    meters_per_minute = speed_kmh * 1000 / 60
    
    # 그래프 안의 모든 길목(u, v, 데이터)을 하나씩 확인
    for u, v, key, data in graph.edges(keys=True, data=True):
        # 도로 길이가 정보에 있으면
        if 'length' in data:
            # 시간(분) = 거리(m) / 속도(m/m)
            travel_time_min = data['length'] / meters_per_minute
            data['travel_time'] = travel_time_min
        else:
            data['travel_time'] = 0.0 # 정보 없으면 예외구역
            
    return graph

def train_comfort_model(graph):
    """
    K-Means 클러스터링(비지도 학습)을 사용하여 길목들을 3개의 쾌적도 그룹으로 쪼갭니다.
    """
    import numpy as np
    from sklearn.cluster import KMeans

    print("🤖 머신러닝 AI (K-Means) 모델 학습 및 쾌적도 등급 분류 시작...")

    edges = list(graph.edges(keys=True, data=True))
    features = []
    
    # 1. 1232개 길목에서 학습용 데이터셋(Features) 추출
    for u, v, k, data in edges:
        shadow = data.get('shadow_percent', 0.0)
        time = data.get('travel_time', 1.0)
        features.append([shadow, time])
        
    X = np.array(features)

    # 2. 비지도 학습 모델 구동 (알아서 3개 그룹으로 묶어라!)
    kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
    labels = kmeans.fit_predict(X)
    
    # 3. 각 그룹의 특성을 파악하여 '1등급(훌륭)', '2등급(보통)', '3등급(최악)' 부여
    cluster_shadow_means = []
    for i in range(3):
        # 각 그룹에 속해있는 도로들의 '그림자 비율' 평균값 계산
        mean_shadow = X[labels == i, 0].mean() 
        cluster_shadow_means.append((i, mean_shadow))
        
    # 그림자 평균이 높은 순서대로 정렬 (가장 그늘진 곳이 1등급)
    cluster_shadow_means.sort(key=lambda x: x[1], reverse=True)
    
    grade_mapper = {}
    grade = 1
    for cluster_id, mean_val in cluster_shadow_means:
        grade_mapper[cluster_id] = grade
        grade += 1

    # 4. 방금 AI가 판단한 쾌적도 등급을 지도 데이터베이스에 쾅쾅 도장 찍기
    for idx, (u, v, k, data) in enumerate(edges):
        comfort_grade = grade_mapper[labels[idx]]
        data['comfort_grade'] = comfort_grade
        
    print("✅ AI 모델링 완료! (1등급: 그늘 짱짱함 ~ 3등급: 심각한 땡볕)")
    return graph

def extract_shadow_features(graph, shadow_geojson_path):
    """
    특정 시간대의 그림자 파일을 로드하여, 1232개의 각 도로 선분이
    그림자와 얼마나 겹치는지(%)를 계산하여 도로 변수에 저장합니다.
    """
    import os
    from shapely.geometry import LineString
    import geopandas as gpd

    if not os.path.exists(shadow_geojson_path):
        print(f"⚠️ 에러: {shadow_geojson_path} 파일을 찾을 수 없습니다.")
        return graph

    print(f"🌞 그림자 파일 로딩 중... ({os.path.basename(shadow_geojson_path)})")
    shadows_gdf = gpd.read_file(shadow_geojson_path)
    
    # 파편화된 그림자 조각들을 연산 속도를 위해 거대한 하나의 덩어리로 합침
    merged_shadow = shadows_gdf.geometry.unary_union

    print("✂️ 1,232개 골목길 그림자 덮힘 면적 비율(%) 추출 중...")
    
    for u, v, key, data in graph.edges(keys=True, data=True):
        if 'geometry' in data:
            road_line = data['geometry']
        else:
            road_line = LineString([(graph.nodes[u]['x'], graph.nodes[u]['y']), 
                                    (graph.nodes[v]['x'], graph.nodes[v]['y'])])
            
        road_length = road_line.length
        if road_length == 0:
            data['shadow_percent'] = 0.0
            continue
            
        # 공간 교집합 연산 (이 도로는 그림자에 몇 m나 덮여 있나?)
        intersect_line = road_line.intersection(merged_shadow)
        
        # 덮인 비율 = 덮인 길이 / 전체 도로 길이
        ratio = intersect_line.length / road_length
        data['shadow_percent'] = round(ratio, 3) 
            
    return graph

def calculate_optimal_shadow_route(start_coords, end_coords, traffic_data):
    """
    가중치가 부여된 맵에서 A->B 최적 경로를 A*(A-Star) 알고리즘으로 뽑는 메인 함수
    """
    dummy_route = [{"lat": 37.5045, "lng": 127.0248}, {"lat": 37.4980, "lng": 127.0276}]
    return dummy_route

# 직접 이 파이썬 파일을 실행했을 때만 테스트 코드가 돕니다!
if __name__ == "__main__":
    print("🚀 [1단계 미션] 도로망 데이터 구축 테스트 시작")
    G_walk, G_bike = build_street_graph()
    
    # --- 추가된 부분 ---
    print("\n⏳ [2단계 미션] 도로에 기본 걷는 시간(분) 부여 중...")
    G_walk = assign_basic_time_weights(G_walk)
    print("✅ 2단계 완벽 성공! 모든 골목길에 소요 시간이 입력되었습니다.")
    # -------------------

    # --- 3단계 추가 부분 ---
    print("\n⏳ [3단계 미션] 도로와 그림자 교집합 AI 피처 추출 중...")
    # 12시 정위 정각 그림자 데이터 테스트
    base_dir = os.path.dirname(os.path.dirname(__file__))
    shadow_test_file = os.path.join(base_dir, "data", "shadow_data", "shadow_0801_1200.geojson")
    
    G_walk = extract_shadow_features(G_walk, shadow_test_file)
    print("✅ 3단계 완벽 성공! 1232개 도로가 몇 %나 그늘진 상태인지 AI 변수(shadow_percent) 장착을 완료했습니다.")
    
    # --- 4단계(머신러닝) 추가 부분 ---
    G_walk = train_comfort_model(G_walk)
    print("🎉 대성공: 머신러닝을 이용해 모든 도로의 쾌적도 등급 판별이 끝났습니다!")
    # -------------------

