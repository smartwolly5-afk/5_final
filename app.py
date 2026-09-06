from flask import Flask, render_template

from db import get_connection

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


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
