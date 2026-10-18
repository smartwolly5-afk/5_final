import os

from flask import Flask

from dashboard import bp as dashboard_bp
from db import get_connection
from dictionary import bp as dictionary_bp
from threat_api import bp as threat_bp
from ui import icon

app = Flask(__name__)
app.register_blueprint(dashboard_bp)
app.register_blueprint(dictionary_bp)
app.register_blueprint(threat_bp)
app.jinja_env.globals["icon"] = icon


@app.route("/db-check")
def db_check():
    try:
        conn = get_connection()
        conn.close()
        return {"status": "ok", "message": "DB 연결 성공"}
    except Exception as e:
        app.logger.warning("DB 연결 실패: %s", e)  # 자세한 원인(계정·호스트)은 서버 로그에만
        return {"status": "error", "message": "DB 연결 실패 (서버 로그 확인)"}, 500


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")  # 디버거는 코드 실행이 가능하므로 명시적으로 켤 때만
