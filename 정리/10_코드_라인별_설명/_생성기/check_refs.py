"""정리 문서의 `파일:줄` 참조 검사: python 정리/10_코드_라인별_설명/_생성기/check_refs.py [--show]

- 모든 .md 에서 `이름.py:12`, `이름.js:3~8` 같은 참조를 찾아, 파일이 있고 줄 번호가 파일 길이 안인지 확인한다.
- 같은 이름 파일이 여럿이면(config.py, __init__.py) 경로가 적힌 참조는 그 경로, 아니면 dashboard/threat/config.py 를 우선한다.
- --show 면 참조한 줄의 실제 코드를 같이 출력 (사람이 의미가 맞는지 눈으로 확인).
"""
import random
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DOCS = REPO / "정리"
FILES = [p for p in REPO.rglob("*") if p.suffix in (".py", ".js", ".html", ".sql", ".css", ".json")
         and "정리" not in p.parts and "__pycache__" not in p.parts and ".git" not in p.parts]
PREFER = {"config.py": "dashboard/threat/config.py", "__init__.py": "dashboard/__init__.py"}
REF = re.compile(r"((?:\./)?(?:[\w.]+/)*[\w.]+\.(?:py|js|html|sql|css)):(\d+)(?:~(\d+))?")


def resolve(name):
    if name.startswith("./"):                                   # ./config.py = 저장소 루트 파일
        return REPO / name[2:]
    if name in PREFER:                                          # 이름만 쓰면 대시보드 쪽 (00 문서의 표기 규칙)
        return REPO / PREFER[name]
    hits = [p for p in FILES if p.as_posix().endswith("/" + name) or p.name == name]
    exact = [p for p in hits if p.relative_to(REPO).as_posix() == name]
    if exact:
        return exact[0]
    if name in PREFER:
        return REPO / PREFER[name]
    return hits[0] if len(hits) == 1 else (hits[0] if hits else None)


def main():
    bad, refs = [], []
    for md in DOCS.rglob("*.md"):
        if "_생성기" in md.parts:
            continue
        for ln, line in enumerate(md.read_text(encoding="utf-8").splitlines(), 1):
            for m in REF.finditer(line):
                name, a, b = m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))
                f = resolve(name)
                if f is None:
                    bad.append(f"{md.relative_to(DOCS)}:{ln} 파일 없음 {name}")
                    continue
                n = len(f.read_text(encoding="utf-8").splitlines())
                if not (1 <= a <= b <= n):
                    bad.append(f"{md.relative_to(DOCS)}:{ln} 범위 밖 {name}:{a}~{b} (파일 {n}줄)")
                refs.append((md, ln, f, a, b))
    print(f"참조 {len(refs)}개, 문제 {len(bad)}개")
    print("\n".join(bad))
    if "--show" in sys.argv:
        for md, ln, f, a, b in refs:
            text = f.read_text(encoding="utf-8").splitlines()[a - 1].strip()[:110]
            print(f"{md.relative_to(DOCS)}:{ln} → {f.relative_to(REPO).as_posix()}:{a} | {text}")
    if "--sample" in sys.argv:
        random.seed(int(sys.argv[-1]) if sys.argv[-1].isdigit() else 0)
        for md, ln, f, a, b in random.sample(refs, 10):
            src = f.read_text(encoding="utf-8").splitlines()
            doc = md.read_text(encoding="utf-8").splitlines()[ln - 1].strip()[:160]
            print(f"\n[{md.relative_to(DOCS)}:{ln}] {doc}\n  → {f.relative_to(REPO).as_posix()}:{a}~{b}: " + " / ".join(s.strip()[:90] for s in src[a - 1:min(b, a + 2)]))


if __name__ == "__main__":
    main()
