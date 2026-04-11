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
    SERVER[Backend<br>
