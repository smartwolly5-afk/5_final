import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO = Path(__file__).resolve().parent


class Config:
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "tank")


def data_file(name):
    """데이터 엑셀 위치: TANK_DATA_DIR → 저장소 폴더 → 저장소 바로 위 폴더 순서로 찾는다.
    어디에도 없으면 첫 후보 경로를 돌려준다 (열 때 FileNotFoundError 로 위치가 드러나게)."""
    dirs = [Path(d) for d in [os.getenv("TANK_DATA_DIR")] if d] + [REPO, REPO.parent]
    return next((d / name for d in dirs if (d / name).is_file()), dirs[0] / name)
