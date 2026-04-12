# Shadow-Nav (그늘길 내비게이션)

2026년 전국 통합데이터 활용 공모전 출품작

폭염 시 보행자·자전거 이용자에게 그늘진 최적 경로와 신호등·공영자전거 정보를 실시간으로 제공하는 웹 내비게이션입니다.

---

## 기술 스택

| 영역 | 기술 |
| :--- | :--- |
| Frontend | HTML5, CSS, Vanilla JS, 카카오맵 JS API |
| Backend | Python, FastAPI, httpx |
| Data/Model | OSMnx, NetworkX (A*), GeoPandas, Shapely, Scikit-learn (K-Means) |

---

## 외부 API 및 데이터

각자 담당 API 홈페이지에서 API Key를 발급받아 `.env` 파일에 넣어주세요.

### 1. 정적 데이터 (`data/` 폴더)
| 데이터명 | 출처 | 활용 목적 |
| :--- | :--- | :--- |
| V-World 3D 건물 통합정보 | 국토교통부 | 시간대별 그림자 GeoJSON 생성용 건물 데이터 |

### 2. 런타임 동적 데이터
| 데이터명 | 출처 | 활용 목적 |
| :--- | :--- | :--- |
| 보행자/자전거 도로망 그래프 | OSMnx (OpenStreetMap) | 길찾기 요청 시 bbox 기준 다운로드, A* 라우팅 그래프 구성 |

### 3. 프론트엔드 호출 API
| API 이름 | 출처 | 활용 목적 |
| :--- | :--- | :--- |
| 카카오맵 JS API | Kakao Developers | 지도 표시, 그늘 폴리곤, 경로 Polyline 렌더링 |
| 카카오 Local API | Kakao Developers | 장소명 → 위경도 변환 |

### 4. 백엔드 실시간 호출 API
| API 이름 | 출처 | 활용 목적 |
| :--- | :--- | :--- |
| 교통안전 신호등 실시간 정보 | 공공데이터포털 | 횡단보도 빨간불 대기시간을 라우팅 패널티에 반영 |
| 전국 공영자전거 실시간 정보 | 공공데이터포털 | 경로 근처 대여소 위치 및 잔여 대수 표시 |

---

## 시스템 구조

```mermaid
graph TD
    classDef frontend fill:#3498db,stroke:#2980b9,color:#fff;
    classDef api fill:#e67e22,stroke:#d35400,color:#fff;
    classDef backend fill:#2c3e50,stroke:#1a252f,color:#fff;
    classDef model fill:#2ecc71,stroke:#27ae60,color:#fff;
    classDef data fill:#9b59b6,stroke:#8e44ad,color:#fff;

    UI[Frontend<br>카카오맵 + UI]:::frontend
    SERVER[Backend<br>FastAPI]:::backend
    MODEL[Data/Model<br>AI 쾌적도 분류 및 A* 라우팅]:::model
    DB[(data/ 폴더<br>그림자 GeoJSON 109장)]:::data
    PUB((공공 API<br>전국 통합데이터 API)):::api
    KAKAO((카카오 API<br>장소 텍스트 검색)):::api

    UI -- 1. 장소 검색 요청 --> KAKAO
    UI -- 2. 위경도 기준 길찾기 요청 --> SERVER
    SERVER -- 3. 실시간 신호등 조회 --> PUB
    PUB -- 응답 결과 --> SERVER
    SERVER -- 4. 기상 정보 종합 전달 --> MODEL
    DB -. 5. 그늘 가중치 연산 .-> MODEL
    MODEL -- 6. A* 탐색 완료 (Polyline 리턴) --> SERVER
    SERVER -- 7. JSON 응답 --> UI
    DB -. 8. 시간별 그림자 맵 로딩 .-> UI
```

---

## 라우팅 로직

1. 카카오 모빌리티 API로 기본 반경(Bbox) 파악 및 위치 설정
2. OSMnx로 해당 Bbox의 보행 도로망 그래프 다운로드
3. 시간대별 GeoJSON(109장)으로 각 도로 엣지의 그림자 덮힘 비율 계산 → shadow_weight 부여
4. K-Means 쾌적도 등급 분류: 엣지별 피처(그림자비율, 직사광선노출거리, 보도여부)를 정규화 후 Silhouette Score 기반 최적 K 자동 선택, 등급별 배율 반영
5. 횡단보도 제약: Shapely 교차 분석으로 차도 라인 감지 및 무단횡단 패널티 적용
6. 실시간 신호 패널티: 빨간불 잔여시간을 엣지 가중치에 반영
7. A* 탐색: Haversine 휴리스틱으로 그늘 + 쾌적도 + 신호 복합 최적 경로 탐색

---

## 실행 방법

**환경 변수 (`backend/.env` 파일 생성 필수)**
```env
KAKAO_REST_API_KEY=발급받은키
KAKAO_JS_API_KEY=발급받은키
SIGNAL_API_KEY=신호등API키
BIKE_API_KEY=공영자전거API키
```
*(카카오 콘솔 Web 플랫폼 도메인 설정에 `http://localhost:3000` 등록을 잊지 마세요!)*

**실행 명령어 (로컬 테스트용)**
```bash
# 1. 백엔드 서버 가동 (FastAPI)
cd backend
python -m uvicorn app:app --reload --port 8000

# 2. 프론트엔드 가동 (새 터미널 열기)
cd frontend
python -m http.server 3000
```
웹 브라우저에서 `http://localhost:3000` 으로 접속하시면 UI를 띄워볼 수 있습니다.
