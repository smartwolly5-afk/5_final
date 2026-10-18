"""전차 사전: 전차 제원 원본 데이터 조회 전용 (위협도 계산과 무관)."""
import re
from pathlib import Path
from collections import Counter, defaultdict

from flask import Blueprint, current_app, g, redirect, render_template, request, url_for
from jinja2 import Undefined
from markupsafe import Markup, escape

from db import get_connection
from threat_calc import norm_type

bp = Blueprint("dictionary", __name__)

COLUMNS = [
    "tank_id", "canonical_name", "aliases", "family_name", "variant_name", "tank_type",
    "generation", "origin_country", "manufacturer", "service_year", "operator_countries",
    "crew", "combat_weight_t", "length_m", "width_m", "height_m", "main_gun",
    "main_gun_caliber_mm", "main_ammunition", "effective_range_m", "secondary_weapons",
    "armor_description", "era", "aps", "defense_systems", "engine", "engine_power_hp",
    "power_to_weight_hp_t", "max_road_speed_kmh", "range_km", "sources", "source_count",
    "spec_count", "spec_coverage_%",
]


def load_tanks():
    """전차 제원 원본 데이터 (COLUMNS 키를 가진 dict 목록). MySQL tank_specs 테이블에서 읽습니다."""
    cols = ", ".join(f"`{c}`" for c in COLUMNS)
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT {cols} FROM tank_specs")
                return cur.fetchall()
        finally:
            conn.close()
    except Exception as e:  # DB가 꺼져 있어도 사전 화면은 열리되, '데이터 없음'과 구분되게 경고를 띄운다
        current_app.logger.warning("tank_specs 조회 실패: %s", e)
        g.db_error = True  # dictionary/base.html 이 경고 문구 표시
        return []


LABELS = {
    "tank_id": "ID", "canonical_name": "정식 명칭", "aliases": "별칭", "family_name": "계열",
    "variant_name": "변형", "tank_type": "유형", "generation": "세대", "origin_country": "개발국",
    "manufacturer": "제조사", "service_year": "도입 연도", "operator_countries": "운용국",
    "crew": "승무원", "combat_weight_t": "전투중량", "length_m": "전장", "width_m": "전폭",
    "height_m": "전고", "main_gun": "주포", "main_gun_caliber_mm": "주포 구경",
    "main_ammunition": "주력 탄약", "effective_range_m": "유효 사거리", "secondary_weapons": "부무장",
    "armor_description": "장갑", "era": "반응장갑 (ERA)", "aps": "능동방호 (APS)",
    "defense_systems": "기타 방호 체계", "engine": "엔진", "engine_power_hp": "엔진 출력",
    "power_to_weight_hp_t": "출력 대 중량비", "max_road_speed_kmh": "최고 도로 속도",
    "range_km": "항속거리", "sources": "출처", "source_count": "출처 수", "spec_count": "제원 항목 수",
    "spec_coverage_%": "제원 충족률",
}

UNITS = {
    "crew": "명", "combat_weight_t": "t", "length_m": "m", "width_m": "m", "height_m": "m",
    "main_gun_caliber_mm": "mm", "effective_range_m": "m", "engine_power_hp": "hp",
    "power_to_weight_hp_t": "hp/t", "max_road_speed_kmh": "km/h", "range_km": "km",
}

BOOL_FIELDS = {"era", "aps"}

# 상세 제원표: (섹션, 항목명, 컬럼). 값이 있는 행만 렌더링한다
SPEC_ROWS = [
    ("기본", "정식 명칭", "canonical_name"), ("기본", "별칭", "aliases"), ("기본", "개발국", "origin_country"),
    ("기본", "제조사", "manufacturer"), ("기본", "구분", "tank_type"), ("기본", "세대", "generation"),
    ("기본", "실전배치", "service_year"), ("기본", "운용국", "operator_countries"), ("기본", "승무원", "crew"),
    ("제원", "전장", "length_m"), ("제원", "전폭", "width_m"), ("제원", "전고", "height_m"),
    ("제원", "전투중량", "combat_weight_t"),
    ("화력", "주포", "main_gun"), ("화력", "주포 구경", "main_gun_caliber_mm"), ("화력", "탄약", "main_ammunition"),
    ("화력", "유효 사거리", "effective_range_m"), ("화력", "부무장", "secondary_weapons"),
    ("방호", "장갑", "armor_description"), ("방호", "반응장갑(ERA)", "era"), ("방호", "능동방호(APS)", "aps"),
    ("방호", "기타 방호", "defense_systems"),
    ("기동", "엔진", "engine"), ("기동", "엔진 출력", "engine_power_hp"), ("기동", "출력대중량비", "power_to_weight_hp_t"),
    ("기동", "최고 속도", "max_road_speed_kmh"), ("기동", "항속 거리", "range_km"),
    ("출처", "출처", "sources"),
]
HIDDEN_VALUES = {"정보 없음", "0", "??", "nan", "none", "null", "-", ""}

SEARCH_FIELDS = ("canonical_name", "aliases", "family_name", "variant_name")

# 국가명 → (코드, 영문명, 지역). 국가 카드의 코드 칩·부제에 사용
COUNTRY_INFO = {
    "대한민국": ("KR", "South Korea", "동아시아"), "한국": ("KR", "South Korea", "동아시아"),
    "북한": ("KP", "North Korea", "동아시아"), "중국": ("CN", "China", "동아시아"),
    "일본": ("JP", "Japan", "동아시아"), "미국": ("US", "United States", "북아메리카"),
    "러시아": ("RU", "Russia", "동유럽·북아시아"), "소련": ("SU", "Soviet Union", "동유럽·북아시아"),
    "우크라이나": ("UA", "Ukraine", "동유럽"), "폴란드": ("PL", "Poland", "동유럽"),
    "체코": ("CZ", "Czech Republic", "동유럽"), "독일": ("DE", "Germany", "서유럽"),
    "프랑스": ("FR", "France", "서유럽"), "영국": ("GB", "United Kingdom", "서유럽"),
    "이탈리아": ("IT", "Italy", "남유럽"), "스웨덴": ("SE", "Sweden", "북유럽"),
    "튀르키예": ("TR", "Türkiye", "중동"), "터키": ("TR", "Türkiye", "중동"),
    "이스라엘": ("IL", "Israel", "중동"), "이란": ("IR", "Iran", "중동"),
    "인도": ("IN", "India", "남아시아"), "파키스탄": ("PK", "Pakistan", "남아시아"),
    "체코슬로바키아": ("CS", "Czechoslovakia", "동유럽"), "헝가리": ("HU", "Hungary", "동유럽"),
    "유고슬라비아": ("YU", "Yugoslavia", "남유럽"), "오스트리아": ("AT", "Austria", "서유럽"),
    "스위스": ("CH", "Switzerland", "서유럽"), "네덜란드": ("NL", "Netherlands", "서유럽"),
    "벨기에": ("BE", "Belgium", "서유럽"), "핀란드": ("FI", "Finland", "북유럽"),
    "중화민국": ("TW", "Taiwan (ROC)", "동아시아"), "캐나다": ("CA", "Canada", "북아메리카"),
    "브라질": ("BR", "Brazil", "남아메리카"), "아르헨티나": ("AR", "Argentina", "남아메리카"),
    "남아공": ("ZA", "South Africa", "아프리카"), "호주": ("AU", "Australia", "오세아니아"),
    "뉴질랜드": ("NZ", "New Zealand", "오세아니아"),
}

NA = "정보 없음"
TRUE_WORDS = {"1", "y", "yes", "true", "o", "있음", "유", "보유"}
FALSE_WORDS = {"0", "n", "no", "false", "x", "없음", "무", "미보유"}


# ===== 값 처리 =====
def is_missing(v):
    if v is None or isinstance(v, Undefined):
        return True
    return isinstance(v, str) and v.strip().lower() in ("", "nan", "none", "null", "-")


def text(v):
    return "" if is_missing(v) else str(v).strip()


def to_number(v):
    if is_missing(v) or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().rstrip("%").replace(",", ""))
    except ValueError:
        return None


def fmt_num(n):
    return f"{n:,.2f}".rstrip("0").rstrip(".")


def fmt_bool(v):
    if isinstance(v, (bool, int, float)):
        return "있음" if v else "없음"
    s = str(v).strip()
    if s.lower() in TRUE_WORDS:
        return "있음"
    if s.lower() in FALSE_WORDS:
        return "없음"
    return f"있음 ({s})"  # 유무 대신 장비명이 들어온 경우


def display(field, value):
    """표시 규칙(결측 → 정보 없음, 유무 → 있음/없음, 단위 표기)을 적용한 HTML."""
    if is_missing(value):
        return Markup(f'<span class="na">{NA}</span>')
    num = to_number(value)
    if field in BOOL_FIELDS:
        out = fmt_bool(value)
    elif field == "service_year" and num is not None:
        out = f"{int(num)}년"
    elif field in UNITS and num is not None:
        out = f"{fmt_num(num)} {UNITS[field]}"
    else:
        out = text(value)
    return escape(out)


def country_meta(country):
    code, en, region = COUNTRY_INFO.get(country, ("", "", ""))
    return {"name": country, "code": code or "?", "en": en, "region": region}  # 미등록·국가 미상은 '?'



# ===== 그룹·검색 =====
def country_of(t):
    return text(t.get("origin_country")) or "국가 미상"


def family_of(t):
    return text(t.get("family_name")) or text(t.get("canonical_name")) or text(t.get("tank_id"))


def variant_label(t):
    return text(t.get("variant_name")) or text(t.get("canonical_name")) or text(t.get("tank_id"))


def norm(s):
    return re.sub(r"[\s\-_./]", "", s).lower()


def matches(t, q):
    nq = norm(q)
    return any(nq in norm(text(t.get(f))) for f in SEARCH_FIELDS)


def distinct(tanks, field):
    return sorted({text(t.get(field)) for t in tanks} - {""})


def year_key(t):
    y = to_number(t.get("service_year"))
    return (y is None, y or 0, variant_label(t))


def representative(tanks):
    """대표 전차: 제원 충족률이 가장 높은 것, 같으면 최신 도입."""
    return max(tanks, key=lambda t: (to_number(t.get("spec_coverage_%")) or 0,  # 0~100 (load_xlsx 계산)
                                     to_number(t.get("service_year")) or 0), default=None)


def summarize_countries(tanks):
    groups = defaultdict(list)
    for t in tanks:
        groups[country_of(t)].append(t)
    cards = [{**country_meta(c), "tanks": len(ts), "rep": representative(ts)} for c, ts in groups.items()]
    return sorted(cards, key=lambda c: (c["name"] == "국가 미상", -c["tanks"], c["name"]))  # 국가 미상은 맨 끝


# ===== 라우트 =====
@bp.app_context_processor
def helpers():
    return {"display": display, "LABELS": LABELS, "NA": NA}


@bp.route("/dictionary")
def home():
    tanks = load_tanks()
    country = request.args.get("country", "").strip()
    if country:
        return country_page(tanks, country)

    q = request.args.get("q", "").strip()
    f_type = request.args.get("type", "")
    f_gen = request.args.get("generation", "")
    filtered = [t for t in tanks
                if (not f_type or text(t.get("tank_type")) == f_type)
                and (not f_gen or text(t.get("generation")) == f_gen)]
    results = sorted((t for t in filtered if matches(t, q)), key=variant_label) if q else None
    return render_template(
        "dictionary/home.html",
        variant_label=variant_label, total=len(tanks), q=q, f_type=f_type, f_gen=f_gen,
        types=distinct(tanks, "tank_type"), generations=distinct(tanks, "generation"),
        results=results, countries=summarize_countries(filtered),
        family_of=family_of, country_of=country_of, lin=lineage(tanks) if q else {},
    )


COUNTRY_SORTS = {"name", "type", "kind"}


def name_key(t):
    """한글 이름 먼저, 그다음 영문·숫자 (대소문자 무시)."""
    n = text(t.get("canonical_name"))
    return (not re.match(r"[가-힣]", n), n.casefold())


def country_page(tanks, country):
    lin = lineage(tanks)  # 원형은 다른 나라 행일 수도 있으므로 전체 기준
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "name")
    sort = sort if sort in COUNTRY_SORTS else "name"
    rows = []
    for t in tanks:
        if country_of(t) != country or (q and norm(q) not in norm(text(t.get("canonical_name")))):
            continue
        l = lin[text(t.get("tank_id"))]
        rows.append({"t": t, "type": norm_type(t.get("tank_type")) or "", "lin": l,
                     "kind_key": (l["variant"], text((l["original"] or {}).get("canonical_name")) or l["family"])})
    keys = {"name": lambda r: name_key(r["t"]),
            "type": lambda r: (r["type"] == "", r["type"], name_key(r["t"])),
            "kind": lambda r: (r["kind_key"], name_key(r["t"]))}
    rows.sort(key=keys[sort])
    mine = [t for t in tanks if country_of(t) == country]
    return render_template("dictionary/country.html", country=country_meta(country), rows=rows, total=len(mine),
                           q=q, sort=sort, stats=country_stats(mine))


# 위협도 구간 (정량 위협도, 기준전차 M1A1 = 100). 색은 style.css 의 --stage1~4
THREAT_BINS = [(100, "100 이상", 1), (70, "70 ~ 100", 2), (40, "40 ~ 70", 3), (0, "40 미만", 4)]


def quant_threat(r):
    """사전 위협도 = 100 × (화력 F + 기동력 M + 방호력 P) / 3. 전술 가중치 없는 정량 평가 (기준전차 = 100).
    전술 가중치를 반영한 T_1~T_10 은 대시보드·/api/threat 용이라 사전에서는 쓰지 않는다. 하나라도 없으면 None."""
    fmp = [r.get(a) for a in ("f", "m", "p")]
    return None if any(v is None for v in fmp) else round(100 * sum(float(v) for v in fmp) / 3, 1)


def load_scores(ids):
    """tank_id 목록 → {tank_id: 정량 위협도 또는 None}. tank_threat 이 없으면 빈 dict."""
    if not ids:
        return {}
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT tank_id, f, m, p FROM tank_threat WHERE tank_id IN ({', '.join(['%s'] * len(ids))})", ids)
                return {r["tank_id"]: quant_threat(r) for r in cur.fetchall()}
        finally:
            conn.close()
    except Exception as e:
        current_app.logger.warning("tank_threat 조회 실패: %s", e)
        return {}


def country_stats(tanks):
    """국가 페이지 오른쪽 패널: 전차 종류별 개수, 위협도 구간별 개수, 위협도 상위 3."""
    types = Counter(norm_type(t.get("tank_type")) or "미분류" for t in tanks).most_common()
    scores = load_scores([text(t.get("tank_id")) for t in tanks])
    scored = [(v, t) for t in tanks if (v := scores.get(text(t.get("tank_id")))) is not None]
    bins = [{"label": label, "stage": stage, "n": 0} for _, label, stage in THREAT_BINS]
    for v, _ in scored:
        bins[next(i for i, (lo, _, _) in enumerate(THREAT_BINS) if v >= lo)]["n"] += 1
    bins.append({"label": "산출 불가", "stage": None, "n": len(tanks) - len(scored)})
    top = [{"t": t, "score": v} for v, t in sorted(scored, key=lambda x: -x[0])[:3]]
    return {"types": types, "type_max": max((n for _, n in types), default=1),
            "bins": bins, "bin_max": max((b["n"] for b in bins), default=1) or 1, "top": top}


# ===== 원형·개량형 =====
def is_base(t):
    v = text(t.get("variant_name"))
    return v in ("", "Base") or v.startswith("Family-level")


def lineage(tanks):
    """tank_id → {family, variant(개량형 여부), original(원형 행 또는 None), variants(원형일 때 개량형 목록)}.
    개량형 = 같은 계열에서 variant_name 이 Base 가 아닌 행 (계열에 혼자면 원형으로 본다).
    원형 = 같은 계열의 Base 행 (여럿이면 계열명과 같은 이름 → 가장 이른 도입 순)."""
    fams = defaultdict(list)
    for t in tanks:
        fams[family_of(t)].append(t)
    out = {}
    for fam, ts in fams.items():
        bases = sorted((t for t in ts if is_base(t)), key=lambda t: (text(t.get("canonical_name")) != fam, year_key(t)))
        original = bases[0] if bases else None
        variants = sorted((t for t in ts if len(ts) > 1 and not is_base(t)), key=year_key)
        for t in ts:
            is_var = any(t is v for v in variants)
            out[text(t.get("tank_id"))] = {
                "family": fam, "variant": is_var, "original": original if is_var else None,
                "variants": variants if t is original else [],
            }
    return out


# ===== 상세 제원표 =====
def hidden(v):
    return is_missing(v) or text(v).lower() in HIDDEN_VALUES or to_number(v) == 0


def lines(v):
    return [x.strip() for x in text(v).split("|") if x.strip() and x.strip() not in HIDDEN_VALUES]


def cell(field, v):
    """제원표 한 칸의 HTML. 표시할 값이 없으면 None (그 행을 숨김)."""
    if hidden(v):
        return None
    num = to_number(v)
    if field == "era":
        return None if text(v).lower() in FALSE_WORDS else Markup("장착")
    if field == "aps" and text(v).lower() in FALSE_WORDS:
        return None
    if field == "crew" and num is not None:
        return escape(f"{int(num)}명")
    if field in UNITS and num is not None:
        return escape(f"{fmt_num(num)} {UNITS[field]}")
    if field == "sources":
        src = lines(v)
        return escape(f"{', '.join(src)} ({len(src)}개 출처)")
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    parts = lines(v)
    return Markup("<br>".join(escape(x) for x in parts)) if parts else None


def english_name(t):
    """한글 정식 명칭일 때, 별칭 중 한글이 없는 라틴 이름 (예: K2 흑표 → K2 Black Panther)."""
    if not re.search(r"[가-힣]", text(t.get("canonical_name"))):
        return None
    return next((a for a in lines(t.get("aliases")) if re.search(r"[A-Za-z]{3}", a) and not re.search(r"[가-힣]", a)), None)


IMAGE_DIR = Path(__file__).resolve().parent / "static" / "tank_images"


def tank_image(tank_id):
    """static/tank_images/<tank_id>.(jpg|jpeg|png|webp) 가 있으면 static 기준 경로, 없으면 None (실루엣 표시)."""
    for ext in ("jpg", "jpeg", "png", "webp"):
        if (IMAGE_DIR / f"{tank_id}.{ext}").is_file():
            return f"tank_images/{tank_id}.{ext}"
    return None


THREAT_COLS = "tank_id, canonical_name, family_name, computable, f, m, p, cal_src, len_src, pw_src, armor_src, height_src"
# 지수별 계산 입력 (threat_calc.py_threat 기준) → 산출 불가 툴팁에 쓰는 이름
AXIS_INPUTS = {"f": [("cal_src", "주포 구경"), ("len_src", "구경장")],
               "m": [("pw_src", "출력대중량비(마력·전투중량)")],
               "p": [("armor_src", "장갑"), ("height_src", "차체 높이")]}
AXES = [("f", "화력"), ("m", "기동력"), ("p", "방호력")]


def load_threat(tank_id, family):
    """tank_threat 에서 이 전차 + 같은 계열 행 → (이 전차 행, 계열 다른 행 목록). 테이블이 없으면 (None, [])."""
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT {THREAT_COLS} FROM tank_threat WHERE tank_id = %s OR (family_name = %s AND computable = 1)",
                            (tank_id, family))
                rows = cur.fetchall()
        finally:
            conn.close()
    except Exception as e:  # tank_threat 가 아직 없으면(sync 전) 위협도 패널만 숨김
        current_app.logger.warning("tank_threat 조회 실패: %s", e)
        return None, []
    me = next((r for r in rows if r["tank_id"] == tank_id), None)
    return me, [r for r in rows if r["tank_id"] != tank_id]


def missing_reason(row, axis):
    """산출 불가 이유 (툴팁). threat_calc 는 주포 구경이 없으면 화력·기동·방호·위협도를 모두 산출하지 않는다."""
    if not row["computable"]:
        return "주포 구경 없음 — 구경이 없으면 화력·기동·방호를 모두 산출하지 않음"
    names = [name for col, name in AXIS_INPUTS[axis] if not row.get(col) or str(row[col]).startswith("결측")]
    return (", ".join(names) + " 없음") if names else "계산 입력 부족"


def threat_panel(row, family_rows):
    """화면용 값 (계산은 하지 않고 tank_threat 값을 기준전차 = 100 척도로만 바꾼다)."""
    if row is None:
        return None
    pct = lambda v: None if v is None else round(float(v) * 100, 1)
    score = quant_threat(row)
    peers = [{"name": r["canonical_name"], "tank_id": r["tank_id"], **{a: pct(r[a]) for a, _ in AXES}}
             for r in family_rows if quant_threat(r) is not None]
    bars = [{"key": a, "label": label, "value": pct(row[a]),
             "missing": None if row[a] is not None else missing_reason(row, a)} for a, label in AXES]
    values = [b["value"] for b in bars if b["value"] is not None] + [p[a] for p in peers for a, _ in AXES if p[a] is not None]
    scale = max(150, -(-max(values, default=0) // 50) * 50)  # 50 단위 올림, 최소 150 (기준선 100이 항상 보이게)
    return {"score": score, "delta": None if score is None else round(score - 100, 1),
            "missing": None if score is not None else missing_reason(row, next(a for a, _ in AXES if row[a] is None)),
            "bars": bars, "peers": peers, "scale": scale}


def spec_sections(t, lin):
    """[(섹션, [(항목명, HTML)])] — 빈 섹션은 빠진다."""
    rows = []
    for sec, label, field in SPEC_ROWS:
        html = cell(field, t.get(field))
        if html is not None:
            rows.append((sec, label, html))
        if field == "aliases" and lineage_cell(t, lin):  # 원형/개량형 행은 별칭 다음
            rows.append((sec, *lineage_cell(t, lin)))
    sections = []
    for sec, label, html in rows:
        if not sections or sections[-1][0] != sec:
            sections.append((sec, []))
        sections[-1][1].append((label, html))
    return sections


def tank_link(t):
    return Markup('<a href="{}">{}</a>').format(url_for("dictionary.tank", tank_id=text(t.get("tank_id"))),
                                                 text(t.get("canonical_name")))


def lineage_cell(t, lin):
    if lin["variant"]:
        if lin["original"] is not None:
            return "원형", Markup("{}의 개량형").format(tank_link(lin["original"]))
        return "원형", escape(f"{lin['family']} 계열")
    if lin["variants"]:
        return "개량형", Markup(", ").join(tank_link(v) for v in lin["variants"])
    return None


@bp.route("/dictionary/tank/<tank_id>")  # 예전 주소 호환 (아래 규칙이 먼저 등록돼 url_for 는 새 주소)
@bp.route("/dictionary/<tank_id>")
def tank(tank_id):
    tanks = load_tanks()
    t = next((t for t in tanks if text(t.get("tank_id")) == tank_id), None)
    if t is None:
        return render_template("dictionary/missing.html", what=f"전차 ID '{tank_id}'"), 404
    lin = lineage(tanks)[tank_id]
    shown = sum(cell(f, t.get(f)) is not None for _, _, f in SPEC_ROWS)
    return render_template(
        "dictionary/tank.html", t=t, lin=lin, image=tank_image(tank_id), en=english_name(t), sections=spec_sections(t, lin),
        threat=threat_panel(*load_threat(tank_id, text(t.get("family_name")) or None)), shown=shown, total=len(SPEC_ROWS),
        country=country_of(t),
    )


@bp.route("/dictionary/family/<path:family_name>")
def family(family_name):
    """계열 단계는 없어졌다. 예전 계열 주소는 그 계열이 속한 국가 페이지로 보낸다."""
    countries = Counter(country_of(t) for t in load_tanks() if family_of(t) == family_name)
    if not countries:
        return render_template("dictionary/missing.html", what=f"'{family_name}' 계열"), 404
    return redirect(url_for("dictionary.home", country=countries.most_common(1)[0][0]))
