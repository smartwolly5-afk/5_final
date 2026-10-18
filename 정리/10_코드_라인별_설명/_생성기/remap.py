"""코드가 바뀐 뒤 문서의 줄 번호 옮기기: python 정리/10_코드_라인별_설명/_생성기/remap.py <예전 커밋> [--write]

- 예전 커밋과 지금 파일을 줄 단위로 비교(difflib)해서, 그대로 남은 줄은 새 줄 번호로 옮긴다.
- 대상: 정리/*.md 의 `파일:줄` 참조, spec_*.py 의 "range"·블록 범위 (spec 의 "file" 기준).
- 바뀐 줄(지워지거나 고쳐진 줄)을 가리키던 참조는 '확인 필요' 로 출력만 한다 → 사람이 고친다.
- --write 없이 돌리면 무엇이 바뀔지만 보여 준다.
"""
import difflib
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DOCS = REPO / "정리"
sys.path.insert(0, str(HERE))
from check_refs import REF, resolve  # noqa: E402


def old_lines(commit, rel):
    r = subprocess.run(["git", "show", f"{commit}:{rel}"], cwd=REPO, capture_output=True)
    return r.stdout.decode("utf-8").splitlines() if r.returncode == 0 else None


def line_map(old, new):
    """예전 줄 번호 → (새 줄 번호, 그대로인지)."""
    m = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        for k in range(i1, i2):
            if tag == "equal":
                m[k + 1] = (j1 + (k - i1) + 1, True)
            else:                                                     # 바뀐 줄: 바뀐 구간의 처음 줄로 (확인 필요)
                m[k + 1] = (min(j1 + (k - i1), max(j2 - 1, j1)) + 1, False)
    return m


def main():
    commit, write = sys.argv[1], "--write" in sys.argv
    maps, review = {}, []

    def mapper(rel):
        if rel not in maps:
            old = old_lines(commit, rel)
            new = (REPO / rel).read_text(encoding="utf-8").splitlines() if (REPO / rel).is_file() else None
            maps[rel] = None if old is None or new is None or old == new else line_map(old, new)
        return maps[rel]

    def move(rel, a, b, where):
        m = mapper(rel)
        if not m:
            return a, b
        (na, oka), (nb, okb) = m.get(a, (a, False)), m.get(b, (b, False))
        if not (oka and okb):
            review.append(f"{where}: {rel}:{a}~{b} → {na}~{nb} (바뀐 줄 — 확인 필요)")
        return na, nb

    for md in DOCS.rglob("*.md"):
        if "_생성기" in md.parts:
            continue
        text = md.read_text(encoding="utf-8")

        def sub(mt):
            f = resolve(mt.group(1))
            if f is None:
                return mt.group(0)
            rel = f.relative_to(REPO).as_posix()
            a = int(mt.group(2)); b = int(mt.group(3) or a)
            na, nb = move(rel, a, b, f"{md.relative_to(DOCS)}")
            return f"{mt.group(1)}:{na}" + (f"~{nb}" if mt.group(3) else "")
        new = REF.sub(sub, text)
        if new != text:
            print(f"참조 수정: {md.relative_to(DOCS)}")
            if write:
                md.write_text(new, encoding="utf-8")

    for spec in HERE.glob("spec_*.py"):
        text = spec.read_text(encoding="utf-8")
        rel = re.search(r'"file":\s*"([^"]+)"', text).group(1)
        if not mapper(rel):
            continue

        def sub2(mt):
            a, b = int(mt.group(2)), int(mt.group(3))
            na, nb = move(rel, a, b, spec.name)
            return f"{mt.group(1)}({na}, {nb})"
        new = re.sub(r'("range":\s*|\(\s*)\((\d+),\s*(\d+)\)', sub2, text)
        if new != text:
            print(f"범위 수정: {spec.name}")
            if write:
                spec.write_text(new, encoding="utf-8")
    print("\n확인 필요:" if review else "\n확인 필요 없음")
    print("\n".join(sorted(set(review))))


if __name__ == "__main__":
    main()
