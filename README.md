# Shadow-Nav (그늘길 내비게이션)

2026년 전국 통합데이터 활용 공모전 출품작

폭염 및 기후위기 심화에 대응하여, 보행자와 자전거 이용자에게 **가장 시원한(그늘진) 최적 경로**와 **공공 교통 인프라 정보(신호등, 자전거)**를 실시간 융합 제공하는 스마트 웹 내비게이션 프로토타입입니다.

---

## 🛠️ 기술 스택

| 영역 | 기술 |
| :--- | :--- |
| **Frontend (웹 UI & 지도)** | HTML5, CSS, Vanilla JS, 카카오맵 JS API |
| **Backend (API & 서버)** | Python, FastAPI, httpx |
| **Data & Model (라우팅 알고리즘)** | OSMnx, NetworkX (A*), GeoPandas, Shapely, Scikit-learn (초정밀 AI) |

---

## 💾 외부 API 및 데이터 명세서

팀원들은 각자 담당하는 API의 공식 홈페이지에 가입하여 API Key를 발급받아 `.env` 파일에 연동 바랍니다.

### 1. 정적 데이터 (`data/` 폴더)
| 데이터명 | 출처 | 활용 목적 |
| :--- | :--- | :--- |
| **V-World 3D 건물 통합정보** | 국토교통부 | 시간대별 109장 그림자 GeoJSON 생성용 건물 베이스 데이터 |
| **보행자/자전거 도로망 그래프** | OSMnx | 최적 경로 라우팅이 돌아갈 1,232개 골목길(Edge) 및 교차로(Node) 좌표망 |

### 2. 프론트엔드 호출 API (팀원 A 담당)
| API 이름 | 출처 | 활용 목적 |
| :--- | :--- | :--- |
| **카카오맵 JS API** | Kakao Developers | 브라우저에 지도를 띄우고 그늘 폴리곤, 최적 경로(Polyline), 애니메이션 표시 |
| **카카오 Local API** | Kakao Developers | 텍스트 장소명 검색 시 위도/경도(X,Y) 변환 |

### 3. 백엔드 실시간 호출 API (팀원 C 담당)
| API 이름 | 출처 | 활용 목적 |
| :--- | :--- | :--- |
| **교통안전 신호등 실시간 정보** | 공공데이터포털 | 경로상 교차로 횡단보도의 빨간불 잔여 대기시간(초)을 라우팅 패널티에 반영 |
| **전국 공영자전거 실시간 정보** | 공공데이터포털 | 자전거 모드 선택 시 경로상 가장 가까운 대여소와 실시간 잔여 대수 파악 |

---

## ⚙️ 시스템 구조 (System Architecture)

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

## 🧭 핵심 라우팅 로직

1. 카카오 모빌리티 API로 기본 반경(Bbox) 파악 및 위치 설정
2. 시간대별 데이터베이스(109장의 GeoJSON)를 이용해 특정 시간의 골목길 그림자 덮힘 비율 정밀 계산
3. **머신러닝(K-Means):** 도로별 그림자 비율, 거리 등을 바탕으로 쾌적지수 모델 자동 3단계 분류
4. **횡단보도 정밀 제약:** Shapely 교차 분석으로 실제 차도 라인 감지 및 무단횡단 패널티 적용
5. **A* 라우팅 탐색 가동:** 쾌적지수 등급(가중치 패널티)을 바탕으로 시간 대비 가장 시원한 목적 기반 우회로 탐색

---

## 💻 서버 실행 방법 및 환경 설정 (Usage)

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
