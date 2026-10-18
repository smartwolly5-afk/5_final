"""위협도 계산 코드 정리본 — 숫자·데이터는 코드정리.json, 계산 순서는 이 파일 (줄마다 주석).

원본 (실제 서버가 쓰는 코드):  threat/config.py · threat/core.py · threat/pipeline.py · threat/*.json
이 파일은 그 계산을 한 파일에 모은 '읽기용'이다. Flask 주소(__init__.py)는 화면 연결이라 뺐다.

흐름:  탐지 결과 → 군집별로 묶기 → 군집 전술 정하기 → 전차마다 화력·기동·방호 점수 → 전차 위협도
       → 군집 대응단계(1~4) → 순위 매기기 → 화면용 결과(dict)

실행:  python 코드정리.py   (dashboard 폴더에서)
  → mock 12건을 분석해 출력하고, 원본 코드와 결과가 똑같은지 검사한다.
  ponytail: 사본이라 원본을 고치면 여기도 고쳐야 함. 어긋나면 맨 아래 검사가 실패해서 알려준다.
"""

# ════════════════════════════════════════════════════════════════════
# [0] 준비: 라이브러리와 JSON 읽기
# ════════════════════════════════════════════════════════════════════
import json                # JSON 파일을 파이썬 dict 로 읽는 표준 라이브러리
import math                # 위치 추정에 쓰는 삼각함수 (cos, sin, radians)
from pathlib import Path   # 파일 경로를 다루는 표준 라이브러리

DATA_FILE = Path(__file__).with_name("코드정리.json")  # 이 파일과 같은 폴더의 코드정리.json


def strip_notes(x):
    """JSON 안의 '_설명' 같은 '_' 키를 지운다 (설명용이라 계산에는 필요 없음)."""
    if isinstance(x, dict):                                                     # dict 이면
        return {k: strip_notes(v) for k, v in x.items() if not k.startswith("_")}  # '_' 키는 버리고 안쪽도 똑같이 처리
    if isinstance(x, list):                                                     # 리스트면
        return [strip_notes(v) for v in x]                                      # 원소마다 똑같이 처리
    return x                                                                    # 숫자·문자는 그대로


DATA = strip_notes(json.loads(DATA_FILE.read_text(encoding="utf-8")))  # JSON 읽기 → 설명 키 제거
S = DATA["settings"]                                                   # 설정값 묶음 (짧게 S 로 부름)
SPECS = DATA["tank_specs"]                                             # 기종명 → 제원
TACTIC_NAMES = {int(k): v for k, v in DATA["tactic_names"].items()}    # JSON 키는 문자열("1")이라 정수(1)로 바꿈
TACTIC_WEIGHTS = {int(k): v for k, v in S["tactic_weights"].items()}   # 전술번호 → [화력, 기동, 방호] 가중치
LEVELS = {int(k): v for k, v in S["levels"].items()}                   # 단계번호 → 단계 이름

MANEUVER, COMMAND = 1, 10                                    # 자주 쓰는 전술 번호: 1 기동·직접전투, 10 지휘통제
CATEGORIES = ("전차", "기갑차", "포병", "인원", "미확인")      # 입력에 허용하는 분류
RANKED = ("전차", "미확인")                                   # 랭킹 표에 올리는 분류
COUNT_KEYS = {"전차": "tank", "기갑차": "apc", "포병": "artillery", "인원": "infantry"}  # 상단 카운터 이름
AXIS_LABELS = {"firepower": "화력", "mobility": "기동력", "protection": "방호력"}       # 근거 태그에 쓰는 한글 이름


# ════════════════════════════════════════════════════════════════════
# [1] 표적 1건 판별
# ════════════════════════════════════════════════════════════════════

def spec_of(det):
    """전차이고 기종이 제원표에 있으면 제원 dict, 아니면 None."""
    if det.get("category") != "전차":     # 전차가 아니면 (기갑차·포병 등)
        return None                        # 제원을 찾지 않는다
    return SPECS.get(det.get("model"))     # 제원표에서 기종명으로 찾기 (없으면 None)


def is_unknown(det):
    """미확인 표적인가: 분류가 '미확인'이거나, 전차인데 제원표에 없는 기종."""
    return det.get("category") == "미확인" or (det.get("category") == "전차" and spec_of(det) is None)


# ════════════════════════════════════════════════════════════════════
# [2] 군집 판별: 제대(소대·중대·대대)와 전술
# ════════════════════════════════════════════════════════════════════

def classify_echelon(detections):
    """군집 안 전차+기갑차 대수로 제대를 정한다 → {"n": 대수, "weight": 제대가중치, "name": 제대명}."""
    n = sum(d.get("category") in S["echelon_categories"] for d in detections)  # 전차·기갑차만 센다 (True=1, False=0)
    for lo, weight, name in S["echelons"]:      # 대대(16대) → 중대(5대) → 소대(1대) 순서로
        if n >= lo:                              # 최소 대수 이상이면
            return {"n": n, "weight": weight, "name": name}  # 그 제대로 확정
    return {"n": 0, "weight": 0, "name": "없음"}  # 전투차량이 0대면 가중치 0 → 군집점수도 0


def infer_tactic(detections):
    """군집 전술 자동 추정: 지휘전차가 하나라도 있으면 10번 지휘통제, 없으면 1번 기동·직접전투."""
    tanks = [d for d in detections if d.get("category") == "전차"]           # 전차만 골라서
    return COMMAND if any(d.get("is_commander") for d in tanks) else MANEUVER  # 지휘전차 유무로 결정


def tactic_weights(tactic, is_commander=False):
    """실제로 적용할 전술 번호와 [화력, 기동, 방호] 가중치. 지휘전차는 항상 10번 지휘통제."""
    t = COMMAND if is_commander else tactic     # 지휘전차면 군집 전술과 상관없이 지휘통제
    if t not in TACTIC_WEIGHTS:                 # 11번처럼 가중치가 없는 전술이면
        raise ValueError(f"가중치 미정 전술: {TACTIC_NAMES.get(t, t)}")  # 계산할 수 없으니 오류
    return t, TACTIC_WEIGHTS[t]                 # (전술 번호, [wf, wm, wp])


# ════════════════════════════════════════════════════════════════════
# [3] 전차 1대 점수
# ════════════════════════════════════════════════════════════════════

def firepower_raw(s):
    """화력 원점수 = 구경 × 구경장^0.5 (기준전차로 나누기 전)."""
    return s["caliber_mm"] * s["gun_length"] ** S["gun_length_exp"]


def quant_score(spec):
    """기준전차(M1A1)를 100 으로 놓은 화력·기동력·방호력·종합 점수."""
    b = SPECS[S["base_model"]]                                    # 기준전차 제원
    fire = firepower_raw(spec) / firepower_raw(b)                 # 화력 = 내 화력 원점수 ÷ 기준 원점수
    mob = spec["pw"] / b["pw"]                                    # 기동력 = 내 출력대중량비 ÷ 기준
    armor = (spec["ke"] / b["ke"] + spec["ce"] / b["ce"]) / 2     # 장갑 = 운동에너지탄(KE)·화학탄(CE) 방호 비율의 평균
    height = (b["height"] / spec["height"]) ** S["height_exp"]    # 높이 보정 = (기준높이 ÷ 내 높이)^0.5 → 낮으면 1보다 큼
    prot = armor * height                                         # 방호력 = 장갑 × 높이 보정
    w = S["quant_weights"]                                        # 종합 점수 가중치 (0.5 / 0.3 / 0.2)
    total = fire * w["firepower"] + mob * w["mobility"] + prot * w["protection"]  # 종합(MPI, 참고값)
    return {"firepower": round(fire * 100, 1),                    # 비율 × 100, 소수 1자리
            "mobility": round(mob * 100, 1),
            "protection": round(prot * 100, 1),
            "total": round(total * 100, 1)}


def tank_threat(spec, tactic, is_commander=False):
    """전차 1대 위협도 = 전술 가중치로 화력·기동·방호 점수를 가중평균 (기준전차 ≈ 100)."""
    _, (wf, wm, wp) = tactic_weights(tactic, is_commander)       # 이 전차에 적용할 가중치
    q = quant_score(spec)                                        # 화력·기동·방호 점수 (100 기준)
    weighted = wf * q["firepower"] + wm * q["mobility"] + wp * q["protection"]  # 가중합
    return round(weighted / (wf + wm + wp), 1)                   # 가중치 합으로 나눔 (합이 0.99인 전술도 1로 맞춰짐)


def threat_grade(score):
    """위협도 점수 → 단계 이름 (매우 높음/높음/보통/낮음). 점수가 없으면 None."""
    if score is None:                                    # 미확인·제원 없는 전차는 점수가 없음
        return None                                      # 단계도 없음
    for lo, name in S["threat_grades"]:                  # 100 → 70 → 40 → 0 순서로
        if score >= lo:                                  # 하한 이상이면
            return name                                  # 그 단계


# ════════════════════════════════════════════════════════════════════
# [4] 군집 대응단계 (1 즉시 보고 ~ 4 관심)
# ════════════════════════════════════════════════════════════════════

def cluster_response_level(detections, threats):
    """군집 대응단계. threats = 군집 안 표적들의 위협도 (점수 없으면 None)."""
    threats = [t for t in threats if t is not None]          # 점수가 있는 전차만 남김
    ech = classify_echelon(detections)                        # 제대 (소대·중대·대대)
    t_cluster = max(threats, default=0.0)                     # 군집 위협도 = 가장 위험한 전차의 점수
    score = round(t_cluster * ech["weight"], 1)               # 군집점수 = 군집 위협도 × 제대가중치

    level = 4                                                 # 기본은 4단계
    for th, lv in S["level_thresholds"]:                      # 225 → 150 → 75 순서로
        if score >= th:                                       # 경계 이상이면
            level = lv                                        # 그 단계 (1·2·3)
            break                                             # 처음 만족한 것에서 멈춤

    reasons = [f"{ech['name']}급 {ech['n']}대 ×{ech['weight']}" if ech["n"] else "전투차량 없음",  # 근거 1: 제대
               f"군집점수 {score:g} = 최고 위협도 {t_cluster:g} × {ech['weight']} → {level}단계"]    # 근거 2: 점수 판정
    if level == 4:                                            # 하한 규칙은 4단계일 때만 의미 있음
        floors = []                                           # 적용된 하한 규칙 모음
        if any(is_unknown(d) for d in detections):            # 미확인 표적이 섞여 있으면
            floors.append("미확인 포함 → 4단계 불가")
        if any(t >= S["floor_tank_threat"] for t in threats):  # 위협도 75 이상 전차가 있으면
            floors.append(f"위협도 {S['floor_tank_threat']} 이상 전차 → 4단계 불가")
        if floors:                                            # 하나라도 해당하면
            level = 3                                         # 3단계로 올림
            reasons += floors                                 # 근거에 추가
    return {"level": level, "label": LEVELS[level], "score": score, "t_cluster": t_cluster,
            "echelon": ech, "reasons": reasons}


# ════════════════════════════════════════════════════════════════════
# [5] 보조: 위치 추정 · 입력 검사 · 근거 태그
# ════════════════════════════════════════════════════════════════════

def estimate_position(det, observer):
    """화면 속 박스 위치 → 방위·거리 → 위경도.
    ponytail: mock 추정 — 방위는 박스 가로 위치×시야각, 거리는 박스 높이 반비례. 거리측정·카메라 보정이 생기면 교체."""
    b = det["bbox"]                                                    # 박스 (화면 % 좌표)
    center_x = b["x"] + b["w"] / 2                                     # 박스 가로 중심 (0~100)
    offset = (center_x - 50) / 100 * S["camera_fov_deg"]               # 화면 중심에서 벗어난 각도 (왼쪽 -, 오른쪽 +)
    bearing = (observer.get("heading_deg", 0) + offset) % 360          # 방위 = 카메라 방향 + 벗어난 각도 (0~360)
    dist = S["distance_k"] * 10 / max(b["h"], 1)                       # 거리(m): 박스가 클수록 가까움 (0으로 나누기 방지)
    lat = observer["lat"] + dist * math.cos(math.radians(bearing)) / 111_320  # 북쪽으로 이동 (위도 1도 ≈ 111.32km)
    lon = observer["lon"] + dist * math.sin(math.radians(bearing)) / (111_320 * math.cos(math.radians(observer["lat"])))  # 동쪽으로 이동 (경도 1도는 위도에 따라 짧아짐)
    return {"bearing_deg": round(bearing, 1), "distance_m": round(dist),
            "lat": round(lat, 6), "lon": round(lon, 6), "estimated": True}  # estimated=True → 화면에 '추정 위치'로 표시


def validate(payload):
    """입력 검사 (외부에서 들어오는 값이라 꼭 필요). 문제가 있으면 ValueError."""
    dets = payload.get("detections") if isinstance(payload, dict) else None  # 탐지 목록 꺼내기
    if not isinstance(dets, list):                                     # 리스트가 아니면
        raise ValueError("detections 리스트 필요")
    seen = set()                                                       # 이미 본 tracking_id (중복 검사용)
    for d in dets:                                                     # 탐지 한 건씩
        if not isinstance(d, dict) or not d.get("tracking_id"):        # ID 가 없으면
            raise ValueError("각 탐지에 tracking_id 필요")
        if d["tracking_id"] in seen:                                   # 같은 ID 가 또 나오면
            raise ValueError(f"tracking_id 중복: {d['tracking_id']}")
        seen.add(d["tracking_id"])                                     # 본 목록에 추가
        if d.get("category") not in CATEGORIES:                        # 모르는 분류면
            raise ValueError(f"{d['tracking_id']}: category 는 {'/'.join(CATEGORIES)} 중 하나")
        if not all(isinstance((d.get("bbox") or {}).get(k), (int, float)) for k in "xywh"):  # 박스 x,y,w,h 가 숫자가 아니면
            raise ValueError(f"{d['tracking_id']}: bbox x,y,w,h 숫자 필요")
        c = d.get("confidence")                                        # 탐지 신뢰도 (없어도 됨)
        if c is not None and not (isinstance(c, (int, float)) and not isinstance(c, bool) and 0 <= c <= 1):
            raise ValueError(f"{d['tracking_id']}: confidence 는 0~1 숫자 또는 null")  # 화면이 toFixed() 로 표시
    obs = (payload.get("source") or {}).get("observer") or {}          # 관측 위치
    if not all(isinstance(obs.get(k), (int, float)) for k in ("lat", "lon")):  # 위경도가 숫자가 아니면
        raise ValueError("source.observer.lat/lon 필요")
    h = obs.get("heading_deg")                                         # 카메라 방향 (없으면 0)
    if h is not None and not (isinstance(h, (int, float)) and not isinstance(h, bool)):
        raise ValueError("source.observer.heading_deg 는 숫자")        # 위치 추정 계산에 씀
    return dets                                                        # 통과하면 탐지 목록 돌려줌


def target_tags(row):
    """근거 태그: 이 표적의 위협도를 설명하는 짧은 문장들."""
    tags = []
    if row["is_commander"]:                                    # 지휘전차면
        tags.append("지휘전차")                                 # (지휘통제 가중치가 적용된 이유)
    if row["is_unknown"]:                                      # 미확인이면
        tags.append("미확인 · 분석관 검토" if row["category"] == "미확인" else "제원 없음 · 분석관 검토")
    if row["is_new"]:                                          # 직전 분석에 없던 표적이면
        tags.append("신규")
    if row["scores"]:                                          # 점수가 있는 전차만
        axes = {k: row["scores"][k] for k in AXIS_LABELS}      # 화력·기동·방호 세 점수
        hi = max(axes, key=axes.get)                           # 가장 높은 축
        lo = min(axes, key=axes.get)                           # 가장 낮은 축
        tags.append(f"강점 {AXIS_LABELS[hi]} {axes[hi]:g}")
        tags.append(f"약점 {AXIS_LABELS[lo]} {axes[lo]:g}")
        tags.append(f"{row['tactic_name']} 가중치")              # 어떤 전술 가중치로 계산했는지
    return tags


# ════════════════════════════════════════════════════════════════════
# [6] 전체 분석: 탐지 결과 → 화면용 결과
# ════════════════════════════════════════════════════════════════════

def analyze(payload, prev=None, tactic_overrides=None):
    """payload(탐지 결과) → 화면이 그리는 결과 dict.
    prev             = 직전 분석 결과 (신규 표적·단계 변화 비교용, 없으면 None)
    tactic_overrides = {군집ID: 전술번호} — 지휘관이 화면에서 직접 고른 전술"""
    dets = validate(payload)                                            # 1) 입력 검사
    source = payload["source"]                                          # 영상·관측 위치 정보
    prev_ids = {t["tracking_id"] for t in prev["targets"]} if prev else None  # 직전에 있던 표적 ID 들
    overrides = tactic_overrides or {}                                  # 지정 전술 (없으면 빈 dict)

    groups = {}                                                         # 2) 군집ID → 그 군집 탐지 목록
    for d in dets:
        groups.setdefault(d.get("cluster_id") or "C-1", []).append(d)    # 군집ID 가 없으면 C-1 로

    for cid, t in overrides.items():                                    # 지정 전술이 올바른지 검사
        if cid not in groups:                                           # 없는 군집이면
            raise LookupError(f"군집 없음: {cid}")
        if t not in TACTIC_WEIGHTS:                                     # 가중치 없는 번호면
            raise ValueError(f"가중치 없는 전술 번호: {t} (1~10만 가능)")

    clusters, targets = [], []                                          # 결과를 담을 목록
    for cid, members in groups.items():                                 # 3) 군집마다
        override = overrides.get(cid)                                   # 지휘관이 고른 전술 (없으면 None)
        tactic = override if override else infer_tactic(members)        # 고른 게 없으면 시스템이 추정
        rows = []                                                       # 이 군집의 표적 결과
        for d in members:                                               # 4) 군집 안 표적마다
            spec = spec_of(d)                                           # 제원 (전차가 아니거나 모르는 기종이면 None)
            row = {"tracking_id": d["tracking_id"], "category": d["category"], "model": d.get("model"),
                   "confidence": d.get("confidence"), "bbox": d["bbox"],
                   "is_commander": bool(d.get("is_commander")),
                   "is_unknown": is_unknown(d),
                   "is_new": prev_ids is not None and d["tracking_id"] not in prev_ids,  # 직전 결과에 없었으면 신규
                   "cluster_id": cid, "rank": None, "threat": None, "grade": None, "scores": None, "weights": None,
                   "tactic": tactic, "tactic_name": TACTIC_NAMES[tactic],
                   "position": estimate_position(d, source["observer"])}   # 지도용 추정 위치
            if spec:                                                    # 제원이 있는 전차만 점수 계산
                cmd = row["is_commander"] and not override              # 지휘관이 전술을 골랐으면 그게 우선 (지휘전차 규칙 끔)
                used, (wf, wm, wp) = tactic_weights(tactic, cmd)        # 실제 적용된 전술·가중치
                row["threat"] = tank_threat(spec, tactic, cmd)          # 전차 위협도
                row["scores"] = quant_score(spec)                       # 화력·기동·방호·종합
                row["weights"] = {"firepower": wf, "mobility": wm, "protection": wp}
                row["tactic"], row["tactic_name"] = used, TACTIC_NAMES[used]
                row["grade"] = threat_grade(row["threat"])              # 매우 높음/높음/보통/낮음
            row["tags"] = target_tags(row)                              # 근거 태그
            rows.append(row)

        res = cluster_response_level(members, [r["threat"] for r in rows])  # 5) 군집 대응단계
        for r in rows:                                                  # 표적마다 소속 군집 단계 기록
            r["level"], r["label"] = res["level"], res["label"]
            r["tags"].append(f"{cid} 소속")
        clusters.append(dict(res, cluster_id=cid, tactic=tactic, tactic_name=TACTIC_NAMES[tactic],
                             tactic_source="지휘관 지정" if override else "시스템 추정",
                             track_ids=[r["tracking_id"] for r in rows]))
        targets += rows                                                 # 전체 표적 목록에 합침

    # 6) 랭킹: 전차·미확인만. 위협도 높은 순, 점수 없는 미확인은 맨 뒤 (그 안에서는 군집 단계 순)
    ranked = sorted((t for t in targets if t["category"] in RANKED),
                    key=lambda t: (t["threat"] is None,     # 점수 없는 것(True)이 뒤로
                                   -(t["threat"] or 0),     # 점수 높은 순 (음수로 바꿔서 내림차순)
                                   t["level"]))             # 같으면 심각한 군집(작은 단계) 먼저
    for i, t in enumerate(ranked, 1):                       # 1위부터 번호 매기기
        t["rank"] = i
    targets = ranked + [t for t in targets if t["rank"] is None]  # 순위 없는 표적(기갑차·포병·인원)은 뒤에

    # 7) 상단 카운터
    counts = {"total": len(targets), **{k: 0 for k in COUNT_KEYS.values()},
              "new": sum(t["is_new"] for t in targets)}     # 신규 표적 수
    for t in targets:
        if t["category"] in COUNT_KEYS:                     # 전차·기갑차·포병·인원만
            counts[COUNT_KEYS[t["category"]]] += 1          # 분류별로 하나씩 셈

    # 8) 상단 경보 = 가장 심각한 군집 기준 (단계 작은 것, 같으면 점수 큰 것)
    top = min(clusters, key=lambda c: (c["level"], -c["score"]), default=None)
    level = top["level"] if top else 4                      # 군집이 없으면 4단계
    alert = {"level": level, "label": LEVELS[level],
             "prev_level": prev["alert"]["level"] if prev else None,  # 직전 단계 (변화 표시용)
             "banner": level == 1,                          # 1단계면 화면 상단 빨간 배너
             "message": (f"{top['cluster_id']} {top['echelon']['name']}급 {top['echelon']['n']}대 · {top['tactic_name']}"
                         f" · 군집점수 {top['score']:g}") if top else "탐지 표적 없음"}
    return {"source": source, "counts": counts, "alert": alert, "clusters": clusters, "targets": targets}


# ════════════════════════════════════════════════════════════════════
# [7] 실행: mock 으로 돌려 보고, 원본 코드와 결과가 같은지 검사
# ════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    result = analyze(DATA["mock_input"])                    # JSON 의 mock 12건 분석
    print("순위  ID        기종      위협도  단계       군집")
    for t in result["targets"]:
        if t["rank"] is not None:                           # 랭킹 표에 오르는 것만 출력
            print(f"{t['rank']:>3}  {t['tracking_id']:<9} {t['model'] or '미확인':<9} "
                  f"{t['threat'] if t['threat'] is not None else '-':>6}  {t['grade'] or '산출 불가':<9} "
                  f"{t['cluster_id']} {t['level']}단계")
    for c in result["clusters"]:
        print(f"{c['cluster_id']}: {c['level']}단계 · {' / '.join(c['reasons'])}")

    from threat import analyze as original_analyze, load_mock  # 원본 코드 (같은 폴더의 threat 패키지)
    assert result == original_analyze(load_mock()), "원본과 결과가 다름 — 원본이나 JSON 이 바뀌었으면 이 파일도 고칠 것"
    print("OK: 원본 코드와 결과 동일")
