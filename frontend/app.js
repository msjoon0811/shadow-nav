/**
 * Shadow-Nav: 그늘길 내비게이션
 * Frontend - 카카오맵 버전
 */

// ============================================
// 1. 전역 변수 및 설정
// ============================================

const MAP_CENTER = { lat: 37.5045, lng: 127.0248 };
const MAP_ZOOM = 4;
const SHADOW_DATA_PATH = '../data/shadow_data';

let map = null;
let ps = null;
let geocoder = null;
let shadowPolygons = [];
let routePolyline = null;
let startMarker = null;
let endMarker = null;
let startCoord = null;
let endCoord = null;
let searchTimeout = null;
let isSidebarCollapsed = false;
let sidebarWidth = 340;

// ============================================
// 2. 지도 초기화
// ============================================

function initMap() {
    const container = document.getElementById('map');
    const options = {
        center: new kakao.maps.LatLng(MAP_CENTER.lat, MAP_CENTER.lng),
        level: MAP_ZOOM
    };

    map = new kakao.maps.Map(container, options);

    // 컨트롤 추가
    map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT);
    map.addControl(new kakao.maps.MapTypeControl(), kakao.maps.ControlPosition.TOPRIGHT);

    // 서비스 초기화
    ps = new kakao.maps.services.Places();
    geocoder = new kakao.maps.services.Geocoder();

    // 클릭 이벤트
    kakao.maps.event.addListener(map, 'click', onMapClick);

    console.log('✅ 카카오맵 초기화 완료');
}

// ============================================
// 3. 장소 검색
// ============================================

function initSearch() {
    const startInput = document.getElementById('start-input');
    const endInput = document.getElementById('end-input');
    const startResults = document.getElementById('start-results');
    const endResults = document.getElementById('end-results');

    startInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => searchPlaces(e.target.value, startResults, 'start'), 300);
    });

    endInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => searchPlaces(e.target.value, endResults, 'end'), 300);
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest('.input-wrapper')) {
            startResults.classList.remove('active');
            endResults.classList.remove('active');
        }
    });
}

function searchPlaces(keyword, resultsEl, type) {
    if (!keyword || keyword.length < 2) {
        resultsEl.classList.remove('active');
        return;
    }

    ps.keywordSearch(keyword, (data, status) => {
        if (status === kakao.maps.services.Status.OK) {
            displaySearchResults(data, resultsEl, type);
        } else {
            resultsEl.innerHTML = '<li>검색 결과가 없습니다.</li>';
            resultsEl.classList.add('active');
        }
    }, {
        location: new kakao.maps.LatLng(MAP_CENTER.lat, MAP_CENTER.lng),
        radius: 5000
    });
}

function displaySearchResults(places, resultsEl, type) {
    resultsEl.innerHTML = '';
    
    places.slice(0, 5).forEach(place => {
        const li = document.createElement('li');
        li.innerHTML = `
            <div class="place-name">${place.place_name}</div>
            <div class="place-address">${place.address_name}</div>
        `;
        li.addEventListener('click', () => {
            selectPlace(place, type);
            resultsEl.classList.remove('active');
        });
        resultsEl.appendChild(li);
    });
    
    resultsEl.classList.add('active');
}

function selectPlace(place, type) {
    const coord = { lat: parseFloat(place.y), lng: parseFloat(place.x) };
    const position = new kakao.maps.LatLng(coord.lat, coord.lng);

    if (type === 'start') {
        document.getElementById('start-input').value = place.place_name;
        startCoord = coord;
        setMarker(position, 'start', place.place_name);
        showToast(`출발지: ${place.place_name}`, 'success');
    } else {
        document.getElementById('end-input').value = place.place_name;
        endCoord = coord;
        setMarker(position, 'end', place.place_name);
        showToast(`도착지: ${place.place_name}`, 'success');
    }

    map.panTo(position);
}

// ============================================
// 4. 마커 관리
// ============================================

function setMarker(position, type, title) {
    if (type === 'start' && startMarker) startMarker.setMap(null);
    if (type === 'end' && endMarker) endMarker.setMap(null);

    const imageSrc = type === 'start' 
        ? 'https://t1.daumcdn.net/localimg/localimages/07/mapapidoc/markerStar.png'
        : 'https://t1.daumcdn.net/localimg/localimages/07/mapapidoc/marker_red.png';
    
    const marker = new kakao.maps.Marker({
        position: position,
        map: map,
        image: new kakao.maps.MarkerImage(imageSrc, new kakao.maps.Size(24, 35)),
        title: title
    });

    const infowindow = new kakao.maps.InfoWindow({
        content: `<div style="padding:5px;font-size:12px;">${type === 'start' ? '📍 출발' : '🏁 도착'}: ${title}</div>`
    });

    kakao.maps.event.addListener(marker, 'mouseover', () => infowindow.open(map, marker));
    kakao.maps.event.addListener(marker, 'mouseout', () => infowindow.close());

    if (type === 'start') startMarker = marker;
    else endMarker = marker;
}

function onMapClick(mouseEvent) {
    const latlng = mouseEvent.latLng;
    const coord = { lat: latlng.getLat(), lng: latlng.getLng() };

    geocoder.coord2Address(coord.lng, coord.lat, (result, status) => {
        let placeName = `${coord.lat.toFixed(5)}, ${coord.lng.toFixed(5)}`;
        if (status === kakao.maps.services.Status.OK) {
            placeName = result[0].address.address_name;
        }

        if (!startCoord) {
            document.getElementById('start-input').value = placeName;
            startCoord = coord;
            setMarker(latlng, 'start', placeName);
            showToast('출발지 설정 완료! 도착지를 클릭하세요.', 'info');
        } else if (!endCoord) {
            document.getElementById('end-input').value = placeName;
            endCoord = coord;
            setMarker(latlng, 'end', placeName);
            showToast('도착지 설정 완료!', 'success');
        }
    });
}

// ============================================
// 5. 시간 슬라이더
// ============================================

function initTimeSlider() {
    const slider = document.getElementById('time-slider');
    const timeDisplay = document.getElementById('time-display');
    const tempDisplay = document.getElementById('temp-display');

    slider.addEventListener('input', (e) => {
        const minutes = parseInt(e.target.value);
        timeDisplay.textContent = minutesToTimeString(minutes);
        tempDisplay.textContent = `${simulateTemperature(minutes)}°C`;
    });

    slider.addEventListener('change', (e) => {
        loadShadowForTime(parseInt(e.target.value));
    });
}

function minutesToTimeString(minutes) {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return `${hours.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}`;
}

function timeToFileFormat(minutes) {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return `${hours.toString().padStart(2, '0')}${mins.toString().padStart(2, '0')}`;
}

function simulateTemperature(minutes) {
    const hour = minutes / 60;
    if (hour <= 10) return Math.round(28 + (hour - 9) * 2);
    if (hour <= 14) return Math.round(30 + (hour - 10) * 1);
    if (hour <= 16) return Math.round(34 - (hour - 14) * 0.5);
    return Math.round(33 - (hour - 16) * 1.5);
}

// ============================================
// 6. 그림자 데이터
// ============================================

async function loadShadowForTime(minutes) {
    showLoading(true, '그림자 데이터를 불러오는 중...');

    try {
        const roundedMinutes = Math.round(minutes / 5) * 5;
        const timeStr = timeToFileFormat(roundedMinutes);
        const url = `${SHADOW_DATA_PATH}/shadow_0801_${timeStr}.geojson`;

        const response = await fetch(url);
        if (!response.ok) throw new Error('파일 없음');

        const geojsonData = await response.json();
        renderShadow(geojsonData);
        showToast(`${minutesToTimeString(roundedMinutes)} 그림자 로드 완료`, 'success');
    } catch (error) {
        console.error('그림자 로딩 실패:', error);
        showToast('그림자 데이터 로딩 실패', 'error');
    } finally {
        showLoading(false);
    }
}

function renderShadow(geojsonData) {
    shadowPolygons.forEach(p => p.setMap(null));
    shadowPolygons = [];

    geojsonData.features.forEach(feature => {
        if (feature.geometry.type === 'Polygon') {
            const path = feature.geometry.coordinates[0].map(c => new kakao.maps.LatLng(c[1], c[0]));

            const polygon = new kakao.maps.Polygon({
                map: map,
                path: path,
                strokeWeight: 1,
                strokeColor: '#00d4aa',
                strokeOpacity: 0.6,
                fillColor: '#1e3c5a',
                fillOpacity: 0.5
            });

            kakao.maps.event.addListener(polygon, 'mouseover', () => polygon.setOptions({ fillOpacity: 0.7 }));
            kakao.maps.event.addListener(polygon, 'mouseout', () => polygon.setOptions({ fillOpacity: 0.5 }));

            shadowPolygons.push(polygon);
        }
    });

    console.log(`✅ ${shadowPolygons.length}개 그림자 렌더링`);
}

// ============================================
// 7. 길찾기
// ============================================

async function findRoute() {
    if (!startCoord || !endCoord) {
        showToast('출발지와 도착지를 모두 설정해주세요!', 'error');
        return;
    }

    const transportType = document.querySelector('input[name="transport"]:checked').value;
    showLoading(true, '최적의 그늘길을 계산하는 중...');

    try {
        // TODO: 백엔드 API 연동
        await simulateDemoRoute(transportType);
    } catch (error) {
        showToast('경로 계산 실패', 'error');
    } finally {
        showLoading(false);
    }
}

async function simulateDemoRoute(transportType) {
    await new Promise(r => setTimeout(r, 800));

    if (routePolyline) routePolyline.setMap(null);

    const path = [];
    const steps = 15;
    for (let i = 0; i <= steps; i++) {
        const t = i / steps;
        const lat = startCoord.lat + (endCoord.lat - startCoord.lat) * t;
        const lng = startCoord.lng + (endCoord.lng - startCoord.lng) * t;
        const offset = Math.sin(t * Math.PI) * 0.001 * (Math.random() - 0.5);
        path.push(new kakao.maps.LatLng(lat + offset, lng + offset));
    }

    routePolyline = new kakao.maps.Polyline({
        map: map,
        path: path,
        strokeWeight: 6,
        strokeColor: '#0099ff',
        strokeOpacity: 0.8
    });

    const bounds = new kakao.maps.LatLngBounds();
    path.forEach(p => bounds.extend(p));
    map.setBounds(bounds);

    if (transportType === 'bike') {
        document.getElementById('bike-info').style.display = 'block';
        document.getElementById('bike-station-info').innerHTML = `
            <div>📍 신논현역 1번출구 대여소 - <span class="bike-count">7대</span></div>
            <div>📍 강남역 10번출구 대여소 - <span class="bike-count">12대</span></div>
        `;
    } else {
        document.getElementById('bike-info').style.display = 'none';
    }

    showToast('🌳 그늘길 경로를 찾았습니다!', 'success');
    updateRouteInfo(transportType);
}

function updateRouteInfo(transportType) {
    const R = 6371;
    const dLat = (endCoord.lat - startCoord.lat) * Math.PI / 180;
    const dLng = (endCoord.lng - startCoord.lng) * Math.PI / 180;
    const a = Math.sin(dLat/2)**2 + Math.cos(startCoord.lat * Math.PI/180) * Math.cos(endCoord.lat * Math.PI/180) * Math.sin(dLng/2)**2;
    const distance = R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a)) * 1000;
    const speed = transportType === 'bike' ? 200 : 80;
    const time = Math.round(distance / speed);

    document.getElementById('info-card').innerHTML = `
        <strong>📍 경로 정보</strong><br>
        거리: 약 ${Math.round(distance)}m<br>
        예상 소요: 약 ${time}분 (${transportType === 'bike' ? '🚴 자전거' : '🚶 도보'})<br>
        <span style="color: #00d4aa;">🌳 그늘 구간: 약 ${Math.round(Math.random() * 30 + 50)}%</span>
    `;
}

// ============================================
// 8. 사이드바
// ============================================

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const mapEl = document.getElementById('map');
    const toggleBtn = document.getElementById('sidebar-toggle-btn');
    
    isSidebarCollapsed = !isSidebarCollapsed;
    
    if (isSidebarCollapsed) {
        sidebar.classList.add('collapsed');
        mapEl.classList.add('expanded');
        mapEl.style.left = '0';
        toggleBtn.classList.add('collapsed');
        toggleBtn.style.left = '0';
    } else {
        sidebar.classList.remove('collapsed');
        mapEl.classList.remove('expanded');
        mapEl.style.left = sidebarWidth + 'px';
        toggleBtn.classList.remove('collapsed');
        toggleBtn.style.left = sidebarWidth + 'px';
    }
    
    setTimeout(() => map.relayout(), 300);
}

function initSidebarResize() {
    const sidebar = document.getElementById('sidebar');
    const resizeHandle = document.getElementById('resize-handle');
    const mapEl = document.getElementById('map');
    const toggleBtn = document.getElementById('sidebar-toggle-btn');
    
    let isResizing = false;
    
    resizeHandle.addEventListener('mousedown', (e) => {
        isResizing = true;
        resizeHandle.classList.add('active');
        document.body.style.cursor = 'ew-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });
    
    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const newWidth = Math.min(500, Math.max(280, e.clientX));
        sidebarWidth = newWidth;
        sidebar.style.width = newWidth + 'px';
        mapEl.style.left = newWidth + 'px';
        toggleBtn.style.left = newWidth + 'px';
        document.documentElement.style.setProperty('--sidebar-width', newWidth + 'px');
    });
    
    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            resizeHandle.classList.remove('active');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            map.relayout();
        }
    });
}

// ============================================
// 9. UI 유틸리티
// ============================================

function showLoading(show, message = '로딩 중...') {
    const loading = document.getElementById('loading');
    loading.querySelector('.loading-text').textContent = message;
    loading.classList.toggle('active', show);
}

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type} show`;
    setTimeout(() => toast.classList.remove('show'), 3000);
}

function resetAll() {
    if (startMarker) startMarker.setMap(null);
    if (endMarker) endMarker.setMap(null);
    if (routePolyline) routePolyline.setMap(null);
    
    startMarker = endMarker = routePolyline = null;
    startCoord = endCoord = null;
    
    document.getElementById('start-input').value = '';
    document.getElementById('end-input').value = '';
    document.getElementById('bike-info').style.display = 'none';
    document.getElementById('info-card').innerHTML = `
        <strong>💡 TIP:</strong> 출발지와 도착지를 검색하거나 지도를 클릭하여 설정할 수 있어요.
    `;
    
    map.setCenter(new kakao.maps.LatLng(MAP_CENTER.lat, MAP_CENTER.lng));
    map.setLevel(MAP_ZOOM);
    
    showToast('초기화되었습니다.', 'info');
}

// ============================================
// 10. 초기화
// ============================================

window.onload = function() {
    console.log('🚀 Shadow-Nav 시작');
    
    // 카카오맵 SDK 로드 완료 후 실행
    kakao.maps.load(function() {
        console.log('✅ 카카오맵 SDK 로드 완료');
        
        initMap();
        initSearch();
        initTimeSlider();
        initSidebarResize();
        loadShadowForTime(720);
        
        console.log('✅ 초기화 완료!');
        showToast('지도를 클릭하거나 검색하여 출발지를 설정하세요!', 'info');
    });
};

window.toggleSidebar = toggleSidebar;
window.findRoute = findRoute;
window.resetAll = resetAll;