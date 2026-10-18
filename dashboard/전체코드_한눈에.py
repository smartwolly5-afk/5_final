"""위협도 대시보드 서버 코드 전체를 한 파일로 모은 '읽기용' 사본 (줄마다 주석).

원본 위치 (실제로 돌아가는 코드는 이쪽):
  threat/config.py    → [1] 설정값
  threat/core.py      → [2] 단계별 계산
  threat/pipeline.py  → [3] 화면용 JSON 조립
  __init__.py         → [4] Flask 주소(API)
화면 쪽(dashboard.js, index.html, dashboard.css)은 파이썬이 아니라서 여기 넣지 않았다.

실행:  python dashboard/전체코드_한눈에.py   (5_final 폴더에서)
  → mock 탐지 12건을 분석해 랭킹·군집을 출력하고, 원본 코드와 결과가 똑같은지 검사한다.
  ponytail: 사본이라 원본을 고치면 여기도 고쳐야 함. 어긋나면 맨 아래 검사가 실패해서 알려준다.
"""

# ════════════════════════════════════════════════════════════════════
# [0] 가져오기
# ════════════════════════════════════════════════════════════════════
import json                     # JSON 파일(제원표, mock 탐지 결과) 읽기
import math                     # 위치 추정에 쓰는 삼각함수 (cos, sin, radians)
from datetime import datetime   # 보고서에 찍는 작성 시각
from enum import IntEnum        # 전술 번호를 '이름 붙은 정수'로 다루기 위함
from pathlib import Path        # 파일 경로 계산

HERE = Path(__file__).with_name("threat")  # 이 파일 옆 threat 폴더 (JSON 파일이 거기 있음)


# ════════════════════════════════════════════════════════════════════
# [1] 설정값 (원본: threat/config.py) — 숫자를 바꾸려면 원본 config.py 를 고친다
# ════════════════════════════════════════════════════════════════════

BASE_MODEL = "M1A1"  # 기준전차. 이 전차의 화력·기동력·방호력을 각각 100점으로 놓고 다른 전차를 비교

GUN_LENGTH_EXP = 0.5  # 화력 식의 구경장 지수. 0.5 = 제곱근 → 포신이 4배 길어도 화력은 2배로만 반영
HEIGHT_EXP = 0.5      # 방호력 식의 차체 높이 지수. 차체가 낮을수록 맞을 면적이 작아 방호력이 약간 오름

# 종합 점수(MPI, 참고값) 가중치: 화력 50%, 기동력 30%, 방호력 20%. 화면 상세 패널에만 쓰고 순위에는 안 씀
QUANT_WEIGHTS = {"firepower": 0.5, "mobility": 0.3, "protection": 0.2}

# 전술별 (화력, 기동력, 방호력) 가중치. 출처: 5_data/위협도_컬럼_산출.xlsx '전술가중치' 시트 (전문가 설문)
TACTIC_WEIGHTS = {
    1: (0.45, 0.35, 0.20),   # 기동·직접전투  — 지휘전차가 없는 군집의 기본값
    2: (0.21, 0.43, 0.36),   # 병력수송·지원
    3: (0.38, 0.28, 0.34),   # 대전차
    4: (0.61, 0.22, 0.17),   # 간접화력
    5: (0.72, 0.15, 0.12),   # 장거리화력      — 합계 0.99 → 계산할 때 합계로 나눠 1로 맞춤
    6: (0.54, 0.21, 0.25),   # 방공
    7: (0.19, 0.51, 0.30),   # 정찰·표적획득
    8: (0.17, 0.44, 0.39),   # 공병
    9: (0.18, 0.36, 0.46),   # CBRN·연막차폐
    10: (0.19, 0.43, 0.37),  # 지휘통제        — 지휘전차는 항상 이 가중치. 합계 0.99
}                            # 11번 전투근무지원은 화력이 0이라 전차에 안 씀 → 일부러 없음

# 전차 1대 위협도 단계 (랭킹 표 '위협도' 칸). (하한 점수, 이름). 위에서부터 처음 만족하는 것
THREAT_GRADES = [(100, "매우 높음"), (70, "높음"), (40, "보통"), (0, "낮음")]

# 제대: 군집 안 전차+기갑차 대수로 정함. (최소 대수, 제대가중치, 이름). 큰 것부터 검사
ECHELONS = [(16, 3, "대대"), (5, 2, "중대"), (1, 1, "소대")]
ECHELON_CATEGORIES = ("전차", "기갑차")  # 대수에 넣는 분류. 포병·인원·미확인은 안 셈

LEVEL_THRESHOLDS = [(225, 1), (150, 2), (75, 3)]  # 군집점수가 이 값 이상이면 그 단계. 모두 미만이면 4단계
FLOOR_TANK_THREAT = 75                            # 위협도 75 이상 전차가 있는 군집은 4단계(가장 약함)로 못 내려감
LEVELS = {1: "즉시 보고", 2: "우선 감시", 3: "지속 감시", 4: "관심"}  # 대응단계 이름. 1이 가장 심각

CAMERA_FOV_DEG = 60  # 카메라 가로 시야각(도). 박스가 화면 어디 있는지 → 방위로 바꿀 때 사용
DISTANCE_K = 2000    # 거리(m) ≈ 2000 × 10 ÷ 박스 높이(%). 박스 높이 10%면 2km (mock 추정)


# ════════════════════════════════════════════════════════════════════
# [2] 단계별 계산 (원본: threat/core.py) — Flask·DB 와 무관한 순수 함수
# ════════════════════════════════════════════════════════════════════
# 탐지 1건(dict) 모양:
#   {"tracking_id": "Tank-03", "category": "전차", "model": "T-90M", "confidence": 0.93,
#    "bbox": {"x","y","w","h"}, "is_commander": True, "cluster_id": "C-1"}

CATEGORIES = ("전차", "기갑차", "포병", "인원", "미확인")  # 입력에 허용하는 분류 (이 밖의 값은 400 오류)

_raw_specs = json.loads((HERE / "tank_specs.json").read_text(encoding="utf-8"))  # 제원표 파일 읽기
SPECS = {k: v for k, v in _raw_specs.items() if not k.startswith("_")}           # "_note" 같은 설명 키는 빼고 기종만


class Tactic(IntEnum):
    """전술 번호 1~11. 자동 추정은 1번과 10번만 하고, 나머지는 지휘관이 화면 '전술 선택'으로 지정."""
    MANEUVER = 1         # 기동·직접전투
    TRANSPORT = 2        # 병력수송·지원
    ANTI_TANK = 3        # 대전차
    INDIRECT_FIRE = 4    # 간접화력
    LONG_RANGE_FIRE = 5  # 장거리화력
    AIR_DEFENSE = 6      # 방공
    RECON = 7            # 정찰·표적획득
    ENGINEER = 8         # 공병
    CBRN = 9             # CBRN·연막차폐
    COMMAND = 10         # 지휘통제
    SUSTAINMENT = 11     # 전투근무지원 (가중치 없음)


TACTIC_NAMES = {1: "기동·직접전투", 2: "병력수송·지원", 3: "대전차", 4: "간접화력", 5: "장거리화력", 6: "방공",  # 번호 → 화면 이름
                7: "정찰·표적획득", 8: "공병", 9: "CBRN·연막차폐", 10: "지휘통제", 11: "전투근무지원"}


def spec_of(det):
    """전차이고 기종이 제원표에 있으면 그 제원, 아니면 None."""
    if det.get("category") != "전차":  # 전차가 아니면 (기갑차·포병 등)
        return None                    # 제원을 찾지 않음 → 위협도 계산 안 함
    return SPECS.get(det.get("model"))  # 기종명으로 찾기. 없는 기종이면 None


def is_unknown(det):
    """미확인 표적인가: 분류 자체가 '미확인'이거나, 전차인데 제원표에 없는 기종."""
    if det.get("category") == "미확인":                      # 모델이 무엇인지 모름
        return True
    return det.get("category") == "전차" and spec_of(det) is None  # 전차인데 제원이 없음


def classify_echelon(detections):
    """군집의 제대 판정 → {"n": 대수, "weight": 제대가중치, "name": 제대명}."""
    n = sum(d.get("category") in ECHELON_CATEGORIES for d in detections)  # 전차·기갑차만 셈 (True 는 1로 더해짐)
    for lo, weight, name in ECHELONS:                                     # 대대(16) → 중대(5) → 소대(1) 순서
        if n >= lo:                                                       # 최소 대수 이상이면
            return {"n": n, "weight": weight, "name": name}               # 그 제대로 확정
    return {"n": 0, "weight": 0, "name": "없음"}                          # 0대 → 가중치 0 → 군집점수도 0


def infer_tactic(detections):
    """군집 전술 자동 추정: 전차 중 지휘전차가 있으면 ⑩지휘통제, 없으면 ①기동·직접전투."""
    tanks = [d for d in detections if d.get("category") == "전차"]  # 전차만 추림
    if any(d.get("is_commander") for d in tanks):                   # 지휘전차가 하나라도 있으면
        return Tactic.COMMAND                                       # 10번
    return Tactic.MANEUVER                                          # 아니면 1번


def _firepower(s):
    """화력 원점수 = 주포 구경(mm) × 구경장^0.5. 기준전차로 나누기 전 값."""
    return s["caliber_mm"] * s["gun_length"] ** GUN_LENGTH_EXP


def quant_score(spec, base=None):
    """정량 점수 (기준전차 = 100): 화력·기동력·방호력·종합."""
    b = base or SPECS[BASE_MODEL]                                 # 비교 기준 = M1A1 제원
    fire = _firepower(spec) / _firepower(b)                       # 화력 비율 (1.0 = 기준전차와 같음)
    mob = spec["pw"] / b["pw"]                                    # 기동력 비율 = 출력대중량비(hp/t) 비교
    armor = (spec["ke"] / b["ke"] + spec["ce"] / b["ce"]) / 2     # 장갑 비율 = 운동에너지탄(KE)·화학에너지탄(CE) 방호의 평균
    shape = (b["height"] / spec["height"]) ** HEIGHT_EXP          # 높이 보정 = 기준보다 낮으면 1보다 큼
    prot = armor * shape                                          # 방호력 비율
    w = QUANT_WEIGHTS                                             # 종합 점수 가중치 0.5/0.3/0.2
    total = fire * w["firepower"] + mob * w["mobility"] + prot * w["protection"]  # 종합 (참고값)
    pairs = (("firepower", fire), ("mobility", mob), ("protection", prot), ("total", total))
    return {k: round(v * 100, 1) for k, v in pairs}              # 비율 × 100, 소수 1자리로


def tactic_weights(tactic, is_commander=False):
    """실제로 적용할 (전술, (화력, 기동, 방호) 가중치)."""
    t = Tactic.COMMAND if is_commander else Tactic(tactic)        # 지휘전차는 군집 전술과 상관없이 지휘통제
    if t not in TACTIC_WEIGHTS:                                   # 11번처럼 가중치가 없는 전술이면
        raise ValueError(f"가중치 미정 전술: {TACTIC_NAMES[t]}")  # 오류 → API 400
    return t, TACTIC_WEIGHTS[t]                                   # 전술과 가중치 3개


def tank_threat(spec, tactic, is_commander=False):
    """전차 1대 위협도 = 화력·기동력·방호력 점수를 전술 가중치로 가중평균 (기준전차 ≈ 100)."""
    _, (wf, wm, wp) = tactic_weights(tactic, is_commander)  # 가중치 3개 (전술 이름은 여기선 안 씀)
    q = quant_score(spec)                                   # 화력·기동·방호 점수 (100 기준)
    weighted = wf * q["firepower"] + wm * q["mobility"] + wp * q["protection"]  # 가중합
    return round(weighted / (wf + wm + wp), 1)              # 가중치 합으로 나눔 (합 0.99 인 전술도 공평하게)


def threat_grade(score):
    """위협도 점수 → 단계 이름 (매우 높음/높음/보통/낮음). 점수가 없으면 None."""
    if score is None:                                       # 미확인·제원 없음
        return None                                         # 단계도 없음 → 화면에 '산출 불가'
    for lo, name in THREAT_GRADES:                          # 100 → 70 → 40 → 0 순서로
        if score >= lo:                                     # 하한 이상이면
            return name                                     # 그 단계


def cluster_response_level(cluster):
    """군집 대응단계 1~4 와 판정 근거.
    입력 {"detections": [탐지...], "threats": [전차 위협도 또는 None ...]}"""
    dets = cluster["detections"]                                            # 군집의 모든 탐지
    threats = [t for t in cluster.get("threats", []) if t is not None]     # 점수가 있는 전차만
    ech = classify_echelon(dets)                                            # 제대 (소대·중대·대대)
    t_cluster = max(threats, default=0.0)                                   # 군집 위협도 = 가장 위험한 전차 1대의 점수
    score = round(t_cluster * ech["weight"], 1)                             # 군집점수 = 군집 위협도 × 제대가중치
    level = 4                                                               # 기본은 4단계(관심)
    for th, lv in LEVEL_THRESHOLDS:                                         # 225 → 150 → 75 순서로
        if score >= th:                                                     # 경계값 이상이면
            level = lv                                                      # 그 단계
            break                                                           # 더 볼 필요 없음

    if ech["n"]:                                                            # 전투차량이 있으면
        reasons = [f"{ech['name']}급 {ech['n']}대 ×{ech['weight']}"]         # 근거 1: 제대
    else:
        reasons = ["전투차량 없음"]
    reasons.append(f"군집점수 {score:g} = 최고 위협도 {t_cluster:g} × {ech['weight']} → {level}단계")  # 근거 2: 계산식

    if level == 4:                                                          # 하한 규칙은 4단계일 때만 의미 있음
        floors = []                                                         # 걸린 하한 규칙 모음
        if any(is_unknown(d) for d in dets):                                # 정체 모를 표적이 섞여 있으면
            floors.append("미확인 포함 → 4단계 불가")
        if any(t >= FLOOR_TANK_THREAT for t in threats):                    # 위협도 75 이상 전차가 있으면
            floors.append(f"위협도 {FLOOR_TANK_THREAT} 이상 전차 → 4단계 불가")
        if floors:                                                          # 하나라도 걸리면
            level = 3                                                       # 3단계로 올림
            reasons += floors                                               # 근거에 추가
    return {"level": level, "label": LEVELS[level], "score": score, "t_cluster": t_cluster,
            "echelon": ech, "reasons": reasons}


# ════════════════════════════════════════════════════════════════════
# [3] 화면용 JSON 조립 (원본: threat/pipeline.py) — 화면(dashboard.js)은 이 결과만 받아 그림
# ════════════════════════════════════════════════════════════════════

MOCK_FILE = HERE / "mock_detections.json"  # 이미지 분석 모델이 붙기 전까지 쓰는 가짜 탐지 결과
RANKED = ("전차", "미확인")                 # 랭킹 표에 올리는 분류
COUNT_KEYS = {"전차": "tank", "기갑차": "apc", "포병": "artillery", "인원": "infantry"}  # 상단 카운터 키 (화면은 포병+인원을 '포병' 한 칸으로 표시)
AXIS_LABELS = {"firepower": "화력", "mobility": "기동력", "protection": "방호력"}       # 근거 태그에 쓰는 한글 이름


def load_mock(path=MOCK_FILE):
    """mock 입력 읽기. 모델이 붙으면 같은 모양의 dict 를 analyze() 에 넘기면 된다."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def estimate_position(det, observer):
    """관측 지점(카메라) 기준 방위·거리 → 위도·경도 추정. mock: 거리측정 장비가 생기면 교체."""
    b = det["bbox"]                                                     # 박스 (화면 % 좌표)
    center_x = b["x"] + b["w"] / 2                                      # 박스 가로 중심 (0~100)
    offset_deg = (center_x - 50) / 100 * CAMERA_FOV_DEG                 # 화면 가운데서 벗어난 각도
    bearing = (observer.get("heading_deg", 0) + offset_deg) % 360       # 방위 = 카메라 방향 + 벗어난 각도 (0~360)
    dist = DISTANCE_K * 10 / max(b["h"], 1)                             # 거리(m): 박스가 클수록 가까움 (0 나누기 방지)
    north = dist * math.cos(math.radians(bearing))                      # 북쪽으로 이동한 거리(m)
    east = dist * math.sin(math.radians(bearing))                       # 동쪽으로 이동한 거리(m)
    lat = observer["lat"] + north / 111_320                             # 위도 1도 ≈ 111.32km
    lon = observer["lon"] + east / (111_320 * math.cos(math.radians(observer["lat"])))  # 경도 1도는 위도가 높을수록 짧아짐
    return {"bearing_deg": round(bearing, 1), "distance_m": round(dist),
            "lat": round(lat, 6), "lon": round(lon, 6), "estimated": True}  # estimated=True → 화면에 '추정' 표시


def _validate(payload):
    """입력 검증. 외부에서 오는 값이라 꼭 필요. 문제가 있으면 ValueError → API 400."""
    dets = payload.get("detections") if isinstance(payload, dict) else None  # 탐지 목록 꺼내기
    if not isinstance(dets, list):                                           # 리스트가 아니면
        raise ValueError("detections 리스트 필요")
    seen = set()                                                             # 이미 본 tracking_id (중복 검사용)
    for d in dets:                                                           # 탐지마다
        if not isinstance(d, dict) or not d.get("tracking_id"):              # ID 없음
            raise ValueError("각 탐지에 tracking_id 필요")
        if d["tracking_id"] in seen:                                         # ID 중복
            raise ValueError(f"tracking_id 중복: {d['tracking_id']}")
        seen.add(d["tracking_id"])                                           # 본 것으로 기록
        if d.get("category") not in CATEGORIES:                              # 허용 안 된 분류
            raise ValueError(f"{d['tracking_id']}: category 는 {'/'.join(CATEGORIES)} 중 하나")
        bbox = d.get("bbox") or {}                                           # 박스 (없으면 빈 dict)
        if not all(isinstance(bbox.get(k), (int, float)) for k in "xywh"):   # x,y,w,h 가 모두 숫자인지
            raise ValueError(f"{d['tracking_id']}: bbox x,y,w,h 숫자 필요")
        c = d.get("confidence")                                              # 탐지 신뢰도 (없어도 됨)
        if c is not None and not (isinstance(c, (int, float)) and not isinstance(c, bool) and 0 <= c <= 1):
            raise ValueError(f"{d['tracking_id']}: confidence 는 0~1 숫자 또는 null")  # 화면이 toFixed() 로 표시
    obs = (payload.get("source") or {}).get("observer") or {}                # 관측 지점
    if not all(isinstance(obs.get(k), (int, float)) for k in ("lat", "lon")):  # 위경도 숫자인지
        raise ValueError("source.observer.lat/lon 필요")
    h = obs.get("heading_deg")                                               # 카메라 방향 (없으면 0)
    if h is not None and not (isinstance(h, (int, float)) and not isinstance(h, bool)):
        raise ValueError("source.observer.heading_deg 는 숫자")              # 위치 추정 계산에 씀
    return dets                                                              # 검증 통과한 탐지 목록


def _target_tags(row, scores):
    """근거 태그: 이 전차의 위협도를 설명하는 사실만 모음 (군집 판정 근거는 따로)."""
    tags = []
    if row["is_commander"]:                                                  # 지휘전차면
        tags.append("지휘전차")                                              # 지휘통제 가중치를 쓴 이유
    if row["is_unknown"]:                                                    # 미확인이면
        if row["category"] == "미확인":
            tags.append("미확인 · 분석관 검토")                               # 기종 자체를 모름
        else:
            tags.append("제원 없음 · 분석관 검토")                            # 전차인데 제원표에 없음
    if row["is_new"]:                                                        # 직전 분석에 없던 표적
        tags.append("신규")
    if scores:                                                               # 점수가 있는 전차만
        axes = {k: scores[k] for k in AXIS_LABELS}                           # 화력·기동·방호 3개만
        hi = max(axes, key=axes.get)                                         # 가장 높은 항목
        lo = min(axes, key=axes.get)                                         # 가장 낮은 항목
        tags.append(f"강점 {AXIS_LABELS[hi]} {axes[hi]:g}")                  # 예: 강점 화력 108.8
        tags.append(f"약점 {AXIS_LABELS[lo]} {axes[lo]:g}")                  # 예: 약점 기동력 89.4
        tags.append(f"{row['tactic_name']} 가중치")                           # 어떤 전술 가중치로 계산했는지
    return tags


def analyze(payload, prev=None, tactic_overrides=None):
    """탐지 결과 → 화면용 결과(AnalysisResult).
    prev = 직전 분석 결과 (신규 표적·단계 변화 비교용)
    tactic_overrides = {군집ID: 전술번호} 지휘관이 '전술 선택'으로 지정한 것"""
    dets = _validate(payload)                                                # 1) 입력 검증
    source = payload["source"]                                               # 영상 이름·촬영일·관측 지점
    prev_ids = {t["tracking_id"] for t in prev["targets"]} if prev else None # 직전에 있던 표적 ID들 (첫 분석이면 None)
    overrides = tactic_overrides or {}                                       # 지정 전술 (없으면 빈 dict)

    groups = {}                                                              # 2) 군집별로 나누기: 군집ID → 탐지 목록
    for d in dets:
        cid = d.get("cluster_id") or "C-1"                                   # 군집 ID 없으면 C-1
        groups.setdefault(cid, []).append(d)                                 # 그 군집 목록에 추가

    for cid, t in overrides.items():                                         # 3) 지정 전술 검증
        if cid not in groups:                                                # 없는 군집에 지정했으면
            raise LookupError(f"군집 없음: {cid}")                           # → API 404
        if t not in TACTIC_WEIGHTS:                                          # 가중치 없는 번호면
            raise ValueError(f"가중치 없는 전술 번호: {t} (1~10만 가능)")       # → API 400

    clusters, targets = [], []                                               # 결과 모음
    for cid, members in groups.items():                                      # 4) 군집마다
        override = overrides.get(cid)                                        # 지휘관 지정 전술 (없으면 None)
        tactic = Tactic(override) if override else infer_tactic(members)     # 지정 우선, 없으면 자동 추정
        rows = []                                                            # 이 군집의 표적 행들
        for d in members:                                                    # 군집 안 표적마다
            spec = spec_of(d)                                                # 제원 (전차가 아니거나 없는 기종이면 None)
            row = {                                                          # 화면에 보낼 표적 1건
                "tracking_id": d["tracking_id"], "category": d["category"], "model": d.get("model"),
                "confidence": d.get("confidence"), "bbox": d["bbox"],
                "is_commander": bool(d.get("is_commander")),                 # 지휘전차 여부
                "is_unknown": is_unknown(d),                                 # 미확인 여부
                "is_new": prev_ids is not None and d["tracking_id"] not in prev_ids,  # 직전에 없던 ID면 신규
                "cluster_id": cid, "rank": None,                             # 순위는 나중에 매김
                "threat": None, "grade": None, "scores": None, "weights": None,  # 점수는 제원 있을 때만 채움
                "tactic": int(tactic), "tactic_name": TACTIC_NAMES[tactic],
                "position": estimate_position(d, source["observer"]),        # 추정 위치 (미니맵용)
            }
            if spec:                                                         # 제원 있는 전차만 점수 계산
                cmd = row["is_commander"] and not override                   # 지휘관이 전술 지정하면 지휘전차도 그 전술
                used, (wf, wm, wp) = tactic_weights(tactic, cmd)             # 실제로 쓴 전술·가중치
                row["threat"] = tank_threat(spec, tactic, cmd)               # 전차 1대 위협도
                row["scores"] = quant_score(spec)                            # 화력·기동·방호·종합
                row["weights"] = {"firepower": wf, "mobility": wm, "protection": wp}  # 상세 막대 옆 '× 0.19' 값
                row["tactic"] = int(used)                                    # 지휘전차면 10번으로 바뀜
                row["tactic_name"] = TACTIC_NAMES[used]
                row["grade"] = threat_grade(row["threat"])                   # 매우 높음/높음/보통/낮음
            row["tags"] = _target_tags(row, row["scores"])                   # 근거 태그
            rows.append(row)

        threats = [r["threat"] for r in rows]                                # 이 군집 표적들의 위협도 (None 섞임)
        res = cluster_response_level({"detections": members, "threats": threats})  # 5) 군집 대응단계
        for r in rows:                                                       # 표적마다 소속 군집 단계 기록
            r["level"] = res["level"]                                        # 박스·마커 색에 씀
            r["label"] = res["label"]
            r["tags"].append(f"{cid} 소속")                                    # 랭킹 표의 'C-1 소속' 태그
        clusters.append(dict(res, cluster_id=cid, tactic=int(tactic), tactic_name=TACTIC_NAMES[tactic],
                             tactic_source="지휘관 지정" if override else "시스템 추정",
                             track_ids=[r["tracking_id"] for r in rows]))    # 군집 결과 1건
        targets += rows                                                      # 전체 표적 목록에 합침

    # 6) 랭킹: 전차·미확인만. 위협도 높은 순 → 점수 없는 미확인은 맨 뒤 → 같으면 군집 단계 순
    ranked = sorted((t for t in targets if t["category"] in RANKED),
                    key=lambda t: (t["threat"] is None, -(t["threat"] or 0), t["level"]))
    for i, t in enumerate(ranked, 1):                                        # 1부터 순위 매김
        t["rank"] = i
    targets = ranked + [t for t in targets if t["rank"] is None]             # 순위 없는 것(기갑차·포병·인원)은 뒤에

    # 7) 상단 카운터
    counts = {"total": len(targets)}                                         # 전체 수
    for key in COUNT_KEYS.values():                                          # tank, apc, artillery, infantry 를 0 으로
        counts[key] = 0
    counts["new"] = sum(t["is_new"] for t in targets)                        # 신규 수
    for t in targets:
        if t["category"] in COUNT_KEYS:                                      # 미확인은 카운터 칸이 없음
            counts[COUNT_KEYS[t["category"]]] += 1                           # 분류별 +1

    # 8) 경보: 가장 심각한 군집 (단계 숫자가 작을수록, 같으면 군집점수 높을수록)
    top = min(clusters, key=lambda c: (c["level"], -c["score"]), default=None)
    level = top["level"] if top else 4                                       # 군집이 없으면 4단계
    if top:
        message = (f"{top['cluster_id']} {top['echelon']['name']}급 {top['echelon']['n']}대 · {top['tactic_name']}"
                   f" · 군집점수 {top['score']:g}")                           # 보고서·배너에 쓰는 요약
    else:
        message = "탐지 표적 없음"
    alert = {"level": level, "label": LEVELS[level],
             "prev_level": prev["alert"]["level"] if prev else None,         # 직전 단계 (변화 표시용)
             "banner": level == 1,                                           # 1단계면 상단 빨간 배너
             "message": message}
    return {"source": source, "counts": counts, "alert": alert, "clusters": clusters, "targets": targets}


# ════════════════════════════════════════════════════════════════════
# [4] Flask 주소 (원본: __init__.py) — 브라우저 화면과 API
# ════════════════════════════════════════════════════════════════════

def make_blueprint():
    """원본과 같은 라우트를 가진 Blueprint. 실제 서버(app.py)는 원본 __init__.py 의 것을 쓴다."""
    from flask import Blueprint, jsonify, render_template, request  # Flask 는 이 함수 안에서만 필요

    bp = Blueprint("dashboard", __name__, template_folder="templates", static_folder="static",
                   static_url_path="/dashboard-static")             # 화면 파일 위치와 주소

    # 서버 메모리 상태. ponytail: 1건만, 재시작하면 사라짐, 사용자끼리 공유. 다중 사용자면 DB 로
    state = {"payload": None,    # 마지막 입력 (전술 바꾸면 이걸로 다시 계산)
             "prev": None,       # 그 직전 결과 ('신규' 판단 기준)
             "result": None,     # 마지막 결과 (화면이 받는 JSON)
             "overrides": {}}    # 지휘관 지정 전술 {군집ID: 번호}

    def bad(e, code):
        return jsonify(error=str(e)), code                          # 오류를 JSON 으로 (화면이 배너로 보여줌)

    @bp.get("/")
    def index():                                                    # 대시보드 화면
        tactics = [(n, TACTIC_NAMES[n]) for n in sorted(TACTIC_WEIGHTS)]  # 전술 선택 목록 (1~10)
        return render_template("dashboard/index.html", tactics=tactics)

    @bp.post("/api/analyze")
    def api_analyze():                                              # '분석 시작' = 새 분석
        payload = request.get_json(silent=True) or load_mock()      # 본문 JSON, 없으면 mock
        prev = state["result"]                                      # 지금 결과가 '직전 결과'가 됨
        try:
            result = analyze(payload, prev)                         # 새 입력은 지정 전술 없이 계산
        except ValueError as e:
            return bad(e, 400)                                      # 입력 형식 오류
        state.update(payload=payload, prev=prev, result=result, overrides={})  # 지정 전술 초기화
        return jsonify(result)

    @bp.get("/api/threats")
    def api_threats():                                              # 마지막 결과
        if state["result"] is None:
            return bad("분석 결과 없음. POST /api/analyze 먼저 실행", 404)  # 화면은 404 받으면 자동 분석
        return jsonify(state["result"])

    @bp.get("/api/threats/<tracking_id>")
    def api_threat_detail(tracking_id):                             # 표적 1건 + 소속 군집
        result = state["result"] or {"targets": [], "clusters": []}
        t = next((t for t in result["targets"] if t["tracking_id"] == tracking_id), None)  # ID로 찾기
        if t is None:
            return bad(f"표적 없음: {tracking_id}", 404)
        cluster = next(c for c in result["clusters"] if c["cluster_id"] == t["cluster_id"])  # 소속 군집
        return jsonify(target=t, cluster=cluster)

    @bp.patch("/api/clusters/<cluster_id>/tactic")
    def api_set_tactic(cluster_id):                                 # '전술 선택' → 그 군집 다시 계산
        if state["payload"] is None:
            return bad("분석 결과 없음", 404)
        tactic = (request.get_json(silent=True) or {}).get("tactic")  # 1~10 또는 None(자동)
        overrides = dict(state["overrides"])                        # 복사본에 적용 (실패하면 원래 값 유지)
        if tactic is None:
            overrides.pop(cluster_id, None)                         # 자동으로 되돌림
        elif isinstance(tactic, int) and not isinstance(tactic, bool):  # True/False 는 int 로 취급되므로 제외
            overrides[cluster_id] = tactic
        else:
            return bad("tactic 은 1~10 정수 또는 null", 400)
        try:
            result = analyze(state["payload"], state["prev"], overrides)  # 같은 입력으로 다시 계산
        except LookupError as e:
            return bad(e, 404)                                      # 없는 군집
        except ValueError as e:
            return bad(e, 400)                                      # 가중치 없는 전술
        state.update(overrides=overrides, result=result)
        return jsonify(result)

    @bp.get("/report")
    def report():                                                   # 인쇄용 보고서
        if state["result"] is None:
            return bad("분석 결과 없음", 404)
        stage = request.args.get("stage", type=int)                 # 지휘관이 조정한 단계 (숫자 아니면 None)
        if stage not in LEVELS:                                     # 1~4 가 아니면 무시
            stage = None
        return render_template("dashboard/report.html", r=state["result"], stage=stage, levels=LEVELS,
                               generated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    return bp


# ════════════════════════════════════════════════════════════════════
# [5] 실행: mock 으로 돌려 보고, 원본 코드와 결과가 같은지 검사
# ════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys                                                      # 원본 패키지를 찾기 위한 경로 추가
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 5_final 폴더

    result = analyze(load_mock())                                   # 이 파일의 코드로 분석
    print("순위  ID        기종      위협도  단계       군집")
    for t in result["targets"]:
        if t["rank"] is not None:                                   # 랭킹 표에 오르는 것만
            print(f"{t['rank']:>3}  {t['tracking_id']:<9} {t['model'] or '미확인':<9} "
                  f"{t['threat'] if t['threat'] is not None else '-':>6}  {t['grade'] or '산출 불가':<9} "
                  f"{t['cluster_id']} {t['level']}단계")
    for c in result["clusters"]:
        print(f"{c['cluster_id']}: {c['level']}단계 · {' / '.join(c['reasons'])}")

    from dashboard.threat import analyze as original_analyze       # 원본 코드
    assert result == original_analyze(load_mock()), "원본과 결과가 다름 — 원본이 바뀌었으면 이 파일도 고칠 것"
    print("OK: 원본 코드와 결과 동일")
