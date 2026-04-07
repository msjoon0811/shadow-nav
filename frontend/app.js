// [팀원 A] 웹 프론트엔드 메인 로직

// 1. 지도 초기화 (신논현역 중심)
const map = L.map('map').setView([37.5045, 127.0248], 15);

// 2. 배경 지도 (오픈스트리트맵) 로딩
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors'
}).addTo(map);

console.log("지도 세팅 완료! 이제 백엔드 API와 그림자 파일을 연결해보세요.");

// 3. (개발 목표) 시간 슬라이더를 움직이면 shadow_data/ 안의 geojson을 불러와서 지도에 그리는 함수 만들기
// 4. (개발 목표) 길찾기 버튼을 누르면 백엔드에 요청을 보내고, 받아온 경로 선(Path)을 지도에 파란색으로 그리기
