# 10. 코드 라인별 설명 — 읽는 순서

핵심 파일은 **한 줄 또는 의미가 같은 몇 줄씩** 실제 코드와 줄 번호를 붙여 설명했습니다. 나머지 파일은 `기타_파일_요약.md` 와 `../05_함수_목록.md`.

| 순서 | 문서 | 파일 | 왜 이 순서 |
|---|---|---|---|
| 1 | `config.md` | `dashboard/threat/config.py` | 모든 숫자가 여기 있어 다른 파일을 읽을 때 기준이 됨 |
| 2 | `core.md` | `dashboard/threat/core.py` | 제대·전술·대응단계 (가장 짧고 기본) |
| 3 | `pipeline.md` | `dashboard/threat/pipeline.py` | **전체 흐름의 중심**. 여기서 다른 파일을 부름 |
| 4 | `track.md` | `dashboard/threat/track.py` | v2: 프레임 → 트랙 |
| 5 | `judge.md` | `dashboard/threat/judge.py` | v2: 판정과 위협도 |
| 6 | `dashboard_init.md` | `dashboard/__init__.py` | 브라우저 주소 → 계산 → 저장 → 응답 |
| 7 | `unknown_registry.md` | `dashboard/unknown_registry.py` | 미확인 그룹 DB |
| 8 | `dashboard_js.md` | `dashboard/static/dashboard.js` | 화면 그리기 |
| 9 | `response_level.md` | `response_level.py` | 별도 DB 엔진 (대시보드와 비교용) |
| — | `기타_파일_요약.md` | 나머지 파이썬·JS·HTML·CSS | 함수 단위 요약 |

## 문법이 처음 나오는 곳

| 문법 | 설명 위치 |
|---|---|
| docstring, 상수, 딕셔너리, 튜플, 주석 | `config.md` |
| import, 딕셔너리 컴프리헨션, IntEnum, 조건 표현식, `dict.get`, 리스트 컴프리헨션, `any`, `next`, 언패킹, `raise` | `core.md` |
| `Counter`, `setdefault`, `lambda`, `zip(*…)`, `set` 으로 중복 검사 | `track.md` |
| `logging`, `dict.fromkeys` | `judge.md` |
| 데코레이터 `@bp.get`, Blueprint, GET/POST/PATCH, `try/except` | `dashboard_init.md` |
| `global`, 행렬 곱 `@`, SQL 자리표시자 `%s`, JOIN, COALESCE | `unknown_registry.md` |
| `const/let`, 화살표 함수, 템플릿 문자열, `async/await`, `fetch`, `addEventListener`, 이스케이프(XSS) | `dashboard_js.md` |

## 문서 다시 만들기 (코드가 바뀌었을 때)

```powershell
# 라인별 설명 (spec_*.py 의 줄 범위가 맞는지 먼저 확인. 범위가 파일 밖이면 멈춤)
python 정리/10_코드_라인별_설명/_생성기/gen_lines.py (Get-ChildItem 정리/10_코드_라인별_설명/_생성기/spec_*.py)
# 05 함수 목록
python 정리/10_코드_라인별_설명/_생성기/gen_functions.py
```

- 코드와 줄 번호는 실행할 때 **실제 파일에서 읽어** 넣으므로 문서에 손으로 쓴 줄 번호가 없습니다(블록 머리의 범위 제외).
- 설명 문장은 `spec_*.py` 에 있습니다. 코드가 바뀌면 범위와 설명을 함께 고치세요.
