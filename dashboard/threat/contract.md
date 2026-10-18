# 탐지 결과 계약 (모델 → 대시보드)

탐지 모델(YOLO26 + DINO)이 이 형식의 JSON을 `POST /api/analyze` 본문으로 보내면 대시보드가 바로 계산합니다.
본문을 비우면 `static/mock_frames/mock_video_A_5f.json` → `mock_video_B_5f.json` 샘플을 차례로 분석합니다.

## 형식 (v2, 프레임 단위)

```json
{
  "source": {"video": "ukraine_tank_001.mp4", "captured_at": "2024-03-15", "source": "OSINT",
             "observer": {"lat": 48.6, "lon": 38.0, "heading_deg": 90},
             "frame_size": {"w": 1920, "h": 1080}},
  "frames": [
    {"frame_idx": 120, "t_sec": 4.0, "image_path": "frames/ukraine_tank_001/000120.jpg",
     "parts": [],
     "detections": [
       {"tracking_id": "Tank-03", "category": "전차", "det_confidence": 0.93,
        "bbox_px": {"x": 900, "y": 320, "w": 260, "h": 210},
        "cluster_id": "C-1",
        "parts": [{"cls": "antenna", "conf": 0.71, "bbox_px": {"x": 950, "y": 250, "w": 20, "h": 90}},
                  {"cls": "cope_cage", "conf": 0.66, "bbox_px": {"x": 960, "y": 300, "w": 140, "h": 60}}],
        "classification": {
          "model": "dino-v2", "level": "tank_id",
          "top_k": [{"label": "TANK_0216", "family": "T-72", "score": 0.81},
                    {"label": "TANK_0214", "family": "T-72", "score": 0.09}],
          "embedding": [0.012, -0.03, "..."]}}
     ]}
  ]
}
```

| 필드 | 필수 | 설명 |
|---|---|---|
| `source.observer.lat/lon` | 예 | 관측(카메라) 위치. 표적 위치 추정의 기준 |
| `source.frame_size.w/h` | 예 | 픽셀 → 화면 % 변환 |
| `frames[].frame_idx` | 예 | 프레임 번호 |
| `frames[].image_path` | 아니오 | `static/` 기준 원본 프레임 경로. 있으면 화면에 띄우고 crop 을 자름. `static` 밖 경로는 읽지 않음 |
| `frames[].parts` | 아니오 | 전차와 따로 출력된 부품. IoA ≥ `PART_IOA_MIN` 인 전차에 붙임 |
| `detections[].tracking_id` | 예 | 영상 안에서 같은 개체는 같은 ID (트래커 결과) |
| `detections[].category` | 예 | 전차 · 기갑차 · 포병 · 인원 · 미확인 |
| `detections[].bbox_px` | 예* | 픽셀 좌표. *기존 `bbox`(%) 도 허용 (하위 호환) |
| `detections[].det_confidence` | 아니오 | 0~1. 트랙 평균·crop 품질에 씀 |
| `detections[].parts[]` | 아니오 | `cls` = `antenna` / `cope_cage`, `conf` 0~1 |
| `classification.top_k[]` | 아니오 | `label` = 사전 `tank_id` 또는 `family_name` (`label_map.json` 으로 변환). `family` 는 참고용 |
| `classification.embedding` | 아니오 | DINO L2 정규화 벡터. 없으면 Unknown 레지스트리 매칭을 건너뜀 |

기존 v1 형식(`detections` 평면 리스트, `bbox` %, `model` 기종명)도 그대로 받습니다 (`mock_detections.json`).

## 처리 순서

1. `track.aggregate`: 프레임 → 트랙. 안테나·cope cage 비율 규칙, top_k 가중 평균, 임베딩 평균, 대표 crop 선정
2. `judge.judge`: Known / Known_Variant / Unknown
3. `judge.threat_of`: 사전 DB 위협도 + cope cage 보정 (보정 전 값도 응답에 넣음)
4. `pipeline.analyze`: 군집 대응단계·랭킹 (기존 로직)
5. `dashboard/__init__.py`: 대표 crop 저장, Unknown 은 `unknown_registry.record`

## 가정 (모델 팀 확인 필요)

| 항목 | 가정 | 확인할 것 |
|---|---|---|
| 분류 라벨 단위 | `tank_id` 단위 (샘플 `level: "tank_id"`). 계열 라벨도 `label_map.json` 에 넣으면 받음 | DINO 클래스 목록 → `label_map.json` |
| 임베딩 | 차원 무관, 트랙 안에서는 같은 차원. L2 정규화 | 실제 차원, 같은 기종 유사도 분포 (`GROUP_SIM_MIN` 0.85 보정) |
| 트래커 | YOLO 쪽 트래커가 영상 안에서 같은 개체에 같은 `tracking_id` 를 붙임 | 트래커 종류, ID 가 끊길 때 재사용 여부 |
| 부품 | 부품이 전차 탐지 안에 들어오거나(`parts`), 프레임의 `parts` 로 따로 옴 | 출력 방식 |
| 원본 프레임 | `image_path` 의 파일이 Flask `static/` 아래에 있음 | 저장 위치 (다른 곳이면 경로 규칙 추가) |
| `cluster_id` | 모델(또는 전처리)이 붙여 줌. 없으면 C-1 | 군집화 담당 |
| `captured_at` | `YYYY-MM-DD` 또는 `YYYY-MM-DD HH:MM:SS`. 못 읽으면 분석 시각 | |

## 샘플 라벨과 사전 불일치 (사전을 우선함)

| 라벨 | 샘플 JSON family | 사전 family (canonical_name) |
|---|---|---|
| TANK_0230 | T-72 | T-90 (T-90) |
| TANK_0222 | T-72 | T-80 (T-80) |

그 밖에 샘플 라벨(TANK_0216·0220·0221 → T-72, TANK_0231 → T-90, TANK_0226 → T-80)은 사전과 같습니다.
