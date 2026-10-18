import pymysql
from config import Config


def get_connection(with_db: bool = True):
    return pymysql.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        db=Config.DB_NAME if with_db else None,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
