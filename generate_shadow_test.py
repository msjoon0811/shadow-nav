import geopandas as gpd
import pandas as pd
import pybdshadow
from pyproj import Transformer
import time

print("=== 그림자 시뮬레이션 테스트 (8월 1일 12:00) ===")

# 1. 정제된 건물 데이터 로드
gdf = gpd.read_file('sinnonhyeon_buildings_500m_cleaned.shp', encoding='euc-kr')
print(f"건물 수: {len(gdf)}개")

# 2. 좌표계 변환 (EPSG:5186 → WGS84/EPSG:4326)
# pybdshadow는 WGS84(위경도) 좌표계를 사용
gdf_wgs84 = gdf.to_crs(epsg=4326)

# 3. pybdshadow가 요구하는 건물 DataFrame 형식으로 변환
# 필요 컬럼: geometry(Polygon), height(건물높이)
buildings = gdf_wgs84[['geometry']].copy()
buildings['height'] = gdf_wgs84['A17'].values

# 높이가 0 이하인 건물 제거 (안전장치)
buildings = buildings[buildings['height'] > 0].reset_index(drop=True)
print(f"높이 > 0 건물 수: {len(buildings)}개")

# 4. 특정 시간 설정 (2026년 8월 1일 12:00 KST → UTC로 변환 필요)
# KST = UTC + 9시간이므로, KST 12:00 = UTC 03:00
test_date = pd.Timestamp('2026-08-01 03:00:00')  # UTC 기준
print(f"시뮬레이션 시각: 2026-08-01 12:00 KST (UTC: {test_date})")

# 5. 그림자 계산
print("\n그림자 계산 중...")
start = time.time()
shadows = pybdshadow.bdshadow_sunlight(buildings, test_date, roof=True, include_building=False)
elapsed = time.time() - start
print(f"계산 완료! ({elapsed:.2f}초)")
print(f"생성된 그림자 폴리곤 수: {len(shadows)}개")

# 6. GeoJSON으로 저장
output_file = 'shadow_test_0801_1200.geojson'
shadows.to_file(output_file, driver='GeoJSON')
print(f"\n✅ 저장 완료: {output_file}")

# 7. 기본 통계
print(f"\n=== 그림자 통계 ===")
total_area = shadows.to_crs(epsg=5186).area.sum()
print(f"총 그림자 면적: {total_area:,.0f} ㎡ ({total_area/10000:.2f} ha)")
