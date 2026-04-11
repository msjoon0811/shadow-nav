// Shadow-Nav 프론트엔드 — 카카오맵 기반

const API_BASE = "http://localhost:8002";

let map             = null;
let routePolyline   = null;
let shadowPolygons  = [];
let markerStart     = null;
let markerEnd       = null;
let bikeOverlays    = [];
let signalOverlays  = [];
let openInfoWindow  = null;

// ── 앱 초기화 ─────────────────────────────────────────────────────────────────

async function initApp() {
    try {
        const res = await fetch(`${API_BASE}/api/config`);
        const { kakao_js_key } = await res.json();
        await loadKakaoSDK(kakao_js_key);
    } catch (e) {
        setStatus("카카오맵 초기화 실패: " + e.message, "error");
        return;
    }

    map = new kakao.maps.Map(document.getElementById("map"), {
        center: new kakao.maps.LatLng(37.5045, 127.0248),
        level:  3,
    });

    setNow();
    initSearchInput("input-start", "dropdown-start", "start");
    initSearchInput("input-end",   "dropdown-end",   "end");

    document.getElementById("time-display").addEventListener("change", onTimeDisplayInput);
    document.getElementById("time-picker").addEventListener("change", (e) => {
        document.getElementById("btn-now").classList.remove("active");
        const [h, m] = e.target.value.split(":").map(Number);
        syncTimeDisplay(h, m);
    });
}

function loadKakaoSDK(appkey) {
    return new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = `//dapi.kakao.com/v2/maps/sdk.js?appkey=${appkey}&autoload=false`;
        script.onload  = () => kakao.maps.load(resolve);
        script.onerror = reject;
        document.head.appendChild(script);
    });
}

// ── 시간 상태 ─────────────────────────────────────────────────────────────────

function roundToFive(date) {
    const h = date.getHours();
    const m = Math.round(date.getMinutes() / 5) * 5;
    return m >= 60 ? { h: h + 1, m: 0 } : { h, m };
}

function formatTime(h, m) {
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function clampTime(h, m) {
    let total = h * 60 + m;
    total = Math.max(9 * 60, Math.min(18 * 60, total));
    return { h: Math.floor(total / 60), m: total % 60 };
}

function syncTimeDisplay(h, m) {
    const { h: ch, m: cm } = clampTime(h, m);
    const timeStr = formatTime(ch, cm);
    document.getElementById("time-display").value = timeStr;
    document.getElementById("time-picker").value = timeStr;
    if (map) loadShadowLayer(timeStr);
}

function setNow() {
    const { h, m } = roundToFive(new Date());
    syncTimeDisplay(h, m);
    document.getElementById("btn-now").classList.add("active");
}

function adjustTime(delta) {
    document.getElementById("btn-now").classList.remove("active");
    const val = document.getElementById("time-display").value || "12:00";
    const [h, m] = val.split(":").map(Number);
    const total = h * 60 + m + delta;
    syncTimeDisplay(Math.floor(total / 60), total % 60);
}

// 직접 입력 처리
function onTimeDisplayInput(e) {
    document.getElementById("btn-now").classList.remove("active");
    const val = e.target.value;
    if (!/^\d{1,2}:\d{2}$/.test(val)) return;  // HH:MM 형식 아니면 무시
    const [h, m] = val.split(":").map(Number);
    if (isNaN(h) || isNaN(m) || m > 59) return;
    syncTimeDisplay(h, m);
}

// ── 그림자 레이어 ─────────────────────────────────────────────────────────────

let _shadowAbort = null;

async function loadShadowLayer(timeStr) {
    // 이전 요청 취소
    if (_shadowAbort) _shadowAbort.abort();
    _shadowAbort = new AbortController();

    // 기존 폴리곤 즉시 제거
    shadowPolygons.forEach(p => p.setMap(null));
    shadowPolygons = [];

    try {
        const res = await fetch(
            `${API_BASE}/api/shadow/${timeStr.replace(":", "-")}`,
            { signal: _shadowAbort.signal }
        );
        if (!res.ok) return;

        const geojson = await res.json();
        shadowPolygons = geojsonToPolygons(geojson);
    } catch (e) {
        if (e.name !== "AbortError") console.warn("[shadow]", e);
    }
}

function geojsonToPolygons(geojson) {
    const result = [];
    for (const feature of geojson.features) {
        const geom = feature.geometry;
        // Polygon: coordinates[0] = 외곽, MultiPolygon: coordinates[i][0]
        const rings = geom.type === "Polygon"
            ? [geom.coordinates[0]]
            : geom.coordinates.map(c => c[0]);

        for (const ring of rings) {
            const path = ring.map(([lng, lat]) => new kakao.maps.LatLng(lat, lng));
            result.push(new kakao.maps.Polygon({
                map,
                path,
                strokeWeight:  0,
                strokeColor:   "transparent",
                fillColor:     "#1a1a2e",
                fillOpacity:   0.35,
            }));
        }
    }
    return result;
}

// ── 검색 드롭다운 ─────────────────────────────────────────────────────────────

// 선택된 좌표 저장 { start: {name,lat,lng}, end: {name,lat,lng} }
const selected = { start: null, end: null };

function initSearchInput(inputId, dropdownId, key) {
    const input    = document.getElementById(inputId);
    const dropdown = document.getElementById(dropdownId);
    let debounceTimer = null;

    input.addEventListener("input", () => {
        selected[key] = null;  // 텍스트 바꾸면 선택 초기화
        clearTimeout(debounceTimer);
        const q = input.value.trim();
        if (!q) { dropdown.style.display = "none"; return; }
        debounceTimer = setTimeout(() => fetchSuggestions(q, input, dropdown, key), 300);
    });

    // 외부 클릭 시 드롭다운 닫기
    document.addEventListener("click", (e) => {
        if (!input.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.style.display = "none";
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
        showDropdown(results, input, dropdown, key);
    } catch (e) { /* 무시 */ }
}

function showDropdown(results, input, dropdown, key) {
    dropdown.innerHTML = "";
    if (!results.length) { dropdown.style.display = "none"; return; }

    results.forEach(r => {
        const li = document.createElement("li");
        li.innerHTML = `<div class="item-name">${r.name}</div><div class="item-addr">${r.address}</div>`;
        li.addEventListener("click", () => {
            selected[key] = r;
            input.value = r.name;
            dropdown.style.display = "none";
        });
        dropdown.appendChild(li);
    });
    dropdown.style.display = "block";
}

// ── 지오코딩 ──────────────────────────────────────────────────────────────────

async function geocode(query) {
    const res = await fetch(`${API_BASE}/api/geocode?query=${encodeURIComponent(query)}`);
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "장소를 찾을 수 없습니다.");
    }
    return res.json();
}

// ── 오버레이 헬퍼 ─────────────────────────────────────────────────────────────

function makeDotOverlay(lat, lng, color) {
    return new kakao.maps.CustomOverlay({
        position: new kakao.maps.LatLng(lat, lng),
        content:  `<div style="width:14px;height:14px;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);"></div>`,
        map,
        yAnchor: 0.5,
        xAnchor: 0.5,
    });
}

function showPopup(lat, lng, html) {
    if (openInfoWindow) openInfoWindow.setMap(null);
    openInfoWindow = new kakao.maps.InfoWindow({
        position: new kakao.maps.LatLng(lat, lng),
        content:  `<div style="padding:6px 10px;font-size:13px;white-space:nowrap;">${html}</div>`,
        removable: true,
    });
    openInfoWindow.open(map);
}

// ── 따릉이 마커 ───────────────────────────────────────────────────────────────

function renderBikeStations(stations) {
    bikeOverlays.forEach(o => o.setMap(null));
    bikeOverlays = [];

    const list = document.getElementById("ddareungi-list");
    list.innerHTML = "";

    stations.forEach(s => {
        const overlay = new kakao.maps.CustomOverlay({
            position: new kakao.maps.LatLng(s.lat, s.lng),
            content:  `<div class="bike-marker" onclick="showPopup(${s.lat},${s.lng},'<b>${s.name}</b><br>잔여: ${s.available}대')">${s.available}</div>`,
            map,
            yAnchor: 0.5,
            xAnchor: 0.5,
        });
        bikeOverlays.push(overlay);

        const li = document.createElement("li");
        li.textContent = `${s.name} — ${s.available}대`;
        list.appendChild(li);
    });

    document.getElementById("ddareungi-panel").classList.toggle("hidden", stations.length === 0);
}

// ── 신호등 마커 ───────────────────────────────────────────────────────────────

function renderSignals(signals) {
    signalOverlays.forEach(o => o.setMap(null));
    signalOverlays = [];

    signals.forEach(s => {
        const isRed  = s.red_remaining_sec > 0;
        const color  = isRed ? "#e53935" : "#43a047";
        const emoji  = isRed ? "🔴" : "🟢";
        const label  = isRed ? `🔴 적색 잔여: ${s.red_remaining_sec}초` : "🟢 보행 가능";
        const overlay = new kakao.maps.CustomOverlay({
            position: new kakao.maps.LatLng(s.lat, s.lng),
            content:  `<div style="width:22px;height:22px;border-radius:50%;background:${color};border:3px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;font-size:11px;cursor:pointer;" onclick="showPopup(${s.lat},${s.lng},'${label}')">${emoji}</div>`,
            map,
            yAnchor: 0.5,
            xAnchor: 0.5,
        });
        signalOverlays.push(overlay);
    });
}

// ── 메인 길찾기 ───────────────────────────────────────────────────────────────

async function findRoute() {
    const startQuery = document.getElementById("input-start").value.trim();
    const endQuery   = document.getElementById("input-end").value.trim();
    const timeStr    = document.getElementById("time-display").textContent;
    const mode       = document.querySelector('input[name="mode"]:checked').value;

    if (!startQuery || !endQuery) {
        setStatus("출발지와 도착지를 입력하세요.", "warn");
        return;
    }

    setStatus("장소 검색 중...", "loading");

    let startCoord, endCoord;
    try {
        [startCoord, endCoord] = await Promise.all([
            selected.start || geocode(startQuery),
            selected.end   || geocode(endQuery),
        ]);
    } catch (e) {
        setStatus(e.message, "error");
        return;
    }

    if (markerStart) markerStart.setMap(null);
    if (markerEnd)   markerEnd.setMap(null);
    markerStart = makeDotOverlay(startCoord.lat, startCoord.lng, "#4caf50");
    markerEnd   = makeDotOverlay(endCoord.lat,   endCoord.lng,   "#f44336");

    setStatus("경로 계산 중...", "loading");

    let data;
    try {
        const res = await fetch(`${API_BASE}/api/route`, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                start_lat: startCoord.lat,
                start_lng: startCoord.lng,
                end_lat:   endCoord.lat,
                end_lng:   endCoord.lng,
                time_str:  timeStr,
                mode,
            }),
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "서버 오류");
        }
        data = await res.json();
    } catch (e) {
        setStatus(`경로 오류: ${e.message}`, "error");
        return;
    }

    // 경로 폴리라인
    if (routePolyline) routePolyline.setMap(null);
    const path = data.route.map(c => new kakao.maps.LatLng(c.lat, c.lng));
    routePolyline = new kakao.maps.Polyline({
        map,
        path,
        strokeWeight:  5,
        strokeColor:   "#1565c0",
        strokeOpacity: 0.9,
        strokeStyle:   "shortdash",
    });

    // 지도 범위 맞추기
    const bounds = new kakao.maps.LatLngBounds();
    path.forEach(ll => bounds.extend(ll));
    map.setBounds(bounds);

    renderBikeStations(data.ddareungi_stations || []);
    renderSignals(data.signal_data || []);

    setStatus(`경로 완료 — ${path.length}개 노드`, "ok");
}

// ── 상태 메시지 ───────────────────────────────────────────────────────────────

function setStatus(msg, type = "") {
    const el = document.getElementById("status-msg");
    el.textContent = msg;
    el.className = type;
}

// ── 시작 ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", initApp);
