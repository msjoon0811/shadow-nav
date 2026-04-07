import geopandas as gpd
import numpy as np

# 1. 데이터 로드
gdf = gpd.read_file('sinnonhyeon_buildings_500m.shp', encoding='euc-kr')

print("=== 🧹 데이터 정제 시작 ===")
print("=== 정제 전 통계 ===")
no_height = (gdf['A17'] == 0).sum()
print(f"총 건물 수: {len(gdf)}개")
print(f"높이가 0인 건물 불량 데이터: {no_height}개")
print(f"평균 건물 높이: {gdf['A17'].mean():.1f}m\n")

# 2. 정제 로직 적용
# 조건1: 기존 높이(A17)가 0보타 크면 그대로 유지
# 조건2: 높이가 0인데 지상층수(A26)가 있으면 '층수 * 3.0m' 로 계산
# 조건3: 높이도 0이고 층수도 0이면 (단층/가건물 가정) '기본 3.0m' 부여
gdf['height_cleaned'] = np.where(
    gdf['A17'] > 0, 
    gdf['A17'], 
    np.where(
        gdf['A26'] > 0,
        gdf['A26'] * 3.0, 
        3.0 
    )
)

print("=== 정제 후 통계 ===")
no_height_after = (gdf['height_cleaned'] == 0).sum()
print(f"높이가 0인 건물 데이터: {no_height_after}개 (완벽 해결!)")
print(f"평균 건물 높이 (정제 후): {gdf['height_cleaned'].mean():.1f}m")

# 3. 기존 컬럼 덮어쓰기 및 임시 컬럼 삭제
gdf['A17'] = gdf['height_cleaned']
gdf = gdf.drop(columns=['height_cleaned'])

# 4. 정제 완료된 새 파일로 저장
output_file = 'sinnonhyeon_buildings_500m_cleaned.shp'
gdf.to_file(output_file, encoding='euc-kr')
print(f"\n✅ 정제 완료! 다음 파일로 저장되었습니다: {output_file}")
