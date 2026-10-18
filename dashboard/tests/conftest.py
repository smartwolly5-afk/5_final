"""대시보드 테스트 공통: 사전 DB 없는 데모 환경(TANKLAB_DEMO=1)으로 돌린다.
레지스트리는 테스트마다 새 SQLite 파일, crop 은 임시 폴더에 쓴다 (실제 MySQL·static 폴더를 건드리지 않음)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 5_final 폴더


@pytest.fixture(autouse=True)
def demo_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TANKLAB_DEMO", "1")
    monkeypatch.setenv("TANKLAB_SQLITE", str(tmp_path / "test.sqlite3"))
    from dashboard import media, unknown_registry
    from dashboard.threat import dictdb
    monkeypatch.setattr(media, "OUT", tmp_path / "static")
    monkeypatch.setattr(unknown_registry, "_ready", False)
    dictdb.reset()                     # SQLite 에 tank_threat 가 없으니 demo_seed.json 을 읽게 됨
    yield tmp_path
    dictdb.reset()
