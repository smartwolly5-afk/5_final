"""라인별 설명 문서 생성기. 코드가 바뀌면 다시 돌린다:
    python 정리/10_코드_라인별_설명/_생성기/gen_lines.py 정리/10_코드_라인별_설명/_생성기/spec_*.py
(줄 번호가 바뀌었으면 spec 의 범위도 고쳐야 한다. 범위가 파일 밖이면 assert 로 멈춘다)

spec 파일은 DOC = {"file", "out", "title", "intro", "sections": [...]} 를 정의한다.
section = {"head": "함수 `x(a)` — 설명", "range": (시작, 끝), "summary": "...", "blocks": [((s, e), "설명"), ...]}
코드와 줄 번호는 실제 파일에서 읽어 넣는다 (문서에 손으로 적지 않음 → 줄 번호가 어긋날 수 없음).
검사: 블록이 section 범위 안인지, 블록끼리 겹치지 않는지, 순서대로인지.
"""
import runpy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]   # 정리/10_코드_라인별_설명/_생성기 → 저장소 루트
OUT = Path(__file__).resolve().parents[1]     # 정리/10_코드_라인별_설명


def render(doc):
    src = (REPO / doc["file"]).read_text(encoding="utf-8").splitlines()
    lang = {"py": "python", "js": "javascript", "sql": "sql", "html": "html", "css": "css"}[doc["file"].rsplit(".", 1)[1]]
    out = [f"# {doc['title']}", "", f"파일: `{doc['file']}` (전체 {len(src)}줄)", "", doc["intro"].strip(), ""]
    width = len(str(len(src)))
    for sec in doc["sections"]:
        a, b = sec["range"]
        assert 1 <= a <= b <= len(src), (doc["file"], sec["head"], a, b)
        out += [f"### {sec['head']} ({Path(doc['file']).name}:{a}~{b})", ""]
        if sec.get("summary"):
            out += [f"이 부분이 하는 일: {sec['summary'].strip()}", ""]
        last = a - 1
        for (s, e), text in sec["blocks"]:
            assert a <= s <= e <= b, (doc["file"], sec["head"], s, e)
            assert s > last, (doc["file"], "블록 겹침/순서", s, last)
            last = e
            lines = [f"{i:>{width}}  {src[i - 1]}" for i in range(s, e + 1) if src[i - 1].strip()]
            out += [f"```{lang}", *lines, "```", f"→ {text.strip()}", ""]
    (OUT / doc["out"]).write_text("\n".join(out) + "\n", encoding="utf-8")
    return doc["out"]


if __name__ == "__main__":
    for spec in sys.argv[1:]:
        print(render(runpy.run_path(spec)["DOC"]))
