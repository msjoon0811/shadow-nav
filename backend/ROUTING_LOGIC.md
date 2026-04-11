# Shadow-Nav 라우팅 로직 설명

## 전체 흐름

```
프론트 요청
  → [카카오 모빌리티 API] 기본 경로 좌표 획득
  → [공공 API 병렬 호출] 신호등 잔여시간 + 따릉이 대여소
  → [route_model.py] 그래프 구축 → 가중치 계산 → A* 탐색
  → 최적 경로 + 따릉이 정보 반환
```

---

## 1. 카카오 경로로 탐색 범위 결정

카카오 API에서 받은 경로 좌표의 bbox(bounding box)에 **330m 여유**를 추가해
OSMnx로 도로망 그래프를 다운로드한다.

카카오 경로 자체를 결과로 쓰지 않는다. 탐색 영역을 정하는 기준점으로만 사용한다.

---

## 2. 가중치 계산 (엣지별 3단계)

각 도로 엣지(골목길 선분)의 `shadow_weight`는 아래 3단계를 순서대로 거쳐 결정된다.

### 2-1. 기본 이동시간 (`assign_basic_time_weights`)

```
travel_time(분) = 도로 길이(m) / (속도 m/min)
```

| 모드 | 속도 | 효과 |
|---|---|---|
| 보행 | 4 km/h | 기준값 |
| 자전거 | 15 km/h | travel_time이 ~3.75배 작아짐 → 전체 가중치 낮아짐 |

### 2-2. 그늘 가중치 (`apply_shadow_weights`)

```
shadow_weight = travel_time × (1.0 - shadow_coverage × 0.8)
```

- `shadow_coverage`: 해당 도로가 그림자 폴리곤(GeoJSON)과 겹치는 비율 (0.0 ~ 1.0)
- 그림자 데이터는 V-World 3D 건물 + 태양 위치 기반으로 사전 계산된 5분 단위 GeoJSON (`shadow_0801_HHMM.geojson`)
- 요청 시간에서 **가장 가까운 5분 단위**로 반올림해 파일 로드

| 상황 | shadow_coverage | shadow_weight |
|---|---|---|
| 완전 그늘 | 1.0 | travel_time × 0.2 (80% 감소) |
| 절반 그늘 | 0.5 | travel_time × 0.6 (40% 감소) |
| 완전 땡볕 | 0.0 | travel_time × 1.0 (감소 없음) |

→ A*가 그늘진 도로를 선호하게 된다.

### 2-3. 신호등 패널티 (`apply_signal_penalties`)

```
shadow_weight += red_remaining_sec × 0.05
```

- 엣지 중점 기준 **반경 ~22m 이내** 교차로 신호만 적용
- 빨간불 30초 잔여 → +1.5 패널티 (보행 기준 약 150m 우회를 감수할 만큼)
- 신호등 API 미설정 시 패널티 없이 그대로 진행

---

## 3. A* 탐색

```python
shadow_weight = travel_time × (1.0 - shadow_coverage × 0.8) + signal_penalty
```

위 가중치 기준으로 **A\*** 알고리즘 실행.

**휴리스틱**: 현재 노드 → 목적지 직선거리(위경도 유클리드 근사, 미터 단위)

```python
h(u) = hypot(Δx, Δy) × 111_000
```

- 위도 1° ≈ 111km로 환산해 `shadow_weight` 단위(분/미터 기반)와 스케일 맞춤
- Dijkstra 대비 목적지 방향으로 탐색을 집중해 속도 향상

---

## 4. Fallback

그래프 다운로드 실패, 경로 없음 등 예외 발생 시 카카오 원본 경로를 그대로 반환한다.
서버가 죽지 않고 항상 경로를 돌려준다.

---

## 파일 구조 요약

```
backend/
  app.py          - FastAPI 서버, 카카오/신호등/따릉이 API 호출
  route_model.py  - 그래프 구축 + 가중치 계산 + A* 탐색
  .env            - API 키 (KAKAO / SIGNAL / DDAREUNGI)

data/
  shadow_data/
    shadow_0801_0900.geojson   ~ shadow_0801_1800.geojson  (5분 단위, 109장)
```

## API 키 설정

`.env` 파일에 아래 3개를 채우면 모든 기능이 활성화된다.

```
KAKAO_REST_API_KEY=...    # 카카오 개발자 콘솔
SIGNAL_API_KEY=...        # data.go.kr → 교통안전 신호등 실시간 정보
DDAREUNGI_API_KEY=...     # data.seoul.go.kr → 따릉이 실시간 대여소
```

신호등/따릉이 키가 없어도 그늘 기반 라우팅은 정상 동작한다.
