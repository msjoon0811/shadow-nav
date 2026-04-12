const API_BASE = "https://shadow-nav-api.onrender.com";

let map = null;
let shadowPolygons = [];
let routePolyline = null;
let startMarker = null;
let endMarker = null;

let selected = { start: null, end: null };
let isSidebarCollapsed = false;
let sidebarWidth = 340;
let isDepartNow = true;

let bikeOverlays = [];
let signalOverlays = [];
let openInfoWindow = null;
let _shadowAbort = null;

// 1. 초기화 (백엔드에서 API 키 가져오기)
document.addEventListener("DOMContentLoaded", async () => {
    showLoading(true, "초기 설정 중...");
    try {
        const res = await fetch(`${API_BASE}/api/config`);
        const { kakao_js_key } = await res.json();
        await loadKakaoSDK(kakao_js_key);

        initMap();
        initSearchInput("start-input", "start-results", "start");
        initSearchInput("end-input", "end-results", "end");
        initTimeControls();
        initSidebarResize();

        applyTimeSetting(true);
        showToast("지도를 클릭하거나 검색하여 출발지를 설정하세요!", "info");
    } catch (e) {
        showToast("서버 연결 실패: 백엔드(8000)를 확인하세요.", "error");
        console.error(e);
    } finally {
        showLoading(false);
    }
});

function loadKakaoSDK(appkey) {
    return new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = `//dapi.kakao.com/v2/maps/sdk.js?appkey=${appkey}&autoload=false`;
        script.onload = () => kakao.maps.load(resolve);
        script.onerror = reject;
        document.head.appendChild(script);
    });
}

function initMap() {
    map = new kakao.maps.Map(document.getElementById("map"), {
        center: new kakao.maps.LatLng(37.5045, 127.0248),
        level: 4,
    });
    kakao.maps.event.addListener(map, "click", onMapClick);
}

// 2. 검색 기능 (백엔드 API 호출)
function initSearchInput(inputId, dropdownId, key) {
    const input = document.getElementById(inputId);
    const dropdown = document.getElementById(dropdownId);
    let debounceTimer = null;

    input.addEventListener("input", () => {
        selected[key] = null;
        clearTimeout(debounceTimer);
        const q = input.value.trim();

        if (!q) {
            dropdown.classList.remove("active");
            return;
        }
        debounceTimer = setTimeout(() => fetchSuggestions(q, input, dropdown, key), 300);
    });

    document.addEventListener("click", (e) => {
        if (!input.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.classList.remove("active");
        }
    });
}

async function fetchSuggestions(query, input, dropdown, key) {
    try {
        const center = map.getCenter();
        const url = `${API_BASE}/api/search?query=${encodeURIComponent(query)}&x=${center.getLng()}&y=${center.getLat()}`;
        const res = await fetch(url);
        if (!res.ok) return;
        const results = await res.json();

        dropdown.innerHTML = "";
        if (!results.length) {
            dropdown.classList.remove("active");
            return;
        }

        results.forEach(r => {
            const li = document.createElement("li");
            li.innerHTML = `<div class="place-name">${r.name}</div><div class="place-address">${r.address}</div>`;
            li.addEventListener("click", () => {
                selected[key] = r;
                input.value = r.name;
                dropdown.classList.remove("active");
                setMarker(new kakao.maps.LatLng(r.lat, r.lng), key, r.name);
                map.panTo(new kakao.maps.LatLng(r.lat, r.lng));
            });
            dropdown.appendChild(li);
        });
        dropdown.classList.add("active");
    } catch (e) { console.error("Search Error:", e); }
}

// 3. 지오코딩 & 클릭
async function geocode(query) {
    const res = await fetch(`${API_BASE}/api/geocode?query=${encodeURIComponent(query)}`);
    if (!res.ok) throw new Error("장소를 찾을 수 없습니다.");
    return res.json();
}

async function onMapClick(mouseEvent) {
    const latlng = mouseEvent.latLng;
    const coord = { lat: latlng.getLat(), lng: latlng.getLng() };

    // 단순 좌표를 장소명으로 변환하는 것은 카카오 Geocoder API가 편리하므로 백엔드 우회
    const geocoder = new kakao.maps.services.Geocoder();
    geocoder.coord2Address(coord.lng, coord.lat, (result, status) => {
        let placeName = `${coord.lat.toFixed(5)}, ${coord.lng.toFixed(5)}`;
        if (status === kakao.maps.services.Status.OK && result[0]) {
            placeName = result[0].address.address_name;
        }

        if (!selected.start) {
            selected.start = { lat: coord.lat, lng: coord.lng, name: placeName };
            document.getElementById("start-input").value = placeName;
            setMarker(latlng, "start", placeName);
            showToast("출발지 설정 완료! 도착지를 클릭하세요.", "info");
        } else if (!selected.end) {
            selected.end = { lat: coord.lat, lng: coord.lng, name: placeName };
            document.getElementById("end-input").value = placeName;
            setMarker(latlng, "end", placeName);
            showToast("도착지 설정 완료!", "success");
        }
    });
}

function setMarker(position, type, title) {
    if (type === "start" && startMarker) startMarker.setMap(null);
    if (type === "end" && endMarker) endMarker.setMap(null);

    const imageSrc = type === "start" ? "https://t1.daumcdn.net/localimg/localimages/07/mapapidoc/markerStar.png" : "https://t1.daumcdn.net/localimg/localimages/07/mapapidoc/marker_red.png";
    const marker = new kakao.maps.Marker({ position, map, image: new kakao.maps.MarkerImage(imageSrc, new kakao.maps.Size(24, 35)), title });

    if (type === "start") startMarker = marker;
    else endMarker = marker;
}

// 4. 시간 연동 로직 (슬라이더 + 타이핑)
function initTimeControls() {
    const slider = document.getElementById("time-slider");
    const display = document.getElementById("time-display");
    const tempDisplay = document.getElementById("temp-display");

    // 슬라이더 조작 시 -> 텍스트 업데이트
    slider.addEventListener("input", (e) => {
        const mins = parseInt(e.target.value, 10);
        display.value = formatTime(Math.floor(mins / 60), mins % 60);
        tempDisplay.textContent = `${simulateTemperature(mins)}°C`;
    });

    // 슬라이더 놓았을 때 -> 백엔드 요청
    slider.addEventListener("change", (e) => {
        loadShadowLayer(display.value);
    });

    // 텍스트 직접 입력 시 -> 슬라이더 업데이트 & 백엔드 요청
    display.addEventListener("change", (e) => {
        const val = e.target.value;
        if (!/^\d{1,2}:\d{2}$/.test(val)) return;
        const [h, m] = val.split(":").map(Number);
        if (h >= 9 && h <= 18 && m <= 59) {
            const totalMins = h * 60 + m;
            slider.value = totalMins;
            tempDisplay.textContent = `${simulateTemperature(totalMins)}°C`;
            loadShadowLayer(val);
        }
    });
}

function formatTime(h, m) {
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function simulateTemperature(minutes) {
    const hour = minutes / 60;
    if (hour <= 10) return Math.round(28 + (hour - 9) * 2);
    if (hour <= 14) return Math.round(30 + (hour - 10) * 1);
    return Math.round(34 - (hour - 14) * 0.5);
}

// 5. 그림자 데이터 (AbortController 적용)
async function loadShadowLayer(timeStr) {
    if (_shadowAbort) _shadowAbort.abort();
    _shadowAbort = new AbortController();

    shadowPolygons.forEach(p => p.setMap(null));
    shadowPolygons = [];
    showLoading(true, "그림자 데이터 렌더링 중...");

    try {
        const res = await fetch(`${API_BASE}/api/shadow/${timeStr.replace(":", "-")}`, { signal: _shadowAbort.signal });
        if (!res.ok) throw new Error("데이터 없음");

        const geojson = await res.json();

        for (const feature of geojson.features) {
            const geom = feature.geometry;
            const rings = geom.type === "Polygon" ? [geom.coordinates[0]] : geom.coordinates.map(c => c[0]);

            for (const ring of rings) {
                const path = ring.map(([lng, lat]) => new kakao.maps.LatLng(lat, lng));
                shadowPolygons.push(new kakao.maps.Polygon({
                    map, path, strokeWeight: 0, fillColor: "#1e3c5a", fillOpacity: 0.4
                }));
            }
        }
    } catch (e) {
        if (e.name !== "AbortError") console.warn("그림자 실패:", e);
    } finally {
        showLoading(false);
    }
}

// 6. 길찾기 로직
async function findRoute() {
    const startQuery = document.getElementById("start-input").value.trim();
    const endQuery = document.getElementById("end-input").value.trim();
    const timeStr = document.getElementById("time-display").value;
    const mode = document.querySelector('input[name="transport"]:checked').value;
    const weightMode = document.querySelector('input[name="weight"]:checked').value;

    if (!startQuery || !endQuery) {
        showToast("출발지와 도착지를 모두 설정해주세요!", "error");
        return;
    }

    let loadingMsg = "최적의 경로 계산 중...";
    if (weightMode === 'max_shadow') loadingMsg = "그림자가 가장 많은 경로 계산 중...";
    else if (weightMode === 'fastest') loadingMsg = "가장 빠른 경로 계산 중...";

    showLoading(true, loadingMsg);

    try {
        const [startCoord, endCoord] = await Promise.all([
            selected.start || geocode(startQuery),
            selected.end || geocode(endQuery),
        ]);

        selected.start = startCoord;
        selected.end = endCoord;

        const res = await fetch(`${API_BASE}/api/route`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                start_lat: startCoord.lat, start_lng: startCoord.lng,
                end_lat: endCoord.lat, end_lng: endCoord.lng,
                time_str: timeStr, mode, weight_mode: weightMode,
                is_depart_now: isDepartNow
            })
        });

        if (!res.ok) throw new Error("서버 경로 계산 오류");
        const data = await res.json();

        if (routePolyline) routePolyline.setMap(null);
        const path = (data.route || []).map(c => new kakao.maps.LatLng(c.lat, c.lng));
        routePolyline = new kakao.maps.Polyline({
            map, path, strokeWeight: 6, strokeColor: "#00d4aa", strokeOpacity: 0.9, strokeStyle: "solid"
        });

        const bounds = new kakao.maps.LatLngBounds();
        path.forEach(p => bounds.extend(p));
        map.setBounds(bounds);

        renderBikeStations(data.ddareungi_stations || [], mode);
        renderSignals(data.signal_data || []);

        document.getElementById("info-card").innerHTML = `<strong>🌳 그늘길 경로 탐색 완료!</strong><br>안전하게 이동하세요.`;
        showToast("경로를 찾았습니다!", "success");

    } catch (e) {
        showToast(e.message, "error");
    } finally {
        showLoading(false);
    }
}

// 7. 자전거 & 신호등 렌더링
function renderBikeStations(stations, mode) {
    bikeOverlays.forEach(o => o.setMap(null));
    bikeOverlays = [];
    const infoPanel = document.getElementById("bike-info");
    const infoList = document.getElementById("bike-station-info");
    infoList.innerHTML = "";

    if (mode !== "bike" || !stations.length) {
        infoPanel.style.display = "none";
        return;
    }

    stations.forEach(s => {
        const overlay = new kakao.maps.CustomOverlay({
            position: new kakao.maps.LatLng(s.lat, s.lng),
            content: `<div class="bike-marker">${s.available ?? 0}</div>`,
            map, yAnchor: 0.5, xAnchor: 0.5
        });
        bikeOverlays.push(overlay);
        infoList.innerHTML += `<div>📍 ${s.name} - <strong style="color:var(--cool-mint)">${s.available ?? 0}대</strong></div>`;
    });
    infoPanel.style.display = "block";
}

function renderSignals(signals) {
    signalOverlays.forEach(o => o.setMap(null));
    signalOverlays = [];

    signals.forEach(s => {
        const isRed = s.red_remaining_sec > 0;
        const color = isRed ? "#e53935" : "#43a047";
        const emoji = isRed ? "🔴" : "🟢";
        const overlay = new kakao.maps.CustomOverlay({
            position: new kakao.maps.LatLng(s.lat, s.lng),
            content: `<div style="width:20px;height:20px;border-radius:50%;background:${color};border:2px solid #fff;display:flex;align-items:center;justify-content:center;font-size:10px;">${emoji}</div>`,
            map, yAnchor: 0.5, xAnchor: 0.5
        });
        signalOverlays.push(overlay);
    });
}

// 8. 기타 UI 유틸
function showLoading(show, message = "로딩 중...") {
    const loading = document.getElementById("loading");
    if (loading.querySelector(".loading-text")) loading.querySelector(".loading-text").textContent = message;
    loading.classList.toggle("active", show);
}

function showToast(message, type = "info") {
    const toast = document.getElementById("toast");
    toast.textContent = message;
    toast.className = `toast ${type} show`;
    setTimeout(() => toast.classList.remove("show"), 3000);
}

function toggleSidebar() {
    isSidebarCollapsed = !isSidebarCollapsed;
    document.getElementById("sidebar").classList.toggle("collapsed", isSidebarCollapsed);
    document.getElementById("map").classList.toggle("expanded", isSidebarCollapsed);
    document.getElementById("sidebar-toggle-btn").classList.toggle("collapsed", isSidebarCollapsed);

    if (isSidebarCollapsed) {
        document.getElementById("map").style.left = "0px";
        document.getElementById("sidebar-toggle-btn").style.left = "0px";
    } else {
        document.getElementById("map").style.left = sidebarWidth + "px";
        document.getElementById("sidebar-toggle-btn").style.left = sidebarWidth + "px";
    }

    setTimeout(() => { if (map) map.relayout(); }, 300);
}

function initSidebarResize() {
    const sidebar = document.getElementById("sidebar");
    const resizeHandle = document.getElementById("resize-handle");
    let isResizing = false;

    resizeHandle.addEventListener("mousedown", () => { isResizing = true; });
    document.addEventListener("mousemove", (e) => {
        if (!isResizing) return;
        sidebarWidth = Math.min(500, Math.max(280, e.clientX));
        sidebar.style.width = sidebarWidth + "px";
        document.getElementById("map").style.left = sidebarWidth + "px";
        document.getElementById("sidebar-toggle-btn").style.left = sidebarWidth + "px";
    });
    document.addEventListener("mouseup", () => {
        if (isResizing) { isResizing = false; if (map) map.relayout(); }
    });
}

function resetAll() {
    if (startMarker) startMarker.setMap(null);
    if (endMarker) endMarker.setMap(null);
    if (routePolyline) routePolyline.setMap(null);
    bikeOverlays.forEach(o => o.setMap(null));
    signalOverlays.forEach(o => o.setMap(null));

    startMarker = null; endMarker = null; routePolyline = null;
    selected = { start: null, end: null };

    document.getElementById("start-input").value = "";
    document.getElementById("end-input").value = "";
    document.getElementById("bike-info").style.display = "none";
    showToast("초기화되었습니다.");
}

// 9. 출발 시간 설정 팝업 UI
function toggleTimePopup() {
    document.getElementById("time-popup").classList.toggle("hidden");
}

function toggleCustomTimeSelectors() {
    const isCustom = document.querySelector('input[name="depart_time_type"]:checked').value === 'custom';
    document.getElementById("custom-time-selectors").classList.toggle("hidden", !isCustom);
}

function getCurrentRoundedTime() {
    const now = new Date();
    let m = Math.round(now.getMinutes() / 5) * 5;
    let h = now.getHours();
    if (m === 60) { h += 1; m = 0; }
    if (h >= 24) { h -= 24; }
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function applyTimeSetting(isInitial = false) {
    const type = document.querySelector('input[name="depart_time_type"]:checked')?.value || 'now';
    isDepartNow = (type === 'now');
    
    let timeStr = "";
    if (isDepartNow) {
        timeStr = getCurrentRoundedTime();
    } else {
        const h = document.getElementById("custom-hour").value;
        const m = document.getElementById("custom-minute").value;
        timeStr = `${h}:${m}`;
    }

    // 그림자 데이터 없는 시간대 예외 처리
    const [hh] = timeStr.split(":").map(Number);
    if (hh < 9 || hh > 18 || (hh === 18 && Number(timeStr.split(":")[1]) > 0)) { 
        const fastestRadio = document.querySelector('input[name="weight"][value="fastest"]');
        if (fastestRadio && !fastestRadio.checked) {
            fastestRadio.checked = true;
            if (!isInitial) showToast("선택한 시간은 그림자 데이터가 없어 최단 시간 경로로 안내합니다.", "info");
        }
    }

    document.getElementById("time-display").value = timeStr;
    const [ph, pm] = timeStr.split(":").map(Number);
    const totalMins = ph * 60 + pm;
    document.getElementById("time-slider").value = totalMins;
    document.getElementById("temp-display").textContent = `${simulateTemperature(totalMins)}°C`;

    document.getElementById("time-popup").classList.add("hidden");
    loadShadowLayer(timeStr);
}