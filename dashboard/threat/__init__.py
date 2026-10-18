"""위협도 계산 패키지. 바깥(dashboard/__init__.py, 테스트)은 여기서 가져다 쓴다."""
from .core import (Tactic, classify_echelon, cluster_response_level, infer_tactic,  # noqa: F401  단계별 계산 함수
                   quant_score, tank_threat, threat_grade)
from .pipeline import analyze, estimate_position, load_mock  # noqa: F401  응답 조립·위치 추정·mock 입력
