"""위협도 대시보드 (Flask Blueprint). 화면·API·보고서 라우트를 모두 여기 둔다. 계산은 threat/ 패키지.

주소
  GET   /                                  대시보드 화면 (templates/dashboard/index.html)
  POST  /api/analyze                       탐지 결과 분석 (본문 비우면 mock) → AnalysisResult
  GET   /api/threats                       마지막 분석 결과 (분석 전이면 404)
  GET   /api/threats/<tracking_id>         표적 1건 + 소속 군집
  PATCH /api/clusters/<cluster_id>/tactic  군집 전술 지정 {"tactic": 1~10 또는 null(자동)} → 재분석 결과
  GET   /report?stage=N                    인쇄용 보고서 (stage = 지휘관이 조정한 단계, 없으면 AI 권고)
"""
from datetime import datetime  # 보고서 작성 시각

from flask import Blueprint, jsonify, render_template, request

from . import threat                 # 위협도 계산 패키지 (dashboard/threat/)
from .threat import config as C      # 단계 이름 (LEVELS), 전술 가중치 목록
from .threat.core import TACTIC_NAMES  # 전술 번호 → 이름

bp = Blueprint("dashboard", __name__,
               template_folder="templates",            # dashboard/templates/dashboard/*.html
               static_folder="static",                 # dashboard/static/dashboard.js, dashboard.css
               static_url_path="/dashboard-static")    # 브라우저 주소: /dashboard-static/dashboard.js

# 서버 메모리 상태 (요청 사이에 유지).
# ponytail: 프로세스 메모리 1건 — 서버 재시작 시 사라지고 사용자 간 공유됨. 다중 사용자면 DB(cluster_assessment) 저장으로.
STATE = {"payload": None,    # 마지막 입력 (탐지 결과) — 전술을 바꾸면 이걸로 다시 계산
         "prev": None,       # 그 직전 분석 결과 — '신규' 표적 판단 기준
         "result": None,     # 마지막 분석 결과 (화면이 받는 JSON)
         "overrides": {}}    # 지휘관 지정 전술 {cluster_id: 전술번호}


def _bad(e, code):
    """오류를 JSON 으로 돌려준다 (화면이 error 메시지를 배너로 보여줌)."""
    return jsonify(error=str(e)), code


def _run():
    """STATE 의 입력·지정 전술로 분석해 result 를 갱신."""
    STATE["result"] = threat.analyze(STATE["payload"], STATE["prev"], STATE["overrides"])
    return STATE["result"]


@bp.get("/")
def index():
    """대시보드 화면. 데이터는 화면이 열린 뒤 JS 가 API 로 가져온다. 전술 선택 목록만 서버에서 채움."""
    tactics = [(n, TACTIC_NAMES[n]) for n in sorted(C.TACTIC_WEIGHTS)]  # 가중치가 있는 전술 (1~10번)
    return render_template("dashboard/index.html", tactics=tactics)


@bp.post("/api/analyze")
def analyze():
    """새 탐지 결과 분석. 본문이 없으면 mock 입력기 (이미지 분석 모델 연결 전)."""
    payload = request.get_json(silent=True) or threat.load_mock()      # 본문 JSON 또는 mock 파일
    prev = STATE["result"]                                              # 지금 결과가 다음 분석의 '직전 결과'
    try:
        result = threat.analyze(payload, prev)                         # 새 입력은 지정 전술 없이 시스템 추정부터
    except ValueError as e:
        return _bad(e, 400)                                             # 입력 형식 오류
    STATE.update(payload=payload, prev=prev, result=result, overrides={})
    return jsonify(result)


@bp.get("/api/threats")
def threats():
    """마지막 분석 결과 (targets 는 랭킹 순서)."""
    if STATE["result"] is None:
        return _bad("분석 결과 없음. POST /api/analyze 먼저 실행", 404)  # 화면은 404 를 받으면 자동으로 분석 요청
    return jsonify(STATE["result"])


@bp.get("/api/threats/<tracking_id>")
def threat_detail(tracking_id):
    """표적 1건 + 소속 군집."""
    result = STATE["result"] or {"targets": [], "clusters": []}
    t = next((t for t in result["targets"] if t["tracking_id"] == tracking_id), None)
    if t is None:
        return _bad(f"표적 없음: {tracking_id}", 404)
    return jsonify(target=t, cluster=next(c for c in result["clusters"] if c["cluster_id"] == t["cluster_id"]))


@bp.patch("/api/clusters/<cluster_id>/tactic")
def set_tactic(cluster_id):
    """'전술 선택': 군집 전술을 지휘관이 지정 → 그 군집 전차 위협도·대응단계 재계산. tactic=null 이면 자동 추정으로 되돌림."""
    if STATE["payload"] is None:
        return _bad("분석 결과 없음", 404)
    tactic = (request.get_json(silent=True) or {}).get("tactic")       # 1~10 또는 None
    overrides = dict(STATE["overrides"])                                # 실패하면 원래 값 유지하도록 복사본에 적용
    if tactic is None:
        overrides.pop(cluster_id, None)                                 # 지정 해제
    elif isinstance(tactic, int) and not isinstance(tactic, bool):
        overrides[cluster_id] = tactic
    else:
        return _bad("tactic 은 1~10 정수 또는 null", 400)
    try:
        result = threat.analyze(STATE["payload"], STATE["prev"], overrides)
    except LookupError as e:
        return _bad(e, 404)                                             # 없는 군집
    except ValueError as e:
        return _bad(e, 400)                                             # 가중치 없는 전술 번호
    STATE.update(overrides=overrides, result=result)
    return jsonify(result)


@bp.get("/report")
def report():
    """인쇄용 보고서. ?stage=N 은 지휘관이 화면에서 '단계 조정'한 값 (없으면 AI 권고 단계)."""
    result = STATE["result"]
    if result is None:
        return _bad("분석 결과 없음", 404)
    stage = request.args.get("stage", type=int)                         # 숫자가 아니면 None
    if stage not in C.LEVELS:                                           # 1~4 가 아니면 무시
        stage = None
    return render_template("dashboard/report.html", r=result, stage=stage, levels=C.LEVELS,
                           generated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
