# 08. API 명세

- **API** = 화면(브라우저)이나 다른 프로그램이 서버에 데이터를 요청하는 주소. 요청·응답은 **JSON**(`{"키": 값}` 형태의 글자 데이터).
- 서버 주소: `http://127.0.0.1:5000`. 응답 예시는 모두 **실제 실행 결과**에서 발췌했습니다 (전체: `정리/부록/샘플_응답.json`).
- 오류 응답 형식: `{"error": "이유"}` + 상태 코드 — **400** 잘못된 요청, **404** 없음, **500** 서버 내부 오류.

## 한눈에

| 메서드 | 주소 | 내용 | 처리 함수 |
|---|---|---|---|
| GET | `/` | 대시보드 화면 (HTML) | `dashboard/__init__.py:89` `index` |
| POST | `/api/analyze` | 분석 실행 (본문 없으면 샘플 A → B) | `dashboard/__init__.py:96` `analyze` |
| GET | `/api/threats[?video=]` | 마지막 결과 / 영상 전환 | `dashboard/__init__.py:118` `threats` |
| GET | `/api/threats/<tracking_id>` | 표적 1건 + 소속 군집 | `dashboard/__init__.py:132` `threat_detail` |
| PATCH | `/api/clusters/<cluster_id>/tactic` | 군집 전술 지정·해제 | `dashboard/__init__.py:142` `set_tactic` |
| PATCH | `/api/threats/<tracking_id>/commander` | 지휘전차 지정·해제 | `dashboard/__init__.py:164` `set_commander` |
| GET | `/api/unknowns?limit=20` | 미확인 그룹 순위 | `dashboard/__init__.py:192` `unknowns` |
| GET | `/api/unknowns/<group_id>` | 미확인 그룹 상세 | `dashboard/__init__.py:200` `unknown_detail` |
| GET | `/unknowns` | 분석관 화면 (HTML) | `dashboard/__init__.py:211` `unknowns_page` |
| GET | `/report?stage=N` | 인쇄용 보고서 (HTML) | `dashboard/__init__.py:217` `report` |
| POST | `/api/threat/assess` | DB 엔진 군집 판정 | `threat_api.py:34` `assess` |
| PATCH | `/api/threat/cluster/<id>/tactic` | DB 엔진 전술 수정 | `threat_api.py:42` `tactic` |
| PATCH | `/api/threat/cluster/<id>/core-target` | DB 엔진 핵심표적 지정·해제 | `threat_api.py:48` `core_target` |
| GET | `/api/threat/tank/<tank_id>` | 기종 1개 위협도 행 | `threat_api.py:55` `tank` |
| GET | `/dictionary`, `/dictionary/<tank_id>` | 전차 사전 화면 (HTML) | `dictionary.py:223` `home`, `:478` `tank` |
| GET | `/db-check` | DB 연결 확인 | `app.py:19` `db_check` |

**아직 없는 API (TODO, 작업 지시 7장)**: `POST /api/unknowns/<group_id>/confirm`, `/merge`, `/dismiss` (확정·병합·기각).

---

## POST `/api/analyze` — 분석 실행

- **요청**: 본문 없음 → `static/mock_frames/mock_video_A_5f.json`, `mock_video_B_5f.json` 을 차례로 분석. 본문이 있으면 그 JSON 1건 (형식: `dashboard/threat/contract.md`).
```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:5000/api/analyze
```
- **처리**: 영상마다 `pipeline.analyze` → 모두 성공하면 `_attach`(crop 저장, Unknown 레지스트리 저장) → 영상별 상태 저장, 화면은 첫 영상.
- **응답 (발췌)**:
```json
{
 "video": "mock_video_A.mp4",
 "videos": ["mock_video_A.mp4", "mock_video_B.mp4"],
 "counts": {"total": 3, "tank": 2, "apc": 0, "artillery": 0, "infantry": 0, "new": 0},
 "alert": {"level": 3, "label": "지속 감시", "banner": false, "prev_level": null,
           "message": "C-1 소대급 2대 · 지휘통제 · 군집점수 88.9"},
 "source": {"video": "mock_video_A.mp4", "captured_at": "2026-10-18", "source": "MOCK",
            "observer": {"lat": 48.6, "lon": 38.0, "heading_deg": 90}, "frame_size": {"w": 1920, "h": 1080},
            "frame_image": "mock_frames/mock_video_A_000120.jpg", "frame_idx": 120},
 "clusters": [{"cluster_id": "C-1", "level": 3, "label": "지속 감시", "score": 88.9, "t_cluster": 88.9,
               "echelon": {"n": 2, "name": "소대", "weight": 1}, "tactic": 10, "tactic_name": "지휘통제",
               "tactic_source": "시스템 추정", "track_ids": ["Tank-01", "Tank-02", "UNK-001"],
               "reasons": ["소대급 2대 ×1", "군집점수 88.9 = 최고 위협도 88.9 × 1 → 3단계"]}],
 "targets": [
  {"tracking_id": "Tank-01", "rank": 3, "category": "전차", "status": "Known", "model": "T-90", "tank_id": "TANK_0230",
   "family": "T-90", "threat": 82.3, "threat_before_bonus": 82.3, "grade": "높음", "threat_source": "사전 T-90",
   "scores": {"firepower": 108.8, "mobility": 69.4, "protection": 83.7, "total": 92.0},
   "weights": {"firepower": 0.19, "mobility": 0.43, "protection": 0.37}, "tactic": 10, "tactic_name": "지휘통제",
   "is_commander": true, "commander_evidence": {"n": 5, "m": 5, "on": true, "override": null},
   "has_cope_cage": false, "parts": [{"cls": "antenna", "conf": 0.66, "bbox": {"x": 18.28, "y": 30.46, "w": 3.65, "h": 23.06}}],
   "bbox": {"x": 8.39, "y": 47.22, "w": 22.71, "h": 25.65}, "confidence": 0.81, "n_frames": 5,
   "position": {"bearing_deg": 71.8, "distance_m": 780, "lat": 48.602182, "lon": 38.010064, "estimated": true},
   "crop_url": "/static/track_crops/mock_video_A.mp4/Tank-01_124.jpg", "unknown_group_id": null,
   "level": 3, "label": "지속 감시",
   "tags": ["안테나 탐지 5/5프레임 → 지휘전차 추정", "강점 화력 108.8", "약점 기동력 69.4", "지휘통제 가중치", "C-1 소속"]},
  "… (UNK-001, Tank-02 생략)"
 ]
}
```
- **오류**

| 경우 | 코드 | 응답 |
|---|---|---|
| v1 본문에 관측 위치 없음 `{"source": {}, "detections": []}` | 400 | `source.observer.lat/lon 필요` |
| v2 본문의 탐지에 tracking_id·분류·박스가 없거나 신뢰도가 0~1 밖 | 400 | 예: `UNK-001: det_confidence 는 0~1 숫자 또는 null` |
| v2 본문에 `source` 가 아예 없음 `{"frames": []}` | **500** | (빈 응답) — **발견한 문제**, 400 이어야 함 (12번 문서) |

## GET `/api/threats[?video=이름]` — 마지막 결과 / 영상 전환

- 요청: `GET /api/threats?video=mock_video_B.mp4` → 그 영상으로 전환하고 결과를 돌려줌 (응답 형식은 `/api/analyze` 와 같음).
- 오류: 분석 전 → 404 `분석 결과 없음. POST /api/analyze 먼저 실행` (화면은 이때 자동으로 분석 요청), 분석하지 않은 영상 → 404 `분석한 적 없는 영상: X`.

## GET `/api/threats/<tracking_id>` — 표적 1건

- 요청: `GET /api/threats/UNK-007` (영상 B 화면일 때)
- 응답 (발췌):
```json
{"target": {"tracking_id": "UNK-007", "status": "Unknown", "threat": 99.5, "threat_before_bonus": 97.8,
            "threat_source": "T-80 계열 상위25%", "unknown_group_id": "UNK-G0001",
            "crop_url": "/static/track_crops/mock_video_B.mp4/UNK-007_124.jpg",
            "tags": ["T-80 계열 상위25%", "cope cage → 방호 ×1.10", "미확인 · 분석관 검토", "C-1 소속"]},
 "cluster": {"cluster_id": "C-1", "level": 3, "score": 99.5, "tactic_name": "기동·직접전투",
             "echelon": {"n": 1, "name": "소대", "weight": 1}, "track_ids": ["Tank-11", "UNK-007"]}}
```
- 오류: 없는 표적 → 404 `표적 없음: NOPE`

## PATCH `/api/clusters/<cluster_id>/tactic` — 전술 선택

- 요청: `{"tactic": 3}` (1~10) 또는 `{"tactic": null}` (자동으로 되돌림)
```powershell
Invoke-RestMethod -Method Patch http://127.0.0.1:5000/api/clusters/C-1/tactic -ContentType application/json -Body '{"tactic": 3}'
```
- 응답: 다시 계산한 전체 결과. 예 (영상 A, ③대전차 지정): 군집 `tactic_source: "지휘관 지정"`, S = 94.1, 위협도 Tank-02 94.1 · UNK-001 91.8 · Tank-01 89.2 (지휘전차도 지정 전술을 따름).
- 오류: `{"tactic": 11}` → 400 `가중치 없는 전술 번호: 11 (1~10만 가능)`, `{"tactic": "x"}` → 400 `tactic 은 1~10 정수 또는 null`, 없는 군집 → 404 `군집 없음: NOPE`

## PATCH `/api/threats/<tracking_id>/commander` — 지휘전차 지정·해제

- 요청: `{"is_commander": false}` (해제), `true` (지정), `null` (탐지 규칙으로 되돌림)
- 응답 예 (Tank-01 해제): 군집 전술이 ⑩지휘통제 → ①기동·직접전투로 바뀌고, Tank-01 태그 첫 줄이 "지휘전차 해제 (지휘관)". 위협도 UNK-001 94.8 · Tank-02 94.4 · Tank-01 90.0.
- 오류: `{"is_commander": "yes"}` → 400 `is_commander 는 true, false, null`, 없는 표적 → 404 `표적 없음: NOPE`, v1 입력 → 400 `지휘전차 수정은 프레임 단위(v2) 입력에서만`

## GET `/api/unknowns?limit=20` — 미확인 그룹 순위

- `limit` 은 1~200 으로 제한. 대상: status = open 이고 최고 위협도 ≥ 40.
- 응답:
```json
{"groups": [{"rank": 1, "group_id": "UNK-G0001", "status": "open", "family_guess": "T-90", "type_group": "주력전차",
             "max_threat": 99.5, "threat_source": "T-80 계열 상위25%", "n_tracks": 2, "n_videos": 2,
             "priority": 277.5, "has_cope_cage": true, "commander_seen": false, "review_candidates": [],
             "first_seen": "2026-10-18 00:00:00", "last_seen": "2026-10-18 00:00:00",
             "cover": "unknown_crops/UNK-G0001/mock_video_B.mp4_UNK-007_124.jpg",
             "url": "/static/unknown_crops/UNK-G0001/mock_video_B.mp4_UNK-007_124.jpg"}]}
```

## GET `/api/unknowns/<group_id>` — 미확인 그룹 상세

- 응답 (발췌):
```json
{"group": {"group_id": "UNK-G0001", "n_tracks": 2, "n_videos": 2, "max_threat": 99.5, "priority": 277.5, "…": "…"},
 "sightings": [
   {"id": 1, "video": "mock_video_A.mp4", "tracking_id": "UNK-001", "cluster_id": "C-1", "similarity": null,
    "threat": 88.9, "lat": 48.597343, "lon": 38.012528, "captured_at": "2026-10-18 00:00:00"},
   {"id": 2, "video": "mock_video_B.mp4", "tracking_id": "UNK-007", "cluster_id": "C-1", "similarity": 0.9646,
    "threat": 99.5, "lat": 48.599009, "lon": 38.011409, "captured_at": "2026-10-18 00:00:00"}],
 "crops": [
   {"video": "mock_video_B.mp4", "tracking_id": "UNK-007", "frame_idx": 124, "quality": 0.06239,
    "path": "unknown_crops/UNK-G0001/mock_video_B.mp4_UNK-007_124.jpg",
    "url": "/static/unknown_crops/UNK-G0001/mock_video_B.mp4_UNK-007_124.jpg"},
   "… (6장)"]}
```
- 오류: 없는 그룹 → 404 `그룹 없음: UNK-G9999`

## GET `/report?stage=N` — 보고서

- `stage` 가 1~4 면 "지휘관 결정 N단계"를 함께 표시 (화면의 '단계 조정' 값). 숫자가 아니거나 범위 밖이면 무시.
- 응답: 인쇄용 HTML (`dashboard/templates/dashboard/report.html`). 캡처: `정리/그림/화면_5_보고서.png`. 분석 전이면 404.

## DB 엔진 `/api/threat/*` (`threat_api.py`)

화면 없이 다른 프로그램이 쓰는 API 입니다. 입력 형식은 `response_level.py:14~19` (10번 문서 `response_level.md`).

| 주소 | 요청 | 응답·오류 |
|---|---|---|
| POST `/api/threat/assess` | `{"cluster_id": "C-001", "system_tactic": 1, "vehicles": [...], "frames": [...]}` | 판정 결과 (level, S, T_cluster, E, N, vehicles …). cluster_id 없음·JSON 객체 아님 → 400 |
| PATCH `/api/threat/cluster/<id>/tactic` | `{"tactic": 4}` 또는 null | 재판정 결과. 판정 기록 없는 군집 → 404, 잘못된 번호 → 400 |
| PATCH `/api/threat/cluster/<id>/core-target` | `{"track_id": "trk-3", "remove": false}` | 재판정 결과. 군집에 없는 track_id → 400 |
| GET `/api/threat/tank/<tank_id>` | — | `tank_threat` 1행. 없으면 404 `전차 ID 없음` |

> 이 엔진의 결과는 대시보드 화면에 나오지 않습니다(v2 연결 어댑터 TODO).
