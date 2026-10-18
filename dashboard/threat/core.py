"""전차 1대 위협도까지의 단계별 함수 (순수 계산 — Flask·DB 의존 없음, 화면 코드와 분리).

탐지 결과 1건(dict) 형식:
  {"tracking_id": "Tank-03",                       # 추적 ID (영상 안에서 고유)
   "category": "전차"|"기갑차"|"포병"|"인원"|"미확인",  # 분류
   "model": "T-90M" 또는 None,                      # 기종명 (tank_specs.json 키와 맞으면 제원 조회)
   "confidence": 0.93,                              # 탐지 신뢰도 0~1
   "bbox": {"x", "y", "w", "h"},                    # 화면 기준 % 좌표
   "is_commander": false,                           # 지휘전차 여부
   "cluster_id": "C-1"}                             # 군집 ID (없으면 C-1)

계산 순서: infer_tactic → quant_score → tank_threat → threat_grade
군집 대응단계(제대·군집점수·하한)는 response_level.assess 하나로 판정한다 (변환은 adapter.py).
"""
import json                    # tank_specs.json 읽기
from enum import IntEnum       # 전술 번호를 이름 있는 정수로
from pathlib import Path       # 이 파일 옆의 JSON 경로 계산

from . import config as C      # 가중치·경계값 (config.py)

CATEGORIES = ("전차", "기갑차", "포병", "인원", "미확인")  # 입력 검증에 쓰는 허용 분류
SPECS = {k: v for k, v in                                   # 기종명 → 제원 dict
         json.loads(Path(__file__).with_name("tank_specs.json").read_text(encoding="utf-8")).items()
         if not k.startswith("_")}                          # "_note" 같은 설명 키는 제외


class Tactic(IntEnum):
    """11개 전술 기능 번호. infer_tactic 은 1·10번만 자동 추정하고, 나머지는 화면의 '전술 선택'으로 지정한다."""
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
    SUSTAINMENT = 11     # 전투근무지원 (화력 0 → 전차에는 쓰지 않음, 가중치 없음)


TACTIC_NAMES = {1: "기동·직접전투", 2: "병력수송·지원", 3: "대전차", 4: "간접화력", 5: "장거리화력", 6: "방공",  # 화면 표시용 이름
                7: "정찰·표적획득", 8: "공병", 9: "CBRN·연막차폐", 10: "지휘통제", 11: "전투근무지원"}


def spec_of(det):
    """전차이고 기종이 제원표에 있으면 제원 dict, 아니면 None."""
    return SPECS.get(det.get("model")) if det.get("category") == "전차" else None  # 전차가 아니면 제원 조회 안 함


def is_unknown(det):
    """미확인 표적: 분류가 '미확인'이거나, 전차인데 제원표에 없는 기종. v2 입력은 판정 결과(status)를 따른다."""
    if det.get("status"):                                    # v2: Known / Known_Variant / Unknown (judge.py)
        return det["status"] == "Unknown"
    return det.get("category") == "미확인" or (det.get("category") == "전차" and spec_of(det) is None)


def infer_tactic(detections):
    """군집 전술 자동 추정 (전차만 봄): 지휘전차가 있으면 ⑩지휘통제, 없으면 ①기동·직접전투."""
    tanks = [d for d in detections if d.get("category") == "전차"]                   # 전차만 추림
    return Tactic.COMMAND if any(d.get("is_commander") for d in tanks) else Tactic.MANEUVER


def _firepower(s):
    """화력 원점수 = 구경 × 구경장^지수 (기준전차로 나누기 전 값)."""
    return s["caliber_mm"] * s["gun_length"] ** C.GUN_LENGTH_EXP


def quant_score(spec, base=None):
    """정량 점수: 기준전차(M1A1) = 100 인 화력·기동력·방호력·종합(MPI).
    열상·사격통제·안정기·장갑종류·반응장갑 필드는 제원에 남아 있지만 지금은 계산에 쓰지 않는다."""
    b = base or SPECS[C.BASE_MODEL]                                   # 비교 기준 제원 (기본 M1A1)
    fire = _firepower(spec) / _firepower(b)                           # 화력 비율
    mob = spec["pw"] / b["pw"]                                        # 기동력 비율 = 출력대중량비 비
    prot = ((spec["ke"] / b["ke"] + spec["ce"] / b["ce"]) / 2         # 방호력 = KE·CE 정면방호 비율의 평균
            * (b["height"] / spec["height"]) ** C.HEIGHT_EXP)         #        × 차체 높이 보정
    w = C.QUANT_WEIGHTS                                               # 종합 점수 가중치 (0.5/0.3/0.2)
    total = fire * w["firepower"] + mob * w["mobility"] + prot * w["protection"]  # MPI 종합 (참고값)
    return {k: round(v * 100, 1) for k, v in                          # 비율 × 100, 소수 1자리
            (("firepower", fire), ("mobility", mob), ("protection", prot), ("total", total))}


def tactic_weights(tactic, is_commander=False):
    """적용할 전술과 (화력, 기동, 방호) 가중치. 지휘전차는 항상 ⑩지휘통제 가중치."""
    t = Tactic.COMMAND if is_commander else Tactic(tactic)   # 지휘전차면 전술 무시하고 지휘통제
    if t not in C.TACTIC_WEIGHTS:                             # 11번 등 가중치 없는 전술
        raise ValueError(f"가중치 미정 전술: {TACTIC_NAMES[t]}")
    return t, C.TACTIC_WEIGHTS[t]


def tank_threat(spec, tactic, is_commander=False):
    """전차 1대 위협도 = 전술 가중치로 화력·기동·방호 정량 점수를 가중평균 (기준전차 ≈ 100)."""
    _, (wf, wm, wp) = tactic_weights(tactic, is_commander)    # 전술별 가중치
    q = quant_score(spec)                                     # 화력·기동·방호 (100 기준)
    return round((wf * q["firepower"] + wm * q["mobility"] + wp * q["protection"]) / (wf + wm + wp), 1)  # 합으로 나눠 정규화


def threat_grade(score):
    """전차 1대 위협도 단계 이름 (매우 높음/높음/보통/낮음). 점수가 없으면 None."""
    if score is None:                                         # 미확인·제원 없음 → 단계 없음
        return None
    return next(name for lo, name in C.THREAT_GRADES if score >= lo)  # 위에서부터 처음 만족하는 구간
