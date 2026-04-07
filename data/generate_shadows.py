"""
그림자 시뮬레이션 엔진 - 신논현역 반경 500m
pybdshadow 대신 suncalc + shapely로 직접 구현

원리:
1. suncalc로 특정 시각의 태양 고도(altitude)와 방위각(azimuth)을 계산
2. 건물 높이와 태양 고도로 그림자 길이를 계산: shadow_length = height / tan(altitude)
3. 태양 방위각의 반대 방향으로 건물 꼭짓점을 shadow_length만큼 이동
4. 원래 건물 + 이동된 꼭짓점을 합쳐서 그림자 폴리곤 생성
"""
import geopandas as gpd
import pandas as pd
import numpy as np
from suncalc import get_position
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from datetime import datetime, timedelta, timezone
from pyproj import Transformer
import json
import time
import os
import math

# ============================================================
# 설정
# ============================================================
SINNONHYEON_LAT = 37.5045
SINNONHYEON_LNG = 127.0248

# 시뮬레이션 기준일: 2026년 8월 1일
BASE_DATE = "2026-08-01"
# 시간 범위: 오전 9시 ~ 오후 6시 (KST)
START_HOUR = 9
END_HOUR = 18
# 간격: 5분
INTERVAL_MINUTES = 5

# KST → UTC 오프셋
KST_OFFSET = 9

# ============================================================
# 그림자 계산 함수
# ============================================================
def calculate_shadow_for_building(building_geom, height, sun_altitude, sun_azimuth):
    """
    단일 건물의 그림자 폴리곤을 계산합니다.
    
    Parameters:
        building_geom: 건물 폴리곤 (미터 단위 좌표계)
        height: 건물 높이 (m)
        sun_altitude: 태양 고도 (radians)
        sun_azimuth: 태양 방위각 (radians, 남쪽=0, 시계방향)
    
    Returns:
        그림자 폴리곤 (Polygon)
    """
    if sun_altitude <= 0:
        return None  # 해가 지평선 아래면 그림자 없음
    
    # 그림자 길이 계산
    shadow_length = height / math.tan(sun_altitude)
    
    # 태양 방위각의 반대 방향으로 오프셋 (그림자는 태양 반대편에 생김)
    # suncalc의 azimuth: 남쪽=0, 서쪽=π/2 (시계방향)
    # 우리 좌표계에서 x=동쪽, y=북쪽
    # 태양이 남쪽(azimuth=0)에 있으면 그림자는 북쪽(+y)으로 생김
    dx = -shadow_length * math.sin(sun_azimuth)
    dy = -shadow_length * math.cos(sun_azimuth)
    
    # 건물 꼭짓점을 그림자 방향으로 이동
    if building_geom.geom_type == 'Polygon':
        coords = list(building_geom.exterior.coords)
    else:
        return None
    
    # 이동된 꼭짓점으로 그림자 끝부분 생성
    shadow_coords = [(x + dx, y + dy) for x, y in coords]
    
    # 건물 폴리곤 + 그림자 끝 폴리곤을 합쳐서 전체 그림자 영역 생성
    try:
        shadow_tip = Polygon(shadow_coords)
        full_shadow = unary_union([building_geom, shadow_tip]).convex_hull
        return full_shadow
    except Exception:
        return None


def generate_shadow_for_time(buildings_gdf, target_datetime_utc, lat, lng):
    """
    특정 시각의 전체 그림자 데이터를 생성합니다.
    
    Parameters:
        buildings_gdf: 건물 GeoDataFrame (미터 단위 좌표계, 'A17' = 높이)
        target_datetime_utc: 시뮬레이션 시각 (UTC datetime)
        lat, lng: 위치 좌표 (WGS84)
    
    Returns:
        그림자 GeoDataFrame (WGS84)
    """
    # 태양 위치 계산
    sun_pos = get_position(target_datetime_utc, lng, lat)
    altitude = sun_pos['altitude']  # radians
    azimuth = sun_pos['azimuth']    # radians
    
    altitude_deg = math.degrees(altitude)
    azimuth_deg = math.degrees(azimuth)
    
    if altitude <= 0:
        return None  # 해가 안 떴으면 스킵
    
    # 각 건물의 그림자 계산
    shadows = []
    for idx, row in buildings_gdf.iterrows():
        height = row['A17']
        if height <= 0:
            continue
        shadow = calculate_shadow_for_building(row.geometry, height, altitude, azimuth)
        if shadow is not None and shadow.is_valid and not shadow.is_empty:
            shadows.append(shadow)
    
    if not shadows:
        return None
    
    # 모든 그림자를 하나의 GeoDataFrame으로
    shadow_gdf = gpd.GeoDataFrame(geometry=shadows, crs=buildings_gdf.crs)
    
    # WGS84로 변환해서 반환
    shadow_gdf_wgs84 = shadow_gdf.to_crs(epsg=4326)
    
    return shadow_gdf_wgs84, altitude_deg, azimuth_deg


# ============================================================
# 메인 실행
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("🏙️  신논현역 그림자 시뮬레이션 엔진")
    print(f"📅  기준일: {BASE_DATE}")
    print(f"⏰  시간: {START_HOUR}:00 ~ {END_HOUR}:00 KST ({INTERVAL_MINUTES}분 간격)")
    print("=" * 60)
    
    # 1. 건물 데이터 로드 (EPSG:5186 - 미터 단위)
    print("\n📂 건물 데이터 로딩...")
    gdf = gpd.read_file('sinnonhyeon_buildings_500m_cleaned.shp', encoding='euc-kr')
    print(f"   건물 수: {len(gdf)}개")
    
    # 2. 출력 디렉토리 생성
    output_dir = "shadow_data"
    os.makedirs(output_dir, exist_ok=True)
    
    # 3. 시간 목록 생성
    time_slots = []
    current = datetime.strptime(f"{BASE_DATE} {START_HOUR:02d}:00", "%Y-%m-%d %H:%M")
    end = datetime.strptime(f"{BASE_DATE} {END_HOUR:02d}:00", "%Y-%m-%d %H:%M")
    while current <= end:
        time_slots.append(current)
        current += timedelta(minutes=INTERVAL_MINUTES)
    
    print(f"   생성할 그림자 데이터: {len(time_slots)}개")
    
    # 4. 테스트: 먼저 1개만 해보기
    print(f"\n🔬 테스트: {BASE_DATE} 12:00 KST 그림자 생성...")
    test_kst = datetime.strptime(f"{BASE_DATE} 12:00", "%Y-%m-%d %H:%M")
    test_utc = test_kst.replace(tzinfo=timezone.utc) - timedelta(hours=KST_OFFSET)
    
    start_time = time.time()
    result = generate_shadow_for_time(gdf, test_utc, SINNONHYEON_LAT, SINNONHYEON_LNG)
    elapsed = time.time() - start_time
    
    if result:
        shadow_gdf, alt, azi = result
        print(f"   ✅ 성공! (소요시간: {elapsed:.2f}초)")
        print(f"   ☀️  태양 고도: {alt:.1f}°, 방위각: {azi:.1f}°")
        print(f"   🏗️  그림자 폴리곤 수: {len(shadow_gdf)}개")
        
        # 테스트 파일 저장
        test_file = os.path.join(output_dir, "shadow_0801_1200.geojson")
        shadow_gdf.to_file(test_file, driver='GeoJSON')
        print(f"   💾 저장: {test_file}")
    else:
        print("   ❌ 실패 - 태양이 지평선 아래입니다.")
        exit(1)
    
    # 5. 전체 시간대 일괄 생성
    print(f"\n🚀 전체 {len(time_slots)}개 시간대 그림자 일괄 생성 시작!")
    print(f"   예상 소요시간: 약 {elapsed * len(time_slots) / 60:.1f}분")
    
    total_start = time.time()
    success_count = 0
    
    for i, slot_kst in enumerate(time_slots):
        slot_utc = slot_kst.replace(tzinfo=timezone.utc) - timedelta(hours=KST_OFFSET)
        time_str = slot_kst.strftime("%H%M")
        
        result = generate_shadow_for_time(gdf, slot_utc, SINNONHYEON_LAT, SINNONHYEON_LNG)
        
        if result:
            shadow_gdf, alt, azi = result
            filename = f"shadow_0801_{time_str}.geojson"
            filepath = os.path.join(output_dir, filename)
            shadow_gdf.to_file(filepath, driver='GeoJSON')
            success_count += 1
            
            if (i + 1) % 12 == 0 or i == 0:  # 매 1시간마다 또는 첫번째
                print(f"   [{i+1}/{len(time_slots)}] {slot_kst.strftime('%H:%M')} KST | 태양 고도: {alt:.1f}° | 그림자 {len(shadow_gdf)}개")
    
    total_elapsed = time.time() - total_start
    
    print(f"\n{'=' * 60}")
    print(f"✅ 완료!")
    print(f"   성공: {success_count}/{len(time_slots)}개")
    print(f"   총 소요시간: {total_elapsed:.1f}초 ({total_elapsed/60:.1f}분)")
    print(f"   저장 위치: {output_dir}/")
    print(f"{'=' * 60}")
