DOC = {
    "file": "dashboard/threat/adapter.py",
    "out": "adapter.md",
    "title": "adapter.py — 대시보드 ↔ 판정 엔진(response_level.assess) 변환",
    "intro": """
**엔진 통합의 연결 부분**입니다. 예전에는 대시보드(`core.cluster_response_level`)와 DB 엔진(`response_level.assess`)이 군집 대응단계를 따로 계산했는데,
이제 대시보드도 `response_level.assess` 하나로 판정합니다. 이 파일은 그 사이에서 **모양만 바꿔 주는 변환기(어댑터)** 입니다.

```
pipeline 의 표적 행(row)들 ──to_assess_input──▶ assess 입력 ──response_level.assess──▶ assess 결과 ──from_assess_output──▶ 화면 Cluster
```

- 전차 1대 위협도 T 는 대시보드가 이미 계산한 값(cope cage 보정·계열 상위 25%·지휘전차 가중치 반영)을 `"T"` 로 넘깁니다 → 판정 엔진이 사전 DB 를 다시 찾지 않습니다.
- 화면(`dashboard.js`)이 쓰는 필드 이름(`level`, `label`, `score`, `t_cluster`, `echelon`, `reasons`)은 예전과 같게 돌려줍니다.
""",
    "sections": [
        {"head": "머리말과 import", "range": (1, 18), "blocks": [
            ((1, 6), "이 파일의 역할 요약."),
            ((10, 11), "설정값(`C`)과 전술 추정·미확인 판단 함수."),
            ((13, 16), "저장소 루트의 `response_level.py` 를 가져오려고 루트 폴더를 import 경로에 넣습니다. `rl` 로 줄여 부릅니다."),
            ((18, 18), "하한 규칙 이름을 화면용 한국어로 바꾸는 표 ('Unknown 포함' → '미확인 포함')."),
        ]},
        {"head": "함수 `load_coef()` — 판정 경계값", "range": (21, 23), "blocks": [
            ((21, 23), "`response_level.load_coef()` 를 그대로 부릅니다. DB `threat_coef` 의 lv1·lv2·lv3·floor_t 가 우선이고, 없으면 `config.py` 기본값(225/150/75, 75). 경계값 조회는 이 한 곳."),
        ]},
        {"head": "함수 `to_assess_input(...)` — 표적 행 → 판정 입력", "range": (26, 43),
         "summary": "대시보드 군집 1개를 `response_level.assess` 가 받는 형식으로 바꿉니다.", "blocks": [
            ((30, 31), "지휘관이 전술을 지정했으면 그 번호가 `tactic_override`. 군집 표적 ID 집합도 만듭니다."),
            ((32, 36), "군집 ID, 시스템 추정 전술(지휘관이 바꾸기 전), 지휘관 전술, 이 군집에 속한 핵심표적, 미확인을 대수에 넣을지(`ECHELON_COUNT_UNKNOWN`)."),
            ((37, 40), "차량 목록: 상태(Known/Known_Variant/Unknown), 분류, 사전 ID, 지휘전차 여부, 그리고 **미리 계산된 위협도 T**와 그 출처."),
            ((41, 43), "v2 입력이면 프레임별로 그 군집 표적만 남긴 목록을 넣습니다 → 판정 엔진이 '프레임마다 동시에 보인 대수의 최댓값'으로 제대를 정합니다. v1 은 프레임 정보가 없어 생략."),
        ]},
        {"head": "함수 `floor_text(f)` — 하한 규칙 문장", "range": (46, 49), "blocks": [
            ((46, 49), "판정 엔진의 하한 규칙 1개를 화면 문장으로. 예: '핵심표적 지정 → 최소 2단계 (Tank-01)', '미확인 포함 → 최소 3단계 (미확인 1대: UNK-001)'."),
        ]},
        {"head": "함수 `from_assess_output(result)` — 판정 결과 → 화면 Cluster", "range": (52, 63),
         "summary": "판정 엔진 결과를 화면이 쓰던 형식으로 되돌리고, 새 정보(S·E·N, 하한 규칙 목록, 지휘관 조치 전 단계)를 덧붙입니다.", "blocks": [
            ((54, 55), "대수 N, 제대가중치 E, 군집점수 S, 군집 최고 위협도 T, 점수만으로 본 단계, 실제로 적용된 하한 규칙."),
            ((56, 58), "판정 근거 문장 — 예전 문구 그대로: '소대급 3대 ×1', '군집점수 88.9 = 최고 위협도 88.9 × 1 → 3단계', 그리고 적용된 하한 규칙 문장."),
            ((59, 63), "화면 필드 + `floors`(검사한 하한 규칙 전부, 적용 여부 포함) + `level_before_override` + S·E·N + 핵심표적 목록."),
        ]},
        {"head": "함수 `assess_cluster(...)` — 대시보드 군집 판정 (pipeline 이 부름)", "range": (66, 71), "blocks": [
            ((69, 70), "입력으로 바꿔 판정합니다. 모든 차량에 T 가 있으므로 사전 lookup 은 빈 표(`{}`)로 넘깁니다."),
            ((71, 71), "화면 Cluster 를 돌려주되, 판정 기록 저장(`dashboard/__init__.py` `_attach`)에 쓰려고 입력·결과를 `_assess_input`·`_assess_result` 로 붙입니다. 이 두 필드는 API 응답으로 나가기 전에 지웁니다."),
        ]},
        {"head": "함수 `cluster_response_level(cluster, coef)` — 예전 호출 형식 호환", "range": (74, 83), "blocks": [
            ((77, 81), "예전 형식 `{\"detections\": [...], \"threats\": [...]}` 를 표적 행으로 바꿉니다. i번째 위협도는 i번째 탐지의 것이고, 모자라면 점수 없음."),
            ((82, 83), "같은 판정 엔진으로 판정하고 내부 필드를 빼서 돌려줍니다. 지금은 v1 테스트(`dashboard/tests/test_threat.py`)가 씁니다."),
        ]},
    ],
}
