import geopandas as gpd
from shapely.geometry import Point
from pyproj import Transformer
import time

# 신논현역 좌표 (WGS84)
SINNONHYEON_LNG = 127.0248
SINNONHYEON_LAT = 37.5045
RADIUS_M = 500  # 지름 1km = 반지름 500m

print("=" * 50)
print("신논현역 중심 지름 1km (반지름 500m) 건물 필터링")
print("=" * 50)

# 좌표 변환 (WGS84 → EPSG:5186)
transformer = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True)
center_x, center_y = transformer.transform(SINNONHYEON_LNG, SINNONHYEON_LAT)
print(f"신논현역 좌표 (EPSG:5186): {center_x:.2f}, {center_y:.2f}")

# 서울 전체 건물 데이터 로드
print("\n서울 건물 데이터 로딩 중...")
start = time.time()
gdf = gpd.read_file("AL_D010_11_20260309.shp", encoding="euc-kr")
print(f"로딩 완료! ({time.time()-start:.1f}초, 총 {len(gdf):,}개 건물)")

# 반지름 500m 원 생성 및 필터링
center_point = Point(center_x, center_y)
buffer_circle = center_point.buffer(RADIUS_M)

print(f"\n반지름 {RADIUS_M}m (지름 1km) 원 내 건물 필터링 중...")
gdf_filtered = gdf[gdf.geometry.intersects(buffer_circle)].copy()
print(f"결과: {len(gdf_filtered):,}개 건물")

# 통계 출력
print(f"\n=== 필터링 결과 ===")
print(f"주소 분포:")
for addr, cnt in gdf_filtered['A4'].value_counts().items():
    print(f"  {addr}: {cnt}개")

print(f"\n지상층수(A26): min={gdf_filtered['A26'].min()}, max={gdf_filtered['A26'].max()}, mean={gdf_filtered['A26'].mean():.1f}")
print(f"건물높이(A17): min={gdf_filtered['A17'].min():.1f}m, max={gdf_filtered['A17'].max():.1f}m, mean={gdf_filtered['A17'].mean():.1f}m")

# 높이 0인 건물 비율
no_height = (gdf_filtered['A17'] == 0).sum()
print(f"\n높이 0인 건물: {no_height}개 ({no_height/len(gdf_filtered)*100:.1f}%)")
print(f"높이 있는 건물: {len(gdf_filtered)-no_height}개")

# 저장
output_path = "sinnonhyeon_buildings_500m.shp"
gdf_filtered.to_file(output_path, encoding="euc-kr")
print(f"\n저장 완료: {output_path}")
