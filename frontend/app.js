// Shadow-Nav 프론트엔드 메인 로직

const API_BASE = "http://localhost:8000";

// ── 지도 초기화 ───────────────────────────────────────────────────────────────

const map = L.map("map").setView([37.5045, 127.0248], 16);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap contributors",
    maxZoom: 19,
}).addTo(map);

// 레이어 관리
let routeLayer    = null;   // 경로 폴리라인
let shadowLayer   = null;   // 그림자 GeoJSON 오버레이
let markerStart   = null;
let markerEnd     = null;
let bikeMarkers   = [];

// ── 시간 상태 ─────────────────────────────────────────────────────────────────

// 현재 시각을 5분 단위로 반올림해서 초기값 설정
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

// 시간 표시 동기화
function syncTimeDisplay(h, m) {
    const { h: ch, m: cm } = clampTime(h, m);
    document.getElementById("time-display").textContent = formatTime(ch, cm);
    document.getElementById("time-picker").value = formatTime(ch, cm);
    loadShadowLayer(formatTime(ch, cm));
}

// 현재 시각으로 설정
function setNow() {
    const { h, m } = roundToFive(new Date());
    syncTimeDisplay(h, m);
    document.getElementById("btn-now").classList.add("active");
}

// ±5분 조절
function adjustTime(delta) {
    document.getElementById("btn-now").classList.remove("active");
    const val = document.getElementById("time-picker").value || "12:00";
    const [h, m] = val.split(":").map(Number);
    const total = h * 60 + m + delta;
    syncTimeDisplay(Math.floor(total / 60), total % 60);
}

// 직접 picker로 변경
document.addEventListener("DOMContentLoaded", () => {
    // 초기 시각 설정
    setNow();

    document.getElementById("time-picker").addEventListener("change", (e) => {
        document.getElementById("btn-now").classList.remove("active");
        const [h, m] = e.target.value.split(":").map(Number);
        syncTimeDisplay(h, m);
    });
});

// ── 그림자 레이어 ─────────────────────────────────────────────────────────────

async function loadShadowLayer(timeStr) {
    if (shadowLayer) {
        map.removeLayer(shadowLayer);
        shadowLayer = null;
    }

    try {
        const res = await fetch(`${API_BASE}/api/shadow/${timeStr.replace(":", "-")}`);
        if (!res.ok) return;  // 해당 시간대 파일 없으면 그냥 스킵

        const geojson = await res.json();
        shadowLayer = L.geoJSON(geojson, {
            style: {
                fillColor:   "#1a1a2e",
                fillOpacity: 0.35,
                color:       "transparent",
                weight:      0,
            },
        }).addTo(map);
    } catch (e) {
        // 서버 꺼져 있거나 파일 없으면 무시
    }
}

// ── 지오코딩 ──────────────────────────────────────────────────────────────────

async function geocode(query) {
    const res = await fetch(`${API_BASE}/api/geocode?query=${encodeURIComponent(query)}`);
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "장소를 찾을 수 없습니다.");
    }
    return res.json();  // { name, lat, lng }
}

// ── 마커 헬퍼 ─────────────────────────────────────────────────────────────────

function makeIcon(color) {
    return L.divIcon({
        className: "",
        html: `<div style="
            width:14px;height:14px;border-radius:50%;
            background:${color};border:2px solid #fff;
            box-shadow:0 1px 4px rgba(0,0,0,.4);
        "></div>`,
        iconAnchor: [7, 7],
    });
}

// ── 따릉이 마커 ───────────────────────────────────────────────────────────────

function renderBikeStations(stations) {
    bikeMarkers.forEach(m => map.removeLayer(m));
    bikeMarkers = [];

    const list = document.getElementById("ddareungi-list");
    list.innerHTML = "";

    stations.forEach(s => {
        const icon = L.divIcon({
            className: "",
            html: `<div class="bike-marker">${s.available}</div>`,
            iconAnchor: [16, 16],
        });
        const m = L.marker([s.lat, s.lng], { icon })
            .bindPopup(`<b>${s.name}</b><br>잔여 자전거: ${s.available}대`)
            .addTo(map);
        bikeMarkers.push(m);

        const li = document.createElement("li");
        li.textContent = `${s.name} — ${s.available}대`;
        list.appendChild(li);
    });

    const panel = document.getElementById("ddareungi-panel");
    panel.classList.toggle("hidden", stations.length === 0);
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
        [startCoord, endCoord] = await Promise.all([geocode(startQuery), geocode(endQuery)]);
    } catch (e) {
        setStatus(e.message, "error");
        return;
    }

    // 마커 갱신
    if (markerStart) map.removeLayer(markerStart);
    if (markerEnd)   map.removeLayer(markerEnd);
    markerStart = L.marker([startCoord.lat, startCoord.lng], { icon: makeIcon("#4caf50") })
        .bindPopup(startCoord.name).addTo(map);
    markerEnd   = L.marker([endCoord.lat, endCoord.lng],   { icon: makeIcon("#f44336") })
        .bindPopup(endCoord.name).addTo(map);

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

    // 경로 그리기
    if (routeLayer) map.removeLayer(routeLayer);
    const latlngs = data.route.map(c => [c.lat, c.lng]);
    routeLayer = L.polyline(latlngs, {
        color:     "#2196f3",
        weight:    5,
        opacity:   0.85,
        lineJoin:  "round",
    }).addTo(map);
    map.fitBounds(routeLayer.getBounds(), { padding: [40, 40] });

    // 따릉이 대여소
    renderBikeStations(data.ddareungi_stations || []);

    setStatus(`경로 완료 — ${latlngs.length}개 노드`, "ok");
}

// ── 상태 메시지 ───────────────────────────────────────────────────────────────

function setStatus(msg, type = "") {
    const el = document.getElementById("status-msg");
    el.textContent = msg;
    el.className = type;
}
