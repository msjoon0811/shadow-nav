import geopandas as gpd
import folium

print("데이터 읽는 중...")
# 1. 아까 뽑은 12시 정각 그림자 파일 (원하는 시간으로 바꾸셔도 됩니다)
shadow_gdf = gpd.read_file("shadow_data/shadow_0801_1200.geojson")

# 2. 신논현역 중심 지도 생성
m = folium.Map(location=[37.5045, 127.0248], zoom_start=16)

# 3. 그림자 데이터를 까만색 반투명 폴리곤으로 지도에 덮어씌우기
folium.GeoJson(
    shadow_gdf,
    style_function=lambda x: {
        'fillColor': '#000000',  # 까만색
        'color': '#000000',      # 테두리 까만색
        'weight': 1,
        'fillOpacity': 0.5       # 반투명도 지정
    }
).add_to(m)

# 4. HTML 웹페이지로 저장
m.save("my_shadow_map.html")
print("완료! my_shadow_map.html 파일이 생성되었습니다. 더블클릭해서 열어보세요!")
