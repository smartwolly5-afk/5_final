# TANK

영상에서 탐지된 전차·장갑차의 **위협도**를 보여 주고, 전차 제원 원본 데이터를 **전차 사전**으로 탐색하는 Flask + MySQL 웹 프로토타입입니다.

## 주요 기능

### 위협도 (`/`)
- 영상 위 바운딩 박스와 위협도 순위 표 (High / Medium / Low 필터)
- 표 행이나 박스를 클릭하면 상세 패널이 열림
- 현재는 `app.py`의 목업 데이터(`MOCK_TARGETS`)를 사용

### 전차 사전 (`/dictionary`)
위협도 계산과 별개로, MySQL `tank_specs` 테이블의 제원을 3단계로 탐색합니다.

| 단계 | 주소 | 내용 |
|---|---|---|
| 1. 국가 목록 | `/dictionary` | 국가 카드, 전체 검색(명칭·별칭·계열·변형), 유형·세대 필터 |
| 2. 계열 목록 | `/dictionary?country=러시아` | 계열 카드, 도입 연도순 / 이름순 정렬 |
| 3. 계열 상세 | `/dictionary/family/<family_name>` | 변형 탭, 그룹별 제원, 변형 비교표(다른 값 강조) |
| 변형 바로가기 | `/dictionary/tank/<tank_id>` | 해당 변형 탭이 선택된 계열 상세 |

표시 규칙:
- 값이 없으면 "정보 없음"으로 표시
- `era`, `aps`는 있음 / 없음
- 단위를 함께 표기 (t, m, mm, hp, hp/t, km/h, km)
- `spec_coverage_%`는 신뢰도 배지로 표시: 80% 이상 초록, 50~80% 노랑, 50% 미만 빨강

## 기술 스택

- Python 3.12, Flask 3.0, Jinja2
- MySQL 8, PyMySQL, python-dotenv
- 순수 CSS / JavaScript (프레임워크 없음), Pretendard 글꼴

## 실행 방법

```bash
# 1. 패키지 설치
pip install -r requirements.txt

# 2. DB 접속 정보 설정: .env.example을 .env로 복사한 뒤 비밀번호 입력
cp .env.example .env

# 3. DB, 테이블, 예시 데이터 생성 (다시 실행해도 안전)
python init_db.py

# 4. 서버 실행 → http://127.0.0.1:5000
python app.py
```

DB 연결 확인: http://127.0.0.1:5000/db-check

## 폴더 구조

```
tank/
├── app.py                  # Flask 앱, 위협도 페이지·API, 블루프린트 등록
├── config.py               # .env 설정 읽기
├── db.py                   # MySQL 연결 (get_connection)
├── schema.sql              # tank_specs 테이블 + 예시 데이터
├── init_db.py              # schema.sql 적용 스크립트
├── dictionary.py           # 전차 사전: 데이터 조회, 표시 규칙, 라우트
├── ui.py                   # 공통 아이콘 icon()
├── templates/
│   ├── _nav.html           # 공통 상단 바
│   ├── index.html          # 위협도 페이지
│   └── dictionary/         # 사전 페이지 (base, macros, home, country, family, missing)
├── static/
│   ├── style.css           # 공통 테마 변수 + 위협도 스타일
│   ├── dictionary.css      # 사전 스타일
│   └── dashboard.js        # 위협도 표·상세 패널 동작
└── TANK_개발가이드.docx     # 구조 설명, 처음부터 만들기, 수정 방법
```

## 데이터

`tank_specs` 테이블 컬럼:

`tank_id`, `canonical_name`, `aliases`, `family_name`, `variant_name`, `tank_type`, `generation`, `origin_country`, `manufacturer`, `service_year`, `operator_countries`, `crew`, `combat_weight_t`, `length_m`, `width_m`, `height_m`, `main_gun`, `main_gun_caliber_mm`, `main_ammunition`, `effective_range_m`, `secondary_weapons`, `armor_description`, `era`, `aps`, `defense_systems`, `engine`, `engine_power_hp`, `power_to_weight_hp_t`, `max_road_speed_kmh`, `range_km`, `sources`, `source_count`, `spec_count`, `spec_coverage_%`

작성 규칙:
- 같은 `family_name`을 가진 행은 한 계열의 변형으로 묶임
- `aliases`, `operator_countries`처럼 값이 여러 개인 칸은 쉼표로 구분
- `spec_coverage_%`는 SQL에서 반드시 백틱으로 감싸야 함

예시 데이터는 K2 흑표 1건이며, 출처 검증 전 임의 값입니다.

## 수정 가이드

컬럼 추가, 표시 규칙 변경, 테마 색상, 메뉴 추가 등 자주 하는 수정 방법은 **`TANK_개발가이드.docx`**에 정리되어 있습니다.

간단 요약:
- **제원 항목 추가:** DB `ALTER TABLE`을 실행한 뒤 `dictionary.py`의 `COLUMNS`, `LABELS`, `UNITS`, `SPEC_GROUPS`에 추가
- **색상 변경:** `static/style.css` 맨 위 `:root` 변수 수정
- **메뉴 탭 추가:** `templates/_nav.html`에 링크 추가
