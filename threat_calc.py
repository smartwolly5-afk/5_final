"""위협도 T 계산 (순수 계산 — DB·엑셀 의존 없음).

대시보드 DB 동기화(sync_threat_db.py)와 사전 화면(dictionary.py)이 같은 코드를 쓴다.
입력: tank_specs 와 같은 컬럼의 DataFrame, 계수 dict, 전술 가중치 [(w_F, w_M, w_P), ...] (1~10번)
"""
import re

import pandas as pd

BASE_ID = "TANK_0120"  # M1A1 Abrams = 기준 전차

# 세대 수동 보정: 대표 행에 '2·3·3.5세대'가 섞였거나 변형 행에 세대가 없는 주력전차
GEN_MANUAL = {  # 새 tank_id (tank_dictionary_v2, 2026-10-13 번호 재부여)
    'TANK_0226': '3세대', 'TANK_0227': '3세대', 'TANK_0121': '3세대', 'TANK_0219': '3세대', 'TANK_0115': '3세대',
    'TANK_0231': '3.5세대', 'TANK_0092': '3세대', 'TANK_0116': '3세대', 'TANK_0162': '3.5세대', 'TANK_0093': '3세대',
    'TANK_0114': '3세대', 'TANK_0221': '3세대', 'TANK_0277': '3세대', 'TANK_0230': '3세대', 'TANK_0220': '3세대',
    'TANK_0224': '2세대', 'TANK_0225': '2세대', 'TANK_0222': '2세대', 'TANK_0214': '2세대', 'TANK_0216': '2세대',
    'TANK_0218': '2세대', 'TANK_0217': '2세대', 'TANK_0161': '3세대', 'TANK_0160': '3세대', 'TANK_0212': '2세대',
    'TANK_0113': '2세대', 'TANK_0213': '2세대', 'TANK_0210': '1세대', 'TANK_0194': '3.5세대', 'TANK_0331': '2세대',
}
# ERA 수동 지정 (주력전차, 해당 변형의 표준 사양 기준) — 참고용 컬럼, 위협도 식에는 반영하지 않음.
# 여기 없는 주력전차는 사전 era 값을 쓰고 '검증 안 됨' 표시
ERA_MANUAL = {
    1: ['T-14 Armata', 'T-90', 'T-90M', 'T-80BV', 'T-80U', 'T-80BVM', 'T-72B', 'T-72B3', 'T-72M4CZ', 'T-72M2 모데르나',
        'T-55AMV', 'PT-91 Twardy', 'T-84', 'T-84 오플롯-M', 'VT-4', 'Type 96', 'Type 99', 'Type 59D', 'MBT-2000',
        'Al Khalid', 'Karrar', '오비옉트 640'],
    0: ['M1A1 Abrams', 'M1 Abrams', 'K2 흑표', 'K1 전차', 'K1A1 전차', 'Leopard 1', 'Leopard 2', 'Leopard 2A4',
        'Leopard 2A5', 'Leclerc', 'Challenger 1', 'Challenger 2', 'C1 Ariete', 'Ariete 1', 'Ariete 2', '90식 전차',
        'Type 10', 'Type 74', 'Merkava', 'Merkava 3', 'Merkava 4', 'Altay', 'Arjun', 'Strv 122', 'T-80', 'T-80B',
        'T-72', 'T-72 Ural', 'T-72A', 'T-72M', 'T-64', 'T-62', 'T-62M', 'T-62 / TR-580 / Tiran', 'T-55', 'T-55AM',
        'Type 59', 'Type 69', 'M60', 'M60A3 TTS Patton', 'M48 Patton', 'CM-11 Brave Tiger', 'Magach 7', 'Chieftain',
        'AMX-30', 'Vickers MBT', '빅커스 전차', 'Panzer 68', 'EE-T1 Osório', 'Osorio T-2', 'TR-125', 'M-84',
        '올리판트 전차', 'Type 85', 'ZTZ88', '88식 전차', '80식 전차', 'MGCS', '레오파르트 3', 'K-3 전차', 'M8 뷰포드',
        'M551 셰리든', 'TTD 전차', '프로제또 M40 모드 65', '69/79식 전차'],
}
# 장갑 수동 보정: 사전 텍스트가 실제와 다른 경우
ARMOR_MANUAL = {'Merkava 3': (0.8, '모듈식 복합장갑(사전 텍스트는 강철) — 3세대 복합'),
                '빅커스 전차': (0.133, 'Vickers MBT 차체 전면 80mm/600 (사전 장갑 텍스트는 2차대전 빅커스 전차 값 혼입)')}

AMMO = [  # (계수 시트 이름, 키워드 정규식) — 텍스트에 여러 개면 계수가 가장 큰 탄
    ('APFSDS', r'APFSDS|날개안정|분리철갑'),
    ('포발사 ATGM', r'ATGM|미사일|missile|포발사|Bastion|Refleks|LAHAT'),
    ('HEAT', r'HEAT|성형작약|대전차고폭'),
    ('APDS', r'APDS'),
    ('APCR', r'APCR|HVAP'),
    ('HESH', r'HESH|HEP\b'),
    ('AP(철갑탄)', r'철갑탄|\bAP\b|\bAPC|APBC|APHE'),
    ('HE', r'\bHE\b|고폭탄'),
]
TYPES = [('초중', '초중전차'), ('주력', '주력전차'), ('중형', '중형전차'), ('중전차', '중전차'),
         ('순항', '순항전차'), ('보병', '보병전차'), ('경전차', '경전차')]
TYPE_ARMOR = {'주력전차': 0.60, '중전차': 0.25, '초중전차': 0.30, '중형전차': 0.12, '보병전차': 0.12,
              '순항전차': 0.08, '경전차': 0.04, '미상': 0.04}
GEN_ARMOR = {'2세대': 0.70, '3세대': 0.80, '3.5세대': 0.90}


def s(v):
    return '' if pd.isna(v) else str(v)


def norm_type(t):
    return next((v for k, v in TYPES if k in s(t)), None)


def gun_cal(text):
    for num, unit in re.findall(r'(\d+(?:[.,]\d+)?)\s*(mm|cm)', s(text)):
        v = float(num.replace(',', '.')) * (10 if unit == 'cm' else 1)
        if 20 <= v <= 200:
            return v, unit
    return None, None


def gun_len(text):
    t = s(text)
    for pat in (r'(\d+(?:\.\d+)?)\s*구경장', r'(\d+(?:\.\d+)?)\s*구경(?!장)', r'L\s*/\s*(\d+(?:\.\d+)?)', r'\bL(\d{2})\b'):
        for m in re.findall(pat, t):
            if 10 <= float(m) <= 80:
                return float(m)
    return None


def gen_of(text):
    gs = sorted(set(re.findall(r'(\d(?:\.5)?)세대', s(text))), key=float)
    return gs


def armor_of(text, gen):
    t = s(text)
    if not t:
        return None, None
    if re.search(r'열화우라늄|depleted|\bDU\b|초밤|chobham|도체스터|dorchester|버링턴', t, re.I):
        return 1.0, '복합+DU'
    if re.search(r'복합|composite|세라믹|ceramic|특수장갑|modular|모듈형|laminate|multilayer|적층|RHA|equivalent|등가', t, re.I):
        return GEN_ARMOR.get(gen, 0.65), '복합장갑(세대 차등)'
    mm = [float(x) for x in re.findall(r'(\d+(?:\.\d+)?)\s*mm', t) if float(x) < 1000]
    if mm:
        return round(min(max(mm) / 600, 0.6), 3), f'강철 {max(mm):g}mm/600'
    if re.match(r'\s*(Armor type|Assembly)\s*:', t) and not re.search(r'armor|장갑', t.split(':', 1)[1], re.I):
        return None, '구조 문구'
    return 0.25, '강철(두께 불명)'


def build_inputs(d):
    rows = []
    d = d.copy()
    d['grp'] = d.tank_type.map(norm_type)
    fam_type = d.dropna(subset=['grp']).groupby('family_name').grp.agg(lambda x: x.mode()[0])
    cal_txt = d.main_gun.map(lambda x: gun_cal(x)[0])
    for i, r in d.iterrows():
        x = {'tank_id': r.tank_id, 'canonical_name': r.canonical_name, 'family_name': r.family_name, '유형 추정': None}
        g = r.grp
        if pd.isna(g):
            if r.family_name in fam_type:
                g, x['유형 추정'] = fam_type[r.family_name], '같은 계열 유형'
            elif (r.main_gun_caliber_mm if pd.notna(r.main_gun_caliber_mm) else cal_txt[i] or 0) >= 100:
                g, x['유형 추정'] = '주력전차', '주력전차(구경 기반 추정)'
            else:
                g = '미상'
        x['유형'] = g
        rows.append(x)
    X = pd.DataFrame(rows, index=d.index)

    def fam_fill(col, key='family_name', how='median'):
        vals = X[col].where(X[col + '_src'].isin(['원본', 'main_gun 텍스트', 'main_gun 텍스트(cm)', '엔진출력÷전투중량',
                                                    'generation 텍스트', 'armor_description', '탄약 텍스트']))
        return vals.groupby(X[key]).transform(how)

    # 구경
    X['cal'], X['cal_src'] = d.main_gun_caliber_mm, d.main_gun_caliber_mm.map(lambda v: '원본' if pd.notna(v) else None)
    for i in X.index[X.cal.isna()]:
        v, u = gun_cal(d.main_gun[i])
        if v:
            X.loc[i, ['cal', 'cal_src']] = v, 'main_gun 텍스트' + ('(cm)' if u == 'cm' else '')
    X['cal_src'] = X.cal_src.astype(object)
    X = X.rename(columns={'cal': '구경', 'cal_src': '구경_src'})
    f = fam_fill('구경')
    m = X.구경.isna() & f.notna()
    X.loc[m, '구경'], X.loc[m, '구경_src'] = f[m], '대체:fam 중앙값'
    X.loc[X.구경.isna(), '구경_src'] = '결측(보완 필요)'
    X['산출가능'] = X.구경.notna()

    # 세대 (탄종 규칙·장갑 등급에 쓰이므로 먼저)
    X['세대'], X['세대_src'] = None, None
    for i in X.index:
        gs = gen_of(d.generation[i])
        if X.tank_id[i] in GEN_MANUAL:
            X.loc[i, ['세대', '세대_src']] = GEN_MANUAL[X.tank_id[i]], '수동 보정(검토 필요)'
        elif len(gs) == 1:
            X.loc[i, ['세대', '세대_src']] = gs[0] + '세대', 'generation 텍스트'
        elif gs:
            X.loc[i, ['세대', '세대_src']] = gs[-1] + '세대', '대체:여러 세대 중 최신(검토 필요)'
    known = X.세대.where(X.세대_src.isin(['generation 텍스트', '수동 보정(검토 필요)']))
    fam_gen = known.groupby(X.family_name).agg(lambda v: v.dropna().mode()[0] if v.notna().any() else None)
    for i in X.index[X.세대.isna()]:
        fg = fam_gen.get(X.family_name[i])
        if isinstance(fg, str):
            X.loc[i, ['세대', '세대_src']] = fg, '대체:fam 중앙값'
        elif X.유형[i] == '주력전차':
            X.loc[i, ['세대', '세대_src']] = '2세대', '대체:주력전차 2세대 가정'
        else:
            X.loc[i, ['세대', '세대_src']] = '구형/미상', '대체:세대 없음(구형)'

    # 구경장
    X['구경장'] = d.main_gun.map(gun_len)
    X['구경장_src'] = X.구경장.map(lambda v: 'main_gun 텍스트' if pd.notna(v) else None)
    f = fam_fill('구경장')
    m = X.구경장.isna() & f.notna()
    X.loc[m, '구경장'], X.loc[m, '구경장_src'] = f[m], '대체:fam 중앙값'
    bins = pd.cut(X.구경, [0, 50, 80, 100, 115, 126, 999], right=False)
    txt = X.구경장.where(X.구경장_src == 'main_gun 텍스트')
    f = txt.groupby(bins, observed=False).transform('median')
    m = X.구경장.isna() & X.구경.notna() & f.notna()
    X.loc[m, '구경장'], X.loc[m, '구경장_src'] = f[m], '대체:cal_bin 중앙값'
    f = txt.groupby(X.유형).transform('median')
    m = X.구경장.isna() & f.notna()
    X.loc[m, '구경장'], X.loc[m, '구경장_src'] = f[m], '대체:type_grp 중앙값'

    # 탄종
    coef = dict(zip([a for a, _ in AMMO], range(len(AMMO), 0, -1)))
    X['탄종'], X['탄종_src'] = None, None
    for i in X.index:
        hits = [a for a, pat in AMMO if re.search(pat, s(d.main_ammunition[i]), re.I)]
        modern = bool(re.search(r'활강|smoothbore', s(d.main_gun[i]), re.I)) or X.세대[i] in ('3세대', '3.5세대')
        if hits and (not modern or 'APFSDS' in hits):
            X.loc[i, ['탄종', '탄종_src']] = max(hits, key=coef.get), '탄약 텍스트'
        elif modern:  # 활강포·3세대 이상은 APFSDS 운용 → 텍스트(예: 'missiles')보다 낮게 잡히지 않게
            X.loc[i, ['탄종', '탄종_src']] = 'APFSDS', '규칙:활강포/3세대 이상'
        elif X.세대[i] in ('1세대', '2세대'):
            X.loc[i, ['탄종', '탄종_src']] = 'APDS', '대체:전후 세대 규칙'
        else:
            X.loc[i, ['탄종', '탄종_src']] = 'AP(철갑탄)', '대체:기본값'

    # 출력대중량비
    X['pw'] = d.power_to_weight_hp_t
    X['pw_src'] = X.pw.map(lambda v: '원본' if pd.notna(v) else None)
    calc = d.engine_power_hp / d.combat_weight_t
    m = X.pw.isna() & calc.notna()
    X.loc[m, 'pw'], X.loc[m, 'pw_src'] = calc[m].round(3), '엔진출력÷전투중량'
    X = X.rename(columns={'pw': '출력대중량비', 'pw_src': '출력대중량비_src'})
    for key, label in (('family_name', '대체:fam 중앙값'), ('유형', '대체:type_grp 중앙값')):
        f = fam_fill('출력대중량비', key)
        m = X.출력대중량비.isna() & f.notna()
        X.loc[m, '출력대중량비'], X.loc[m, '출력대중량비_src'] = f[m].round(3), label
    m = X.출력대중량비.isna()
    X.loc[m, '출력대중량비'], X.loc[m, '출력대중량비_src'] = X.출력대중량비.median(), '대체:전체 중앙값'

    # 장갑
    X['장갑'], X['장갑_src'], X['장갑 규칙'] = None, None, None
    for i in X.index:
        if X.canonical_name[i] in ARMOR_MANUAL:
            v, rule = ARMOR_MANUAL[X.canonical_name[i]]
            X.loc[i, ['장갑', '장갑_src', '장갑 규칙']] = v, '수동 보정(검토 필요)', rule
            continue
        v, rule = armor_of(d.armor_description[i], X.세대[i])
        X.loc[i, ['장갑', '장갑 규칙']] = v, rule
        if v is not None:
            X.loc[i, '장갑_src'] = 'armor_description'
    X['장갑'] = X.장갑.astype(float)
    fam_max = X.장갑.where(X.장갑_src.notna()).groupby([X.family_name, X.세대]).transform('max')  # 같은 계열·같은 세대
    m = (X['장갑 규칙'] == '구조 문구') & fam_max.notna()
    X.loc[m, '장갑'], X.loc[m, '장갑_src'] = fam_max[m], '대체:계열 최대(차체 구조 문구)'
    f = X.장갑.where(X.장갑_src == 'armor_description').groupby(X.family_name).transform('median')
    m = X.장갑.isna() & f.notna()
    X.loc[m, '장갑'], X.loc[m, '장갑_src'] = f[m], '대체:fam 중앙값'
    m = X.장갑.isna()
    X.loc[m, '장갑'], X.loc[m, '장갑_src'] = X.유형[m].map(TYPE_ARMOR), '대체:전차 유형 기본값'
    X.loc[X['장갑 규칙'] == '구조 문구', '장갑 규칙'] = None

    # ERA (참고용, 식에는 미반영)
    era_set = {n: v for v, names in ERA_MANUAL.items() for n in names}
    X['ERA'] = 0
    X['ERA_src'] = '비주력전차 → 0'
    for i in X.index:
        n = X.canonical_name[i]
        if n in era_set:
            X.loc[i, ['ERA', 'ERA_src']] = era_set[n], '수동 지정(검토 필요)'
        elif X.유형[i] == '주력전차':
            X.loc[i, ['ERA', 'ERA_src']] = int('반응' in s(d.era[i]) or 'ERA' in s(d.era[i])), '사전 era(검증 안 됨)'

    # 높이
    X['높이'] = d.height_m
    X['높이_src'] = X.높이.map(lambda v: '원본' if pd.notna(v) else None)
    f = X.높이.groupby(X.family_name).transform('median')
    m = X.높이.isna() & f.notna()
    X.loc[m, '높이'], X.loc[m, '높이_src'] = f[m], '대체:fam 중앙값'
    X.loc[X.높이.isna(), '높이_src'] = '결측→1.0'

    SRC = ['구경_src', '구경장_src', '탄종_src', '세대_src', '출력대중량비_src', '장갑_src', '높이_src']
    X['대체 항목 수'] = X[SRC].apply(lambda r: sum(str(v).startswith(('대체', '결측')) for v in r), axis=1)
    X['신뢰도'] = X['대체 항목 수'].map(lambda n: '상' if n <= 1 else '중' if n <= 3 else '하')
    return X


def py_threat(X, coefs, weights):
    """엑셀 수식과 같은 계산 (검증·정렬용)."""
    F = (X.구경 / coefs['cal']) * (X.구경장 / coefs['len']) ** 0.5 * X.탄종.map(coefs['ammo']) * X.세대.map(coefs['gen'])
    M = X.출력대중량비 / coefs['pw']
    hf = (coefs['h'] / X.높이).pow(0.5).clip(coefs['hmin'], coefs['hmax']).fillna(1.0)
    P = X.장갑 * hf
    out = pd.DataFrame({'F': F, 'M': M, 'P': P})
    for k, (wf, wm, wp) in enumerate(weights, 1):
        out[f'T_{k}'] = (100 * (wf * F + wm * M + wp * P) / (wf + wm + wp)).round(1)
    return out.where(X.산출가능)


NUMERIC = ['main_gun_caliber_mm', 'combat_weight_t', 'engine_power_hp', 'power_to_weight_hp_t', 'height_m']


def compute(d, coefs, weights):
    """사전 DataFrame → 입력값·출처·F·M·P·T_1~T_10. 기준 전차(M1A1)는 계수 값으로 고정해 정확히 1.0 / 100."""
    d = d.copy()
    d[NUMERIC] = d[NUMERIC].apply(pd.to_numeric, errors='coerce')  # MySQL Decimal → float
    X = build_inputs(d.reset_index(drop=True))
    b = X.index[X.tank_id == BASE_ID][0]
    X.loc[b, ['구경', '구경장', '탄종', '세대', '출력대중량비', '장갑', '높이', '산출가능']] =         [coefs['cal'], coefs['len'], 'APFSDS', '3세대', coefs['pw'], 1.0, coefs['h'], True]
    for c in ['구경_src', '구경장_src', '탄종_src', '세대_src', '출력대중량비_src', '장갑_src', '높이_src']:
        X.loc[b, c] = '기준 전차(계수 시트)'
    X.loc[b, ['장갑 규칙', '대체 항목 수', '신뢰도']] = ['복합+DU(기준 1.0)', 0, '상']
    return X.join(py_threat(X, coefs, weights))


def coefs_from_sheets(k, w):
    """위협도_컬럼_산출.xlsx 의 계수(k)·전술가중치(w) 시트 → (coefs, weights 1~10번). 셀 위치는 시트 레이아웃 고정."""
    coefs = {'cal': k['B2'].value, 'len': k['B3'].value, 'pw': k['B4'].value, 'h': k['B5'].value,
             'ammo': {k[f'A{r}'].value: k[f'B{r}'].value for r in range(8, 16)},
             'gen': {k[f'A{r}'].value: k[f'B{r}'].value for r in range(18, 23)},
             'hmin': k['B26'].value, 'hmax': k['B27'].value}
    weights = [(w[f'C{r}'].value, w[f'D{r}'].value, w[f'E{r}'].value) for r in range(2, 12)]
    return coefs, weights
