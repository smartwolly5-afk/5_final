from flask import Flask, jsonify, render_template

from db import get_connection
from dictionary import bp as dictionary_bp
from ui import icon

app = Flask(__name__)
app.register_blueprint(dictionary_bp)
app.jinja_env.globals["icon"] = icon


# 프로토타입용 목업 데이터. DB 테이블이 정해지면 이 부분을 쿼리 결과로 교체합니다.
MOCK_ANALYSIS = {
    "video": "ukraine_tank_001.mp4",
    "captured_at": "2024-03-15",
    "source": "OSINT",
    "duration": "01:35",
    "current": "00:12",
}

MOCK_TARGETS = [
    {
        "id": "Tank-02",
        "type": "전차",
        "damage_types": ["화재", "포탑 손상"],
        "threat": "High",
        "confidence": 0.87,
        "triage": ["회수 검토", "안전확인"],
        "severity_level": 4,
        "severity_note": "포탑 및 차체 화재로 기능 손실 가능성이 높음",
        "actions": [
            "차체 상부에서 화재로 인한 연기와 불꽃이 탐지됨",
            "포탑 회전에 손실 및 구조 변형이 확인됨",
            "유사 사례분석 시 전력 파괴 가능성 높음",
            "현장 상황을 고려하여 회수 여부를 신중히 검토",
        ],
        "bbox": {"x": 37, "y": 33, "w": 15, "h": 21},
    },
    {
        "id": "Tank-01",
        "type": "전차",
        "damage_types": ["경미한 손상"],
        "threat": "Low",
        "confidence": 0.91,
        "triage": ["안전확인"],
        "severity_level": 1,
        "severity_note": "외관상 경미한 손상으로 기동 가능성 있음",
        "actions": [
            "차체 외부에 경미한 파편 흔적이 탐지됨",
            "포탑 및 궤도에서 구조적 손상은 확인되지 않음",
            "접근 전 주변 안전 상황 확인 필요",
        ],
        "bbox": {"x": 18, "y": 19, "w": 10, "h": 15},
    },
    {
        "id": "Tank-03",
        "type": "전차",
        "damage_types": ["경미한 손상"],
        "threat": "Low",
        "confidence": 0.83,
        "triage": ["사람 재검토"],
        "severity_level": 1,
        "severity_note": "손상 판단 근거가 부족하여 전문가 확인 필요",
        "actions": [
            "영상 해상도 한계로 손상 부위 판별이 불확실함",
            "AI 탐지 결과에 대한 전문가 재검토 권장",
        ],
        "bbox": {"x": 73, "y": 74, "w": 14, "h": 21},
    },
    {
        "id": "APC-01",
        "type": "장갑차",
        "damage_types": ["차체 손상"],
        "threat": "Medium",
        "confidence": 0.76,
        "triage": ["추가 기술분석"],
        "severity_level": 3,
        "severity_note": "차체 측면 손상으로 부분 기능 저하 예상",
        "actions": [
            "차체 측면에 관통 흔적으로 보이는 손상이 탐지됨",
            "내부 손상 정도는 영상만으로 판단이 어려움",
            "추가 기술분석을 통한 정밀 평가 필요",
        ],
        "bbox": {"x": 63, "y": 42, "w": 15, "h": 18},
    },
]


@app.route("/")
def index():
    return render_template("index.html", analysis=MOCK_ANALYSIS)


@app.route("/api/targets")
def targets():
    return jsonify(MOCK_TARGETS)


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
