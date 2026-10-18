"""위협도 대시보드 (Flask Blueprint). 화면·API·보고서 라우트를 모두 여기 둔다. 계산은 threat/ 패키지.

주소
  GET   /                                   대시보드 화면 (templates/dashboard/index.html)
  POST  /api/analyze                        탐지 결과 분석 (본문 비우면 샘플 영상 A → B) → AnalysisResult + videos
  GET   /api/threats[?video=이름]           마지막 분석 결과 (video 를 주면 그 영상으로 화면 전환, 분석 전이면 404)
  GET   /api/threats/<tracking_id>          표적 1건 + 소속 군집
  PATCH /api/clusters/<cluster_id>/tactic   군집 전술 지정 {"tactic": 1~10 또는 null(자동)} → 재분석 결과
  PATCH /api/threats/<tracking_id>/commander 지휘전차 지정·해제 {"is_commander": true|false|null(자동)} → 재분석 결과
  GET   /api/unknowns?limit=20              Unknown 그룹 순위
  GET   /api/unknowns/<group_id>            Unknown 그룹 상세 (출현 기록, crop, 병합 후보)
  GET   /unknowns                           분석관 화면 (Unknown 그룹 순위·crop 갤러리·출현 지도)
  GET   /report?stage=N                     인쇄용 보고서 (stage = 지휘관이 조정한 단계, 없으면 AI 권고)
"""
import json
import logging
from datetime import datetime  # 보고서 작성 시각

from flask import Blueprint, jsonify, render_template, request, url_for

from . import media, threat          # crop 저장, 위협도 계산 패키지 (dashboard/threat/)
from .threat import track as TR      # v2 입력 판별
from . import unknown_registry as registry
from .threat import config as C      # 단계 이름 (LEVELS), 전술 가중치 목록
from .threat.core import TACTIC_NAMES  # 전술 번호 → 이름
from .threat.pipeline import MOCK_V2   # 기본 샘플 (영상 A, B)

bp = Blueprint("dashboard", __name__,
               template_folder="templates",            # dashboard/templates/dashboard/*.html
               static_folder="static",                 # dashboard/static/dashboard.js, dashboard.css
               static_url_path="/dashboard-static")    # 브라우저 주소: /dashboard-static/dashboard.js
log = logging.getLogger(__name__)

# 서버 메모리 상태 (요청 사이에 유지). 영상마다 분석 1건(run)을 들고 있고, 화면은 current 영상을 본다.
# ponytail: 프로세스 메모리 — 서버 재시작 시 사라지고 사용자 간 공유됨. 다중 사용자면 DB(cluster_assessment) 저장으로.
#   (Unknown 레지스트리는 DB 라 재시작해도 남는다)
STATE = {"runs": {},       # 영상 이름 → {"payload", "prev", "result", "overrides": {군집: 전술}, "commanders": {표적: bool}}
         "current": None}  # 화면에 보이는 영상 이름


def _bad(e, code):
    """오류를 JSON 으로 돌려준다 (화면이 error 메시지를 배너로 보여줌)."""
    return jsonify(error=str(e)), code


def _video(payload):
    return str((payload.get("source") or {}).get("video") or "영상")


def _run(video=None):
    """?video= 로 고른 영상(없으면 지금 영상)의 run. 분석 전이면 None."""
    return STATE["runs"].get(video or request.args.get("video") or STATE["current"])


def _attach(result, new):
    """v2 표적에 대표 crop 주소와 Unknown 그룹 id 를 붙이고 내부 필드(_track)를 뗀다.
    new=True(새 분석) 면 Unknown 을 레지스트리에 저장, False(전술·지휘전차 변경 재계산) 면 저장된 그룹만 찾는다."""
    video = _video(result)
    for t in result["targets"]:
        if "_track" not in t:
            continue
        crop = media.track_crop(video, t)
        t["crop_url"] = url_for("static", filename=crop) if crop else None
        if t["status"] == "Unknown":
            try:
                info = registry.record(video, t, result["source"]) if new else {"group_id": registry.lookup(video, t["tracking_id"])}
                t["unknown_group_id"] = info and info["group_id"]
            except Exception as e:                                     # 레지스트리 DB 가 꺼져 있어도 대시보드는 보여 준다
                log.warning("Unknown 레지스트리 저장 실패 (%s %s): %s", video, t["tracking_id"], e)
        del t["_track"]
    return result


def _reanalyze(run, overrides=None, commanders=None):
    """같은 입력을 지정 전술·지휘전차만 바꿔 다시 계산 (실패하면 예외, run 은 그대로)."""
    ov = run["overrides"] if overrides is None else overrides
    cm = run["commanders"] if commanders is None else commanders
    result = _attach(threat.analyze(run["payload"], run["prev"], ov, cm), new=False)
    run.update(overrides=ov, commanders=cm, result=result)
    return result


def _respond(result):
    """화면 응답 = 분석 결과 + 분석해 둔 영상 목록·지금 영상 (A/B 탭)."""
    return jsonify(dict(result, videos=list(STATE["runs"]), video=STATE["current"]))


@bp.get("/")
def index():
    """대시보드 화면. 데이터는 화면이 열린 뒤 JS 가 API 로 가져온다. 전술 선택 목록만 서버에서 채움."""
    tactics = [(n, TACTIC_NAMES[n]) for n in sorted(C.TACTIC_WEIGHTS)]  # 가중치가 있는 전술 (1~10번)
    return render_template("dashboard/index.html", tactics=tactics)


@bp.post("/api/analyze")
def analyze():
    """새 탐지 결과 분석. 본문이 없으면 샘플 영상 A → B 를 차례로 분석 (두 영상이 다 들어가야 레지스트리 병합이 보임)."""
    body = request.get_json(silent=True)
    payloads = [body] if body else [json.loads(f.read_text(encoding="utf-8")) for f in MOCK_V2]
    results = []
    try:
        for p in payloads:                                              # 먼저 전부 계산 (입력 오류면 상태를 안 바꿈)
            if not isinstance(p, dict):
                raise ValueError("본문은 JSON 객체")
            run = STATE["runs"].get(_video(p))
            prev = run["result"] if run else None                       # 같은 영상의 직전 결과 → '신규' 표적 판단
            results.append((p, prev, threat.analyze(p, prev)))          # 새 입력은 지정 전술·지휘전차 없이 시스템 추정부터
    except ValueError as e:
        return _bad(e, 400)                                             # 입력 형식 오류
    for p, prev, result in results:
        STATE["runs"][_video(p)] = {"payload": p, "prev": prev, "result": _attach(result, new=True),
                                    "overrides": {}, "commanders": {}}
    STATE["current"] = _video(payloads[0])                              # 화면은 첫 영상부터
    return _respond(STATE["runs"][STATE["current"]]["result"])


@bp.get("/api/threats")
def threats():
    """마지막 분석 결과 (targets 는 랭킹 순서). ?video= 를 주면 그 영상으로 화면 전환."""
    video = request.args.get("video")
    if video and video not in STATE["runs"]:
        return _bad(f"분석한 적 없는 영상: {video}", 404)
    if video:
        STATE["current"] = video
    run = _run()
    if run is None:
        return _bad("분석 결과 없음. POST /api/analyze 먼저 실행", 404)  # 화면은 404 를 받으면 자동으로 분석 요청
    return _respond(run["result"])


@bp.get("/api/threats/<tracking_id>")
def threat_detail(tracking_id):
    """표적 1건 + 소속 군집."""
    result = (_run() or {}).get("result") or {"targets": [], "clusters": []}
    t = next((t for t in result["targets"] if t["tracking_id"] == tracking_id), None)
    if t is None:
        return _bad(f"표적 없음: {tracking_id}", 404)
    return jsonify(target=t, cluster=next(c for c in result["clusters"] if c["cluster_id"] == t["cluster_id"]))


@bp.patch("/api/clusters/<cluster_id>/tactic")
def set_tactic(cluster_id):
    """'전술 선택': 군집 전술을 지휘관이 지정 → 그 군집 전차 위협도·대응단계 재계산. tactic=null 이면 자동 추정으로 되돌림."""
    run = _run()
    if run is None:
        return _bad("분석 결과 없음", 404)
    tactic = (request.get_json(silent=True) or {}).get("tactic")       # 1~10 또는 None
    overrides = dict(run["overrides"])                                  # 실패하면 원래 값 유지하도록 복사본에 적용
    if tactic is None:
        overrides.pop(cluster_id, None)                                 # 지정 해제
    elif isinstance(tactic, int) and not isinstance(tactic, bool):
        overrides[cluster_id] = tactic
    else:
        return _bad("tactic 은 1~10 정수 또는 null", 400)
    try:
        return _respond(_reanalyze(run, overrides=overrides))
    except LookupError as e:
        return _bad(e, 404)                                             # 없는 군집
    except ValueError as e:
        return _bad(e, 400)                                             # 가중치 없는 전술 번호


@bp.patch("/api/threats/<tracking_id>/commander")
def set_commander(tracking_id):
    """지휘전차 지정·해제 (안테나 오탐·누락을 지휘관이 바로잡음). null 이면 탐지 규칙으로 되돌림. v2 입력만."""
    run = _run()
    if run is None:
        return _bad("분석 결과 없음", 404)
    if not TR.is_v2(run["payload"]):
        return _bad("지휘전차 수정은 프레임 단위(v2) 입력에서만", 400)
    if not any(t["tracking_id"] == tracking_id for t in run["result"]["targets"]):
        return _bad(f"표적 없음: {tracking_id}", 404)
    body = request.get_json(silent=True)
    value = body.get("is_commander", "없음") if isinstance(body, dict) else "없음"
    if value is not None and not isinstance(value, bool):
        return _bad("is_commander 는 true, false, null", 400)
    commanders = dict(run["commanders"])
    if value is None:
        commanders.pop(tracking_id, None)
    else:
        commanders[tracking_id] = value
    return _respond(_reanalyze(run, commanders=commanders))


def _crop_urls(rows, key="path"):
    for r in rows:
        r["url"] = url_for("static", filename=r[key]) if r.get(key) else None
    return rows


@bp.get("/api/unknowns")
def unknowns():
    """Unknown 그룹 순위 (open, 위협도 기준 이상, priority 순)."""
    limit = request.args.get("limit", C.UNKNOWN_RANK_TOP, type=int)
    groups = registry.ranking(max(1, min(limit, 200)))
    return jsonify(groups=_crop_urls(groups, "cover"))


@bp.get("/api/unknowns/<group_id>")
def unknown_detail(group_id):
    """Unknown 그룹 상세: 그룹, 출현 기록(위치), crop, 병합 후보."""
    d = registry.detail(group_id)
    if d is None:
        return _bad(f"그룹 없음: {group_id}", 404)
    _crop_urls([d["group"]], "cover")
    _crop_urls(d["crops"])
    return jsonify(d)


@bp.get("/unknowns")
def unknowns_page():
    """분석관 화면. 데이터는 JS 가 /api/unknowns 로 가져온다."""
    return render_template("dashboard/unknowns.html")


@bp.get("/report")
def report():
    """인쇄용 보고서. ?stage=N 은 지휘관이 화면에서 '단계 조정'한 값 (없으면 AI 권고 단계)."""
    run = _run()
    if run is None:
        return _bad("분석 결과 없음", 404)
    stage = request.args.get("stage", type=int)                         # 숫자가 아니면 None
    if stage not in C.LEVELS:                                           # 1~4 가 아니면 무시
        stage = None
    return render_template("dashboard/report.html", r=run["result"], stage=stage, levels=C.LEVELS,
                           generated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
