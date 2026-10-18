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
        return {"status": "error", "message": str(e)}, 500


if __name__ == "__main__":
    app.run(debug=True)
