"""전차 사전: 전차 제원 원본 데이터 조회 전용 (위협도 계산과 무관)."""
import math
import re
from collections import Counter, defaultdict

from flask import Blueprint, current_app, render_template, request, url_for
from jinja2 import Undefined
from markupsafe import Markup, escape

from db import get_connection

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
    except Exception as e:  # DB가 꺼져 있어도 사전 화면은 빈 상태로 열리도록
        current_app.logger.warning("tank_specs 조회 실패: %s", e)
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

SPEC_GROUPS = [
    ("기본 정보", ["canonical_name", "aliases", "variant_name", "tank_type", "generation",
                "service_year", "crew"]),
    ("크기·중량", ["combat_weight_t", "length_m", "width_m", "height_m"]),
    ("화력", ["main_gun", "main_gun_caliber_mm", "main_ammunition", "effective_range_m",
            "secondary_weapons"]),
    ("방호", ["armor_description", "era", "aps", "defense_systems"]),
    ("기동", ["engine", "engine_power_hp", "power_to_weight_hp_t", "max_road_speed_kmh", "range_km"]),
    ("출처·신뢰도", ["sources", "source_count", "spec_count", "spec_coverage_%"]),
]

# 값이 길어 상세 화면에서 한 줄 전체를 쓰는 항목
WIDE_FIELDS = {"aliases", "main_ammunition", "secondary_weapons", "armor_description",
               "defense_systems", "sources"}

COMPARE_FIELDS = [
    "service_year", "crew", "combat_weight_t", "main_gun", "main_gun_caliber_mm",
    "effective_range_m", "era", "aps", "engine_power_hp", "power_to_weight_hp_t",
    "max_road_speed_kmh", "range_km", "spec_coverage_%",
]

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
}

NA = "정보 없음"
TRUE_WORDS = {"1", "y", "yes", "true", "o", "있음", "유", "보유"}
FALSE_WORDS = {"0", "n", "no", "false", "x", "없음", "무", "미보유"}


# ===== 값 처리 =====
def is_missing(v):
    if v is None or isinstance(v, Undefined):
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if isinstance(v, str) and v.strip().lower() in ("", "nan", "none", "null", "-"):
        return True
    if isinstance(v, (list, tuple)) and not v:
        return True
    return False


def text(v):
    if is_missing(v):
        return ""
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    return str(v).strip()


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


def split_values(v):
    if isinstance(v, (list, tuple)):
        return [text(x) for x in v if text(x)]
    return [s for s in re.split(r"\s*[,;|]\s*", text(v)) if s]


def fmt_bool(v):
    if isinstance(v, (bool, int, float)):
        return "있음" if v else "없음"
    s = str(v).strip()
    if s.lower() in TRUE_WORDS:
        return "있음"
    if s.lower() in FALSE_WORDS:
        return "없음"
    return f"있음 ({s})"  # 유무 대신 장비명이 들어온 경우


def coverage_pct(v):
    n = to_number(v)
    if n is None:
        return None
    return n * 100 if 0 < n <= 1 else n  # 0~1 비율로 저장된 경우도 허용


def coverage_badge(v):
    pct = coverage_pct(v)
    if pct is None:
        return Markup(f'<span class="na">{NA}</span>')
    level = "high" if pct >= 80 else "mid" if pct >= 50 else "low"
    return Markup(f'<span class="cov cov-{level}">신뢰도 {fmt_num(pct)}%</span>')


def display(field, value):
    """표시 규칙(결측 → 정보 없음, 유무 → 있음/없음, 단위 표기)을 적용한 HTML."""
    if field == "spec_coverage_%":
        return coverage_badge(value)
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
    return {"name": country, "code": code or country[:2].upper(), "en": en, "region": region}


# ===== 그룹·검색 =====
def country_of(t):
    return text(t.get("origin_country")) or NA


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
    return max(tanks, key=lambda t: (coverage_pct(t.get("spec_coverage_%")) or 0,
                                     to_number(t.get("service_year")) or 0), default=None)


def summarize_countries(tanks):
    groups = defaultdict(list)
    for t in tanks:
        groups[country_of(t)].append(t)
    cards = [{**country_meta(c), "tanks": len(ts), "families": len({family_of(t) for t in ts}),
              "rep": representative(ts)} for c, ts in groups.items()]
    return sorted(cards, key=lambda c: (-c["tanks"], c["name"]))


def summarize_families(tanks):
    groups = defaultdict(list)
    for t in tanks:
        groups[family_of(t)].append(t)
    cards = []
    for name, ts in groups.items():
        years = sorted(int(y) for y in (to_number(t.get("service_year")) for t in ts) if y is not None)
        calibers = Counter(c for c in (to_number(t.get("main_gun_caliber_mm")) for t in ts) if c is not None)
        cards.append({
            "name": name,
            "variants": len(ts),
            "year_min": years[0] if years else None,
            "years": (f"{years[0]} ~ {years[-1]}" if years[0] != years[-1] else str(years[0])) if years else None,
            "caliber": display("main_gun_caliber_mm", calibers.most_common(1)[0][0] if calibers else None),
            "types": ", ".join(distinct(ts, "tank_type")) or None,
            "generations": ", ".join(distinct(ts, "generation")) or None,
            "rep": representative(ts),
        })
    return cards


def union(tanks, field):
    seen = []
    for t in tanks:
        for v in split_values(t.get(field)):
            if v not in seen:
                seen.append(v)
    return ", ".join(seen) or None


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
        family_of=family_of, country_of=country_of,
    )


def country_page(tanks, country):
    sort = "name" if request.args.get("sort") == "name" else "year"
    tanks = [t for t in tanks if country_of(t) == country]
    families = summarize_families(tanks)
    if sort == "year":
        families.sort(key=lambda f: (f["year_min"] is None, f["year_min"] or 0, f["name"]))
    else:
        families.sort(key=lambda f: f["name"])
    return render_template("dictionary/country.html", country=country_meta(country),
                           families=families, sort=sort, variants=len(tanks), rep=representative(tanks),
                           variant_label=variant_label)


@bp.route("/dictionary/family/<path:family_name>")
def family(family_name):
    return family_page(family_name, request.args.get("v"))


@bp.route("/dictionary/tank/<tank_id>")
def tank(tank_id):
    t = next((t for t in load_tanks() if text(t.get("tank_id")) == tank_id), None)
    if t is None:
        return render_template("dictionary/missing.html", what=f"전차 ID '{tank_id}'"), 404
    return family_page(family_of(t), tank_id)


def family_page(name, selected_id):
    variants = sorted((t for t in load_tanks() if family_of(t) == name), key=year_key)
    if not variants:
        return render_template("dictionary/missing.html", what=f"'{name}' 계열"), 404
    selected = next((v for v in variants if text(v.get("tank_id")) == selected_id), variants[0])

    # 변형 비교표: 첫 번째(가장 이른) 변형과 값이 다른 칸을 강조
    compare = []
    for f in COMPARE_FIELDS:
        cells = [display(f, v.get(f)) for v in variants]
        compare.append({"field": f, "cells": [(c, i > 0 and str(c) != str(cells[0])) for i, c in enumerate(cells)],
                        "differs": any(str(c) != str(cells[0]) for c in cells)})

    countries = Counter(country_of(v) for v in variants)
    country = countries.most_common(1)[0][0]
    return render_template(
        "dictionary/family.html",
        name=name, variants=variants, selected=selected, country=country_meta(country),
        manufacturer=union(variants, "manufacturer"), operators=union(variants, "operator_countries"),
        groups=SPEC_GROUPS, compare=compare, variant_label=variant_label, text=text,
        years=summarize_families(variants)[0]["years"], wide=WIDE_FIELDS,
        tab_url=lambda v: url_for("dictionary.tank", tank_id=text(v.get("tank_id"))),
    )
