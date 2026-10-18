# 위협도 대시보드 (`dashboard/`)

위협도 대시보드(`http://127.0.0.1:5000/`)에 필요한 코드가 모두 이 폴더 안에 있습니다. 계산, API, 화면, 보고서, 테스트가 함께 들어 있습니다.
모든 파일에 줄 단위 한국어 주석을 달아 두었습니다. 여기서 고치면 바로 반영됩니다(복사본이 아닙니다).

## 폴더 구조

```
dashboard/
├── README.md                      # 이 문서
├── __init__.py                    # Flask 블루프린트: 화면·API·보고서 라우트, 서버 메모리 상태(STATE)
├── threat/                        # 위협도 계산 (Flask 와 무관한 순수 계산)
│   ├── config.py                  # ★ 숫자는 전부 여기: 전술 가중치 1~10, 위협도 단계 구간, 제대, 75/150/225, 하한 75
│   ├── core.py                    # 단계별 계산 함수 (제대 → 전술 → 정량 점수 → 전차 위협도 → 위협도 단계 → 군집 대응단계)
│   ├── pipeline.py                # 탐지 결과 → 화면용 JSON 조립 (근거 태그, 랭킹, 카운터, 경보, 추정 위치). 응답 형식은 파일 머리말
│   ├── tank_specs.json            # 기종 제원 샘플 4종 (M1A1 = 기준 100). 값은 TODO
│   └── mock_detections.json       # 이미지 분석 모델 대신 쓰는 탐지 결과 12건
├── templates/dashboard/
│   ├── index.html                 # 대시보드 화면 뼈대 (값은 JS 가 채움)
│   └── report.html                # 보고서 출력 (인쇄용)
├── static/
│   ├── dashboard.js               # 화면 동작: API 호출, 표·박스·패널·지도 그리기, 단계 조정·전술 선택·보고서 버튼
│   └── dashboard.css              # 대시보드 전용 스타일 (색상 변수는 ../static/style.css)
└── tests/test_threat.py           # 계산·API 테스트
```

바깥 폴더에서 이 대시보드가 쓰는 파일은 세 개뿐입니다.
- `app.py`: 블루프린트를 등록합니다.
- `templates/_nav.html`: 공통 상단 바입니다.
- `static/style.css`: 색상 변수와 상단 바 스타일입니다.

## 흐름

```
mock_detections.json ─(또는 POST 본문)─▶ __init__.py analyze()
    └─▶ threat/pipeline.py analyze()
          군집마다: core.infer_tactic (전술)  ← 지휘관이 '전술 선택'으로 지정하면 그 전술
                    core.quant_score / tank_threat (전차 위협도)  → core.threat_grade (매우 높음/높음/보통/낮음)
                    core.cluster_response_level (군집 대응단계 1~4 + 판정 근거)
          → 랭킹, 카운터, 경보, 근거 태그, 추정 위치를 붙여 JSON 반환
    └─▶ static/dashboard.js load() → render() → 표, 박스, 상황 패널, 상세 패널, 지도
```

## 화면에서 보이는 것과 만드는 곳

| 화면 | 의미 | 만드는 곳 |
|---|---|---|
| 랭킹 표의 **위협도** 칸 | 전차 1대 점수와 단계 (100 이상 매우 높음, 70 이상 높음, 40 이상 보통, 40 미만 낮음) | 점수 `core.tank_threat`, 단계 `core.threat_grade`, 구간 `config.THREAT_GRADES` |
| 랭킹 표의 **근거 태그** | 이 전차의 점수를 설명하는 사실만 | `pipeline._target_tags` + `analyze()` 의 "C-1 소속" |
| 오른쪽 **상황 패널의 큰 배지** | 가장 심각한 군집의 대응단계 (또는 지휘관이 조정한 단계) | `pipeline.analyze()` 의 `alert` |
| 상황 패널의 **군집 목록** | 군집별 대응단계, 제대, 전술, 판정 근거 | `core.cluster_response_level` 의 `reasons` |
| 박스 색, 지도 마커 색 | 소속 군집의 대응단계 | `dashboard.js renderBoxes / renderMap` |
| 순위 | 전차 위협도가 높은 순서. 점수가 없는 미확인은 맨 뒤 | `pipeline.analyze()` 의 `ranked` 정렬 |

**지금 mock 데이터로 나오는 결과**

| 순위 | ID | 기종 | 위협도 | 근거 태그 |
|---|---|---|---|---|
| 1 | Tank-03 | T-90M | 95.8 높음 | 지휘전차 · 강점 화력 108.8 · 약점 기동력 89.4 · 지휘통제 가중치 · C-1 소속 |
| 3 | Tank-01 | T-72M1 | 88.5 높음 | 강점 화력 108.8 · 약점 기동력 71.5 · 기동·직접전투 가중치 · C-2 소속 |
| 9 | UNK-001 | 미확인 | 산출 불가 | 미확인 · 분석관 검토 · C-2 소속 |

- 군집 C-1: 2단계, 판정 근거는 "중대급 7대 ×2", "군집점수 191.6 = 최고 위협도 95.8 × 2 → 2단계"
- 군집 C-2: 3단계

## 버튼 (상황 패널)

| 버튼 | 동작 | 코드 |
|---|---|---|
| 확인 | 경보 배너와 깜빡임을 끕니다 | `dashboard.js confirmPanelA` |
| 단계 조정 | 지휘관이 전체 단계를 바꿉니다. 계산값은 그대로 두고 화면과 보고서에만 반영합니다 | `dashboard.js` 의 `stage-pick` 처리 |
| 전술 선택 | 군집을 골라 1~10번 전술을 지정합니다. 서버가 그 군집 전차 전부(지휘전차 포함)를 다시 계산합니다. "자동"을 고르면 시스템 추정으로 돌아갑니다 | `dashboard.js applyTactic` → `PATCH /api/clusters/<id>/tactic` → `pipeline.analyze(tactic_overrides=...)` |
| 보고서 출력 | 인쇄용 보고서를 새 탭으로 엽니다. 단계를 조정했다면 그 값도 함께 실립니다 | `dashboard.js openReport` → `GET /report?stage=N` → `report.html` |

## API

| 메서드 | 주소 | 내용 |
|---|---|---|
| POST | `/api/analyze` | 본문은 탐지 결과 JSON입니다. 비우면 mock 파일을 씁니다. 지정했던 전술은 초기화됩니다 |
| GET | `/api/threats` | 마지막 분석 결과입니다. 분석 전이면 404이고, 이때 화면이 자동으로 분석을 요청합니다 |
| GET | `/api/threats/<tracking_id>` | 표적 1건과 소속 군집 |
| PATCH | `/api/clusters/<cluster_id>/tactic` | 본문 `{"tactic": 1~10}` 또는 `{"tactic": null}`(자동). 잘못된 값이면 400, 없는 군집이면 404 |
| GET | `/report?stage=N` | 인쇄용 보고서 |

응답 JSON 필드 설명은 `threat/pipeline.py` 맨 위 주석에 있습니다.

## 자주 고칠 곳

- **위협도 단계 구간이나 이름:** `threat/config.py` 의 `THREAT_GRADES`
  - 색은 `static/dashboard.css` 의 `.grade.g1~g4` 입니다.
  - JS의 이름 → 색 대응은 `dashboard.js GRADE_CLASS` 입니다.
- **근거 태그 문구나 종류:** `threat/pipeline.py` 의 `_target_tags()`
- **군집 판정 근거 문구:** `threat/core.py` 의 `cluster_response_level()` 안 `reasons`
- **전술 가중치:** `threat/config.py` 의 `TACTIC_WEIGHTS`
  - 출처는 `5_data/위협도_컬럼_산출.xlsx` 입니다.
  - 여기서 빼면 화면 전술 목록에서도 사라집니다.
- **대응단계 경계(75/150/225), 하한, 제대:** `threat/config.py`
- **기종 추가:** `threat/tank_specs.json` 에 한 줄을 추가합니다.
- **보고서 내용이나 양식:** `templates/dashboard/report.html`

## 아직 mock 이거나 TODO 인 것

- **제원:** `tank_specs.json` 값은 검증 전 샘플입니다.
- **탐지 입력:** `mock_detections.json` 을 씁니다. 이미지 분석 모델은 아직 연결 전입니다.
- **군집:** 입력의 `cluster_id` 를 그대로 씁니다. 자동 군집화는 없습니다.
- **위치:** `estimate_position()` 은 bbox로 추정한 mock 값입니다.
- **서버 상태:** `STATE` 는 서버 메모리에 1건만 둡니다. 재시작하면 사라지고, 사용자 사이에 공유됩니다.
- **전술 자동 추정:** ①과 ⑩만 자동으로 정합니다. 나머지는 지휘관이 '전술 선택'으로 지정합니다.

## 실행과 테스트 (5_final 폴더에서)

```powershell
python app.py                                   # http://127.0.0.1:5000
python -m pytest tests dashboard/tests -q       # 전체 테스트
```

## 탐지 모델 연동 (v2) · Unknown 레지스트리

모델 출력 형식과 가정은 `threat/contract.md` 에 있습니다. `POST /api/analyze` 를 본문 없이 부르면 `static/mock_frames/` 샘플 영상 A → B 를 분석합니다.

| 파일 | 역할 |
|---|---|
| `threat/track.py` | 프레임 → 트랙 집계 (안테나·cope cage 비율 규칙, top_k 평균, 임베딩 평균, 대표 crop 선정) |
| `threat/judge.py` | Known / Known_Variant / Unknown 판정, 사전 DB 위협도, cope cage 보정 |
| `threat/dictdb.py` | 사전 위협도(`tank_threat`, `type_threat_summary`) 조회. DB 가 없으면 `demo_seed.json` |
| `threat/label_map.json` | 분류 라벨 → tank_id / family |
| `media.py` | 원본 프레임에서 crop 저장 (`static/track_crops/`, `static/unknown_crops/`) |
| `unknown_registry.py` | 미확인 그룹 매칭·집계·순위 (테이블은 `schema_threat.sql` 의 `unknown_*`) |
| `templates/dashboard/unknowns.html`, `static/unknowns.js` | 분석관 화면 `/unknowns` |
| `../static/mock_frames/make_frames.py` | 1장 샘플 → 영상당 5프레임 확장 (Tank-11 안테나 오탐 1프레임 포함) |

**실행 (PowerShell)**

```powershell
pip install -r requirements.txt
python app.py                     # http://127.0.0.1:5000/ → 영상 A/B 탭, /unknowns → 미확인 그룹
# 사전 DB 없이 데모:  $env:TANKLAB_DEMO = "1"; python app.py
python -m pytest dashboard/tests -q
```

**샘플에서 나오는 결과**

| 영상 | 표적 | 판정 | 위협도 근거 |
|---|---|---|---|
| A | Tank-01 | Known (T-90), 안테나 5/5프레임 → 지휘전차 | 사전 T-90, 지휘통제 가중치 |
| A | Tank-02 | Known_Variant (T-72 계열) + cope cage | T-72 계열 상위25% + 방호 ×1.10 |
| A | UNK-001 | Unknown → 새 그룹 UNK-G0001 | 주력전차 상위25% (T-90 계열 표본 2 < 3) |
| B | Tank-11 | Known (T-80), 안테나 1/5프레임 → 지휘전차 아님 | 사전 T-80 |
| B | UNK-007 | Unknown → UNK-G0001 (유사도 ≈ 0.96), n_videos = 2 | T-80 계열 상위25% + 방호 ×1.10 |
