"""FastAPI エントリーポイント。

- GET  /            スマホ用 UI
- POST /api/analyze 手牌（牌表記の配列）を分析
- WS   /ws          カメラ映像（JPEG フレーム）を連続で受け取り、検出＋分析結果を返す
- GET  /api/info    認識方式と登録済みの見本数
- GET  /healthz     死活監視
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import Counter, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from .logic import tiles as T
from .logic.analyzer import analyze
from .logic.settings import RoundSettings
from .vision.detector import load_detector
from .vision.preprocessor import decode_image, preprocess

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mahjong-assist")

STATIC = Path(__file__).parent / "static"
MAX_FRAME_BYTES = 3 * 1024 * 1024

app = FastAPI(title="Mahjong Vision Assist", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
detector = load_detector()


class AnalyzeRequest(BaseModel):
    tiles: list[str] = Field(default_factory=list, max_length=18)
    settings: RoundSettings = Field(default_factory=RoundSettings)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "detector": detector.mode}


@app.get("/api/info")
async def info() -> dict:
    store = getattr(detector, "store", None)
    return {**_hello(), "registered": store.summary() if store else None}


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest) -> dict:
    try:
        return await run_in_threadpool(analyze, req.tiles, req.settings)
    except T.TileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class Stabilizer:
    """直近のフレームで同じ手牌が何度も読めたときだけ「確定」とし、表示のちらつきを抑える。

    プレイヤーがアシストと違う牌を切っても、次に安定して読めた手牌で分析し直す。
    """

    def __init__(self, size: int = 5, need: int = 3):
        self.history: deque[tuple] = deque(maxlen=size)
        self.need = need
        self.stable: tuple | None = None

    def push(self, tiles: list[str | None]) -> tuple[list[str] | None, bool]:
        """(確定した手牌, 今回変わったか) を返す。"""
        self.history.append(tuple(tiles))
        cand, n = Counter(self.history).most_common(1)[0]
        if n >= self.need and cand and None not in cand and cand != self.stable:
            self.stable = cand
            return list(cand), True
        return (list(self.stable) if self.stable else None), False


class PlayerSession:
    """1台のスマホ（1人のプレイヤー）ごとの状態。4人が同時に使っても互いに影響しない。"""

    def __init__(self) -> None:
        self.settings = RoundSettings()
        self.stab = Stabilizer()
        self.last_frame = None  # 学習用に直近のフレームを保持
        self.last_analysis: dict | None = None


# CPU を食い尽くさないよう、同時に画像処理するフレーム数を制限する（4人×1フレーム程度）
FRAME_SLOTS = asyncio.Semaphore(int(os.environ.get("MAHJONG_FRAME_SLOTS", "4")))


def _process_frame(data: bytes | str, sess: PlayerSession) -> dict:
    img = decode_image(data)
    if img is None:
        return {"type": "error", "message": "画像を読み込めませんでした"}
    img = preprocess(img)
    sess.last_frame = img
    dets = detector.detect(img)
    tiles = [d.tile for d in dets]
    hand, changed = sess.stab.push(tiles)
    out = {
        "type": "detection",
        "mode": detector.mode,
        "detections": [d.as_dict() for d in dets],
        "seen": len(dets),
        "unknown": sum(1 for t in tiles if t is None),
        "hand": hand,
        "changed": changed,
    }
    if changed and hand:
        try:
            sess.last_analysis = analyze(hand, sess.settings)
        except T.TileError as e:
            sess.last_analysis = {"message": f"認識結果に矛盾があります: {e}"}
        out["analysis"] = sess.last_analysis
    return out


def _teach(sess: PlayerSession, tiles: list[str]) -> dict:
    """直近のフレームに映っている牌を、プレイヤーが入力した並び（左から順）で見本として登録する。"""
    store = getattr(detector, "store", None)
    if store is None:
        return {"type": "error", "message": "この認識方式では学習できません"}
    if sess.last_frame is None:
        return {"type": "error", "message": "まだカメラ映像が届いていません"}
    from .vision.segmenter import crop, find_tiles

    tiles = [T.validate(t) for t in tiles]
    boxes = find_tiles(sess.last_frame)
    if len(boxes) != len(tiles):
        return {"type": "error", "message": f"枚数が合いません（映っている牌 {len(boxes)}枚 / 入力 {len(tiles)}枚）。牌を横一列に並べて映し直してください"}
    for t, b in zip(tiles, boxes):
        store.add(t, crop(sess.last_frame, b))
    sess.stab = Stabilizer()
    return {"type": "taught", "count": len(tiles), "kinds": store.kinds, "templates": store.count}


async def _handle_json(msg: dict, sess: PlayerSession) -> dict | None:
    kind = msg.get("type")
    if kind == "settings":
        try:
            sess.settings = RoundSettings(**(msg.get("settings") or {}))
        except ValidationError as e:
            return {"type": "error", "message": f"設定が不正です: {e.errors()[0]['msg']}"}
        if sess.stab.stable:  # 設定が変わったら確定済みの手牌で分析し直す
            return {"type": "analysis", "analysis": await run_in_threadpool(analyze, list(sess.stab.stable), sess.settings)}
        return None
    if kind == "frame":  # 互換用：base64 の画像
        image = msg.get("image") or ""
        if len(image) > MAX_FRAME_BYTES:
            return {"type": "error", "message": "画像が大きすぎます"}
        async with FRAME_SLOTS:
            return await run_in_threadpool(_process_frame, image, sess)
    if kind == "analyze":
        try:
            settings = RoundSettings(**(msg.get("settings") or {})) if msg.get("settings") else sess.settings
            return {"type": "analysis", "analysis": await run_in_threadpool(analyze, msg.get("tiles") or [], settings)}
        except (T.TileError, ValidationError) as e:
            return {"type": "error", "message": str(e)}
    if kind == "teach":
        try:
            return await run_in_threadpool(_teach, sess, msg.get("tiles") or [])
        except T.TileError as e:
            return {"type": "error", "message": str(e)}
    return {"type": "error", "message": f"不明なメッセージ: {kind}"}


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    """カメラ映像のストリーミング受信。

    - バイナリメッセージ: JPEG 1フレーム（スマホが連続して送る）
    - テキスト(JSON): settings / teach / analyze
    """
    await websocket.accept()
    await websocket.send_json(_hello())
    sess = PlayerSession()
    try:
        while True:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                data = msg["bytes"]
                if len(data) > MAX_FRAME_BYTES:
                    result = {"type": "error", "message": "画像が大きすぎます"}
                else:
                    async with FRAME_SLOTS:
                        result = await run_in_threadpool(_process_frame, data, sess)
            else:
                try:
                    payload = json.loads(msg.get("text") or "{}")
                except json.JSONDecodeError:
                    continue
                result = await _handle_json(payload, sess)
            if result is not None:
                await websocket.send_json(result)
    except WebSocketDisconnect:
        pass


def _hello() -> dict:
    store = getattr(detector, "store", None)
    return {
        "type": "hello",
        "mode": detector.mode,
        "kinds": store.kinds if store else None,
        "templates": store.count if store else None,
    }
