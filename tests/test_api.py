import base64

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.vision.detector import Detection, normalize_label, sort_left_to_right

client = TestClient(app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200 and "麻雀アシスト" in r.text


def test_api_analyze():
    r = client.post("/api/analyze", json={"tiles": "1m 2m 3m 5p 6p 7p 2s 3s 4s 7z 7z 9m 9m".split(), "settings": {"is_riichi": True}})
    assert r.status_code == 200
    assert r.json()["shanten"] == 0


def test_api_analyze_bad_tile():
    r = client.post("/api/analyze", json={"tiles": ["9z"]})
    assert r.status_code in (400, 422)


def test_websocket_frame_and_analyze():
    img = np.full((240, 320, 3), 200, np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    data = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "frame", "image": data, "settings": {}})
        msg = ws.receive_json()
        assert msg["type"] == "detection" and msg["tiles"] == []
        ws.send_json({"type": "analyze", "tiles": ["1m"] * 3, "settings": {}})
        assert ws.receive_json()["type"] == "analysis"


def test_label_normalization():
    assert normalize_label("5p_red") == "0p"
    assert normalize_label("3man") == "3m"
    assert normalize_label("chun") == "7z"
    assert normalize_label("unknown") is None


def test_sort_left_to_right_keeps_main_row():
    dets = [Detection(f"{i}m", 0.9, (0.1 * i, 0.5, 0.1 * i + 0.06, 0.6)) for i in range(1, 6)]
    dets.append(Detection("1z", 0.9, (0.5, 0.05, 0.56, 0.15)))  # 上の方にある別の牌
    out = sort_left_to_right(list(reversed(dets)))
    assert [d.tile for d in out] == ["1m", "2m", "3m", "4m", "5m"]
