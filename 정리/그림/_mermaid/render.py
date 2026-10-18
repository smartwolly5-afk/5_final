"""정리 문서의 Mermaid 그림 → PNG: python 정리/그림/_mermaid/render.py

mermaid-cli(mmdc)를 쓸 수 없는 환경이라 Chrome 의 화면 없는 모드(headless)로 그린다.
- 원본은 각 md 안의 ```mermaid 블록 (여기에 따로 두지 않음 → 문서와 그림이 어긋나지 않음)
- 가로 1800px, 흰 배경, 한글 글꼴(맑은 고딕). 위아래 빈 공간은 잘라 냄
- 인터넷 필요 (Mermaid 를 CDN 에서 받음)
"""
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

HERE = Path(__file__).resolve().parent
DOCS = HERE.parents[1]
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
TARGETS = [  # (문서, 몇 번째 mermaid 블록, PNG 이름)
    ("02_전체_흐름도.md", 0, "흐름도_1_큰그림"),
    ("02_전체_흐름도.md", 1, "흐름도_2_판정"),
    ("02_전체_흐름도.md", 2, "흐름도_3_요청"),
    ("02_전체_흐름도.md", 3, "흐름도_4_엔진통합"),
    ("05_함수_목록.md", 0, "호출관계도_analyze"),
    ("07_DB_구조.md", 0, "ERD"),
]
PAGE = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{{margin:0;background:#fff}} #d{{width:1700px;margin:40px 50px}} #d svg{{width:100%;height:auto;max-width:none!important}}</style>
</head><body><div id="d" class="mermaid">{src}</div>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>mermaid.initialize({{startOnLoad:true, theme:"default",
  themeVariables:{{fontFamily:"Malgun Gothic, Pretendard, sans-serif", fontSize:"18px"}}, flowchart:{{useMaxWidth:true}}}});</script>
</body></html>"""


def blocks(md):
    return re.findall(r"```mermaid\n(.*?)```", (DOCS / md).read_text(encoding="utf-8"), re.S)


def trim_vertical(path):
    im = Image.open(path).convert("RGB")
    diff = ImageChops.difference(im, Image.new("RGB", im.size, "white")).getbbox()
    if diff:
        top, bottom = max(diff[1] - 30, 0), min(diff[3] + 30, im.height)
        im.crop((0, top, im.width, bottom)).save(path)
    return Image.open(path).size


def main():
    tmp = Path(tempfile.mkdtemp())
    for md, i, name in TARGETS:
        html = tmp / f"{i}.html"
        html.write_text(PAGE.format(src=blocks(md)[i]), encoding="utf-8")
        shot = tmp / "shot.png"
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={tmp / 'prof'}",
                        "--window-size=1800,4000", "--virtual-time-budget=10000", f"--screenshot={shot}", html.as_uri()],
                       check=True, capture_output=True)
        out = HERE.parent / f"{name}.png"
        out.write_bytes(shot.read_bytes())
        print(name, trim_vertical(out))


if __name__ == "__main__":
    main()
