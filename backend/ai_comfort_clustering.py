import os
import sys
import json
import networkx as nx
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString
from sklearn.cluster import KMeans
import osmnx as ox
import matplotlib.pyplot as plt

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def generate_ai_clusters():
    print("[K-Means] 쾌적도 군집화 시작...")
    
    # 1. 파일 경로 설정
    base_dir = os.path.dirname(os.path.dirname(__file__))
    graph_path = os.path.join(base_dir, "data", "walk_graph.graphml")
    shadow_path = os.path.join(base_dir, "data", "shadow_data", "shadow_0801_1400.geojson")
    
    # 2. 데이터 로드
    print("도로망 및 그림자 데이터 로딩 중 (14:00 기준)...")
    if not os.path.exists(graph_path) or not os.path.exists(shadow_path):
        print("캐시 파일이 없습니다. 앱을 먼저 구동해 도로/그림자 데이터를 생성해주세요.")
        return
        
    G = ox.load_graphml(graph_path)
    shadows_gdf = gpd.read_file(shadow_path)
    # DeprecationWarning 방지를 위해 union_all() 사용
    merged_shadow = shadows_gdf.geometry.union_all()
    
    # 3. 데이터 추출 (길이, 그늘 덮힘 비율 파악)
    print("공간 연산 중 (Intersection)...")
    edge_features = []
    
    for u, v, k, data in G.edges(keys=True, data=True):
        length = data.get('length', 10.0)
        geom = data.get('geometry')
        
        if geom is None:
            points = [(G.nodes[u]['y'], G.nodes[u]['x']), (G.nodes[v]['y'], G.nodes[v]['x'])]
            geom = LineString(points)
            
        # 교집합으로 그늘 비율 산출
        intersection = geom.intersection(merged_shadow)
        shadow_percent = intersection.length / geom.length if geom.length > 0 else 0
        
        edge_features.append({
            'u': u, 'v': v, 'k': k,
            'length': length,
            'shadow_percent': shadow_percent
        })
        
    df = pd.DataFrame(edge_features)
    df.fillna(0, inplace=True)
    
    # 4. 머신러닝 비지도 학습 (K-Means)
    print("[K-Means] 도로 쾌적도 군집화 진행 중...")
    # 길이와 그늘 비율 두 가지 변수를 활용해 거리를 무릅쓰고 갈 만한 길인지 3군집화
    features_for_ai = df[['length', 'shadow_percent']]
    
    kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
    df['cluster'] = kmeans.fit_predict(features_for_ai)
    
    # 군집 라벨링 (그늘이 가장 많은 클러스터를 1등급으로 매핑)
    cluster_means = df.groupby('cluster')['shadow_percent'].mean()
    sorted_clusters = cluster_means.sort_values(ascending=False).index
    
    grade_map = {
        sorted_clusters[0]: 1, # 초록 (우수)
        sorted_clusters[1]: 2, # 노랑 (보통)
        sorted_clusters[2]: 3  # 빨강 (열악)
    }
    df['comfort_grade'] = df['cluster'].map(grade_map)
    
    # 5. 시각화 및 결과 저장
    print("분류 결과 요약:\n", df['comfort_grade'].value_counts().sort_index())
    
    output_json = os.path.join(base_dir, "data", "ai_clusters_result.json")
    # 샘플 추출 저장을 통해 기획서 및 발표 시 모델 증빙 자료로 활용
    df[['u', 'v', 'length', 'shadow_percent', 'comfort_grade']].head(100).to_json(output_json, orient='records', force_ascii=False)
    print(f"분석 데이터 저장 완료: {output_json}")

if __name__ == "__main__":
    generate_ai_clusters()
