"""05_함수_목록.md 표 생성기: python 정리/10_코드_라인별_설명/_생성기/gen_functions.py

- 함수 이름·줄 범위·입력(인자)은 AST(파이썬 코드 구조 분석)로 실제 파일에서 읽는다.
- '누가 호출하나'는 실제 호출 문장만 센다. 다른 파일에서 부른 경우 import 별칭(J, TR, tdb, ...)이 그 모듈을 가리킬 때만 인정
  (같은 이름 함수가 여러 파일에 있어도 섞이지 않게).
- '하는 일'은 docstring 첫 줄, 없으면 DESC. '출력'은 OUT, 없으면 docstring 의 '→' 뒤.
결과: _05_머리말.md(손으로 쓴 앞부분) + 표 → 정리/05_함수_목록.md (표만 _함수표.md 에도 저장).
"""
import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DOCS = REPO / "정리"

FILES = [  # (파일, 한 줄 설명)
    ("dashboard/threat/pipeline.py", "탐지 결과 → 화면 응답 JSON 조립 (핵심 흐름)"),
    ("dashboard/threat/core.py", "제대·전술·정량 점수·위협도·대응단계 순수 계산"),
    ("dashboard/threat/track.py", "v2 프레임 → 트랙 집계"),
    ("dashboard/threat/judge.py", "Known/Known_Variant/Unknown 판정과 위협도"),
    ("dashboard/threat/dictdb.py", "사전 위협도 DB 조회 (DB 없으면 demo_seed.json)"),
    ("dashboard/__init__.py", "대시보드 화면·API 주소 (Flask Blueprint)"),
    ("dashboard/media.py", "원본 프레임에서 crop 잘라 저장"),
    ("dashboard/unknown_registry.py", "미확인 그룹 매칭·집계·순위 (DB)"),
    ("response_level.py", "DB 기반 대응수준 엔진 (/api/threat)"),
    ("threat_api.py", "/api/threat 주소 (response_level 사용)"),
    ("threat_calc.py", "사전 제원 → F·M·P·T_1~T_10 계산 (pandas)"),
    ("sync_threat_db.py", "사전 → 위협도 테이블 전체 재계산 스크립트"),
    ("threat_db.py", "MySQL/SQLite 공통 DB 접근"),
    ("dictionary.py", "전차 사전 화면 (/dictionary)"),
    ("app.py", "Flask 앱 시작점 (Blueprint 등록)"),
    ("config.py", "DB 접속 설정·데이터 엑셀 위치"),
    ("db.py", "MySQL 연결"),
    ("ui.py", "화면 아이콘(SVG)"),
    ("init_db.py", "schema.sql 적용 스크립트"),
    ("load_xlsx.py", "사전 엑셀 → tank_specs 테이블 적재 스크립트"),
    ("static/mock_frames/make_sample.py", "mock 프레임 1장 합성 (샘플 생성용)"),
    ("static/mock_frames/make_frames.py", "mock 1장 → 영상당 5프레임 확장 (샘플 생성용)"),
    ("dashboard/static/dashboard.js", "대시보드 화면 동작 (브라우저)"),
    ("dashboard/static/unknowns.js", "미확인 레지스트리 화면 동작 (브라우저)"),
]

DESC = {  # docstring 이 없는 함수의 '하는 일'
    "_commander_tag": "지휘전차 근거 문장 ('안테나 탐지 5/5프레임 → 지휘전차 추정' 등)",
    "_num": "값이 숫자인지 (True/False 제외)", "_box_ok": "박스 x·y·w·h 가 숫자이고 폭·높이 > 0 인지",
    "_from_db": "DB 에서 tank_threat·type_threat_summary 전체 읽기", "p75": "값 목록의 상위 25% (numpy percentile 75)",
    "make_seed": "사전 DB 에서 샘플 계열만 골라 demo_seed.json 저장", "_video": "입력의 영상 이름",
    "_crop_urls": "DB 의 crop 경로 → 브라우저 주소", "_now": "지금 시각 문자열", "_unit": "벡터 길이를 1로 (L2 정규화)",
    "_group": "그룹 1행 읽기", "_new_group_id": "다음 그룹 번호 UNK-G0001 형식", "_cover": "그룹 대표 crop 1장 경로",
    "echelon": "대수 → (제대가중치, 제대명)", "level_of": "군집점수 S → 단계 (DB 경계값)", "_tactic": "전술 번호 1~10 검사",
    "load_lookup": "DB 에서 기종 T·유형 p75·경계값 읽기", "assess_and_save": "판정 후 cluster_assessment 에 저장",
    "latest_cluster": "그 군집의 최근 입력·단계", "_actor": "요청한 사람 이름 (X-User 헤더 또는 actor)",
    "_missing": "LookupError → 404 응답", "tank": "기종 1개 위협도 행 (GET /api/threat/tank/<id>)",
    "assess": "군집 대응수준 판정", "tactic": "군집 전술 수정 (PATCH)", "core_target": "핵심표적 지정·해제 (PATCH)",
    "s": "NaN → 빈 문자열", "norm_type": "전차 유형 텍스트 → 표준 유형", "gun_cal": "주포 텍스트 → 구경(mm)",
    "gun_len": "주포 텍스트 → 구경장(L)", "gen_of": "세대 텍스트 → 세대 목록", "armor_of": "장갑 텍스트 → 장갑 계수와 규칙",
    "build_inputs": "사전 → 계산 입력값(구경·구경장·탄종·세대·출력대중량비·장갑·높이)과 출처, 결측 대체",
    "seed": "계수 테이블이 비어 있으면 엑셀에서 1회 채움", "load_coefs": "DB 계수·전술 가중치 읽기",
    "load_dictionary": "사전 읽기 (MySQL tank_specs 또는 엑셀)", "sync": "전체 재계산 → tank_threat·type_threat_summary 교체",
    "v": "pandas 값 → 파이썬 값 (NaN → None)", "demo": "TANKLAB_DEMO=1 인지", "connect": "DB 연결 (MySQL 또는 SQLite)",
    "_sql": "SQLite 면 %s → ? 로 바꿈", "query": "SELECT 실행 → dict 목록", "execute": "INSERT/UPDATE 실행 (커밋)",
    "init_schema": "schema_threat.sql 적용", "get_connection": "MySQL 연결 객체", "db_check": "DB 연결 확인 (GET /db-check)",
    "icon": "아이콘 이름 → SVG", "statements": "schema.sql 을 SQL 문 목록으로", "main": "스크립트 실행 본체",
    "clean": "엑셀 셀 값 정리 (숫자 아닌 값 → NULL)", "move": "원본 좌표 → 잘라 확대한 프레임 좌표", "jitter": "값을 조금 흔듦",
    "unit": "벡터 길이를 1로", "make": "영상 1개를 5프레임으로 확장", "background": "들판 배경 그리기",
    "paste": "전차 사진을 배경에 붙이고 bbox 계산", "antenna": "안테나 선 그리기", "cope_cage": "cope cage 격자 그리기",
    "topk": "분류 후보 목록 만들기", "emb": "임베딩 벡터 만들기 (seed 고정)",
    "helpers": "사전 템플릿에서 쓰는 도우미 함수 등록", "_bad": "ValueError → 400 응답",
    "fam_fill": "원본 값만으로 계열(또는 유형) 중앙값을 구해 결측 대체용으로 돌려줌",
    "is_missing": "값이 비었는지 (None, '', nan, none, null, -)", "text": "결측이면 '', 아니면 앞뒤 공백을 뺀 글자",
    "to_number": "글자를 숫자로 ('1,200', '85%' 도 처리, 못 바꾸면 None)", "fmt_num": "숫자를 소수 2자리까지, 뒤의 0 제거",
    "fmt_bool": "유무 값 → '있음'/'없음' (장비명이면 '있음 (이름)')", "country_meta": "국가 이름 → 국가 코드·영문명·지역",
    "country_of": "전차의 개발국 (없으면 '국가 미상')", "family_of": "전차의 계열 이름 (없으면 정식 명칭·ID)",
    "variant_label": "전차의 변형 이름 (없으면 정식 명칭·ID)", "norm": "검색용으로 공백·기호를 빼고 소문자로",
    "matches": "검색어가 이름·별칭·계열·변형 중 하나에 들어 있는지", "distinct": "필드의 서로 다른 값 목록 (필터용)",
    "year_key": "도입 연도 정렬 키 (연도 없는 것은 뒤로)", "summarize_countries": "국가별 전차 수·대표 전차 카드 목록",
    "country_page": "국가별 전차 목록 페이지 (검색·정렬·통계)", "is_base": "원형(Base) 행인지",
    "hidden": "제원 표에서 숨길 값인지 (결측·0·숨김 단어)", "lines": "' | ' 로 나뉜 값을 줄 목록으로",
    "tank_link": "전차 상세 페이지 링크 HTML", "lineage_cell": "제원 표의 원형/개량형 칸 내용",
    "getJSON": "API 호출 → JSON (오류면 예외)", "show": "그룹 상세 보여 주기 (표·갤러리·지도)",
}
DESC_JS = {"init": "시작: 버튼 연결·데이터 가져오기"}
DESC_FILE = {  # 같은 이름이 여러 파일에 있을 때 (이름@파일)
    "tank@dictionary.py": "전차 1종 상세 페이지", "family@dictionary.py": "예전 계열 주소 → 국가 페이지로 이동",
    "home@dictionary.py": "사전 첫 화면·검색·국가 목록",
}
PREFIX = {"threat_api.py": "/api/threat"}  # Blueprint url_prefix

OUT = {  # 주요 함수의 출력 (손으로 정리)
    "analyze@dashboard/threat/pipeline.py": "AnalysisResult (source·counts·alert·clusters·targets)",
    "_v2_detections": "(탐지 목록, 화면 프레임)", "_target_tags": "근거 태그 문자열 목록",
    "estimate_position": "{bearing_deg, distance_m, lat, lon, estimated}", "_validate": "탐지 목록 (오류면 ValueError)",
    "aggregate": "(트랙 목록, 화면 프레임)", "validate": "프레임 목록 (오류면 ValueError)", "ioa": "0~1 숫자",
    "attach_parts": "붙인 부품 수", "_flag": "{n, m, on}", "_quality": "품질 점수", "_crop_ok": "True/False",
    "_top_k": "[{label, score, family_json}]", "_embedding": "단위 벡터 또는 None", "px_box": "픽셀 bbox", "to_pct": "% bbox",
    "judge": "{status, tank_id, name, family, type_group, evidence, label_notes}",
    "threat_of": "{threat, threat_before_bonus, scores, weights, tactic, source, cope_tag}",
    "_group_p75": "(T, p_p75, 근거 문장)", "resolve": "{tank_id, family, name} 또는 None",
    "family_stats": "{n, t, f, m, p}", "record": "{group_id, similarity, new} 또는 None",
    "_match": "(그룹 id 또는 None, 유사도, 병합 후보)", "ranking": "그룹 목록 (rank·cover 포함)",
    "detail": "{group, sightings, crops} 또는 None", "priority": "순위 점수",
    "cluster_response_level": "{level, label, score, t_cluster, echelon, reasons}",
    "classify_echelon": "{n, weight, name}", "infer_tactic": "Tactic (1 또는 10)", "quant_score": "{firepower, mobility, protection, total}",
    "tactic_weights": "(Tactic, (w_F, w_M, w_P))", "tank_threat": "위협도 숫자", "threat_grade": "단계 이름 또는 None",
    "save_crop": "저장 경로 또는 None", "track_crop": "저장 경로 또는 None", "_attach": "result (crop_url·unknown_group_id 추가)",
    "is_unknown": "True/False", "spec_of": "제원 dict 또는 None", "is_v2": "True/False", "lookup": "그룹 id 또는 None",
    "query": "dict 행 목록", "execute": "새 행 번호(lastrowid)", "demo": "True/False",
    "tank@dashboard/threat/dictdb.py": "tank_threat 행 또는 None", "type_p75": "숫자 또는 None",
    "family_type_group": "유형 이름 또는 None", "compute": "입력값·F·M·P·T_1~T_10 DataFrame",
    "assess@response_level.py": "판정 결과 dict (level, S, T_cluster, E, N, vehicles …)",
    "sync": "{seeded, tanks, computable, summary_rows}", "_bad@dashboard/__init__.py": "(JSON 오류 응답, 상태 코드)",
}


def py_index():
    """파일별 import 별칭 → 모듈 파일 이름 (basename)."""
    alias, imported = {}, {}
    for f, _ in FILES:
        if not f.endswith(".py"):
            continue
        a, names = {}, {}
        for node in ast.walk(ast.parse((REPO / f).read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                for n in node.names:
                    a[n.asname or n.name] = n.name.split(".")[-1]
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")[-1]
                for n in node.names:
                    if node.module and node.level == 0 or (node.level and node.module):
                        names[n.asname or n.name] = (mod, n.name)
                    if not node.module or node.module in ("threat",) or node.level and not node.module:
                        a[n.asname or n.name] = n.name                      # from . import judge as J
                    else:
                        a.setdefault(n.asname or n.name, n.name)            # from .threat import config as C
        alias[f], imported[f] = a, names
    return alias, imported


def py_functions(alias, imported):
    defs, calls = [], []
    for f, _ in FILES:
        if not f.endswith(".py"):
            continue
        tree = ast.parse((REPO / f).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = (ast.get_docstring(node) or "").strip().splitlines()
                deco = [ast.unparse(d) for d in node.decorator_list]
                defs.append({"file": f, "name": node.name, "start": node.lineno, "end": node.end_lineno,
                             "args": ast.unparse(node.args), "doc": doc[0] if doc else "", "deco": deco})
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    calls.append((f, node.lineno, None, fn.id))
                elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                    calls.append((f, node.lineno, fn.value.id, fn.attr))
    mod_of = lambda path: Path(path).stem if Path(path).stem != "__init__" else "dashboard"  # noqa: E731
    for d in defs:
        mine = mod_of(d["file"])
        out = []
        for f, ln, obj, name in calls:
            if name != d["name"] or (f == d["file"] and ln == d["start"]):
                continue
            if obj is None:
                ok = f == d["file"] or imported[f].get(name, (None,))[0] == mine
            else:
                ok = alias[f].get(obj) == mine or (obj == "threat" and mine == "pipeline")
            if ok:
                out.append(f"{f}:{ln}")
        pre = PREFIX.get(d["file"], "")
        routes = [re.sub(r"^(?:bp|app)\.(\w+)\((.*)\)$", lambda m: f"HTTP {m.group(1).upper().replace('ROUTE', 'GET')} {pre}{m.group(2)}", x).replace("'", "")
                  for x in d["deco"] if x.startswith(("bp.", "app.route")) and "processor" not in x and "errorhandler" not in x]
        d["callers"] = routes + sorted(set(out), key=lambda s: (s.split(":")[0], int(s.split(":")[1])))
    return defs


def js_functions():
    out = []
    for f in ("dashboard/static/dashboard.js", "dashboard/static/unknowns.js"):
        lines = (REPO / f).read_text(encoding="utf-8").splitlines()
        heads = [(i + 1, m.group(2), m.group(3)) for i, l in enumerate(lines)
                 for m in [re.match(r"\s*(async\s+)?function\s+(\w+)\s*\(([^)]*)\)", l)] if m]
        for k, (ln, name, args) in enumerate(heads):
            end = next((j for j in range(ln, len(lines)) if lines[j - 1].startswith("}")), ln)
            com = re.search(r"//\s*(.*)$", lines[ln - 1])
            callers = [f"{f}:{i}" for i, l in enumerate(lines, 1) if i != ln
                       and re.search(r"(?<![\w.])" + name + r"\b(?!\s*=)", re.sub(r"//.*$", "", l))]
            out.append({"file": f, "name": name, "start": ln, "end": end, "args": args,
                        "doc": com.group(1) if com else "", "deco": [], "callers": callers})
    return out


def cell(s):
    return str(s).replace("|", "\\|")


def main():
    alias, imported = py_index()
    defs = py_functions(alias, imported) + js_functions()
    md = []
    for f, desc in FILES:
        rows = sorted((d for d in defs if d["file"] == f), key=lambda d: d["start"])
        if not rows:
            continue
        md += [f"### `{f}` — {desc}", "", "| 함수 | 위치(줄) | 입력 | 출력 | 하는 일 | 누가 호출하나 |", "|---|---|---|---|---|---|"]
        for d in rows:
            what = (d["doc"] or DESC_FILE.get(f"{d['name']}@{Path(f).name}")
                    or (DESC_JS.get(d["name"]) if f.endswith(".js") else None) or DESC.get(d["name"], ""))
            out = OUT.get(f"{d['name']}@{f}") or OUT.get(d["name"])
            if not out:
                m = re.search(r"→\s*(.+?)(?:\.|$)", d["doc"])
                out = m.group(1) if m else "—"
            if d["name"] in ("analyze",) and f == "dashboard/__init__.py":
                out = "JSON 응답"
            callers = ", ".join(c.replace("dashboard/threat/", "").replace("dashboard/static/", "").replace("dashboard/", "")
                                for c in d["callers"][:6]) + (" …" if len(d["callers"]) > 6 else "")
            md.append(f"| `{d['name']}` | {d['start']}~{d['end']} | `{cell(d['args'])}` | {cell(out)} | {cell(what)} | {cell(callers) or '— (스크립트 실행·테스트)'} |")
        md.append("")
    here = DOCS / "10_코드_라인별_설명" / "_생성기"
    (here / "_함수표.md").write_text("\n".join(md), encoding="utf-8")
    head = (here / "_05_머리말.md").read_text(encoding="utf-8")           # 05 문서 앞부분 (손으로 쓴 설명·호출 관계도)
    (DOCS / "05_함수_목록.md").write_text(head + "\n".join(md) + "\n", encoding="utf-8")
    print(f"함수 {len(defs)}개")


if __name__ == "__main__":
    main()
