import base64

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.vision.detector import Detection, normalize_label, sort_left_to_right
from tests.synth import table_image

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


def _jpeg(img) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return buf.tobytes()


def test_websocket_legacy_frame_and_analyze():
    img = np.full((240, 320, 3), 200, np.uint8)
    data = "data:image/jpeg;base64," + base64.b64encode(_jpeg(img)).decode()
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "frame", "image": data})
        msg = ws.receive_json()
        assert msg["type"] == "detection" and msg["hand"] is None
        ws.send_json({"type": "analyze", "tiles": ["1m"] * 3})
        assert ws.receive_json()["type"] == "analysis"


def test_stream_teach_then_auto_recognize_and_follow_changes():
    """映像を流す → 教える → 自動で手牌を読み分析 → 手牌が変わったら分析し直す。"""
    teach = "1m 2m 3m 0p 6p 7p 3s 4s 6s 7s 8s 5z 5z".split()
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["mode"] == "template"
        ws.send_json({"type": "settings", "settings": {"seat_wind": "south"}})
        ws.send_bytes(_jpeg(table_image(teach)))
        first = ws.receive_json()
        assert first["seen"] == 13 and first["unknown"] == 13
        ws.send_json({"type": "teach", "tiles": teach})
        taught = ws.receive_json()
        assert taught["type"] == "taught" and taught["count"] == 13

        # 3フレーム同じ手牌が読めたら確定して分析が届く
        frame = _jpeg(table_image(teach, scale=1.1, origin=(40, 200)))
        msgs = []
        for _ in range(3):
            ws.send_bytes(frame)
            msgs.append(ws.receive_json())
        assert msgs[-1]["changed"] and msgs[-1]["hand"] == teach
        assert msgs[-1]["analysis"]["shanten"] == 0

        # プレイヤーがアシストと関係なく牌を入れ替えても、読み直して分析が更新される
        changed = teach[:-1] + ["3s"]
        frame2 = _jpeg(table_image(changed, scale=1.1, origin=(40, 200)))
        for _ in range(3):
            ws.send_bytes(frame2)
            last = ws.receive_json()
        assert last["hand"] == changed and last["changed"]


def test_teach_count_mismatch():
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_bytes(_jpeg(table_image(["1m", "2m", "3m"])))
        ws.receive_json()
        ws.send_json({"type": "teach", "tiles": ["1m", "2m"]})
        msg = ws.receive_json()
        assert msg["type"] == "error" and "枚数" in msg["message"]


def test_four_players_are_independent():
    """4人が同時に接続しても、各自の手牌・設定は混ざらない。"""
    hands = [
        "1m 2m 3m".split(), "0p 6p 7p".split(), "3s 4s 6s".split(), "5z 5z 1m".split(),
    ]
    conns = [client.websocket_connect("/ws") for _ in range(4)]
    wss = [c.__enter__() for c in conns]
    try:
        for ws in wss:
            ws.receive_json()
        for ws, h in zip(wss, hands):
            ws.send_bytes(_jpeg(table_image(h)))
            ws.receive_json()
        for ws, h in zip(wss, hands):
            ws.send_json({"type": "teach", "tiles": h})
            assert ws.receive_json()["type"] == "taught"
        for ws, h in zip(wss, hands):
            for _ in range(3):
                ws.send_bytes(_jpeg(table_image(h)))
                last = ws.receive_json()
            assert last["hand"] == h
    finally:
        for c in conns:
            c.__exit__(None, None, None)


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


def test_hand_is_never_shared_between_players():
    """他のプレイヤーの手牌・分析・映像は、別の接続にも API にも出てこない。"""
    import re

    from app.main import detector

    a_hand = "1p 2p 3p 4p 5p 6p".split()
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        a.receive_json(); b.receive_json()
        a.send_bytes(_jpeg(table_image(a_hand)))
        a.receive_json()
        a.send_json({"type": "teach", "tiles": a_hand})
        assert a.receive_json()["type"] == "taught"
        # B は自分の映像（何も映っていない）を送るだけ。A の手牌は届かない
        b.send_bytes(_jpeg(np.full((240, 320, 3), 60, np.uint8)))
        msg = b.receive_json()
        assert msg["hand"] is None and msg["seen"] == 0
    info = client.get("/api/info").json()
    assert "registered" not in info
    # 見本のファイル名は乱数だけ（時刻や並び順を含まない）
    for f in detector.store.root.rglob("*.png"):
        assert re.fullmatch(r"[0-9a-f]{32}\.png", f.name)


def test_api_yakuman_list_and_nima_analyze():
    r = client.get("/api/yakuman")
    assert r.status_code == 200 and any(y["name"] == "大三元" for y in r.json()["yakuman"])
    r = client.post("/api/analyze", json={"tiles": "5z 5z 6z 6z 6z 7z 2m 3m 4m 1p 2p 3p 9s 9s".split(), "settings": {"players": 2}})
    assert r.status_code == 200
    body = r.json()
    assert body["nima"] and body["hints"][0]["name"] == "大三元" and "役満狙いなら" in body["message"]
