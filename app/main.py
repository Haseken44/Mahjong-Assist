"""FastAPI エントリーポイント。

- GET  /            スマホ用 UI
- POST /api/analyze 手牌（牌表記の配列）を分析
- WS   /ws          カメラフレームを受け取り、検出＋分析結果を返す
- GET  /healthz     死活監視
"""
from __future__ import annotations

import asyncio
import logging
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
    return {"detector": detector.mode, "tiles": T.ALL_TILES, "red_tiles": T.RED_TILES}


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest) -> dict:
    try:
        return await run_in_threadpool(analyze, req.tiles, req.settings)
    except T.TileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class Stabilizer:
    """直近数フレームで最も多く出た検出結果を採用し、表示のちらつきを抑える。"""

    def __init__(self, size: int = 3):
        self.history: deque[tuple[str, ...]] = deque(maxlen=size)

    def push(self, tiles: list[str]) -> list[str]:
        self.history.append(tuple(tiles))
        best, n = Counter(self.history).most_common(1)[0]
        return list(best) if n > 1 else tiles


def _process_frame(image: str, settings: RoundSettings, stab: Stabilizer) -> dict:
    img = decode_image(image)
    if img is None:
        return {"type": "error", "message": "画像を読み込めませんでした"}
    dets = detector.detect(preprocess(img))
    tiles = stab.push([d.tile for d in dets])
    out = {"type": "detection", "mode": detector.mode, "detections": [d.as_dict() for d in dets], "tiles": tiles}
    if tiles:
        try:
            out["analysis"] = analyze(tiles, settings)
        except T.TileError as e:
            out["analysis"] = {"message": f"認識結果に矛盾があります: {e}"}
    return out


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "hello", "mode": detector.mode})
    stab = Stabilizer()
    try:
        while True:
            msg = await websocket.receive_json()
            try:
                settings = RoundSettings(**(msg.get("settings") or {}))
            except ValidationError as e:
                await websocket.send_json({"type": "error", "message": f"設定が不正です: {e.errors()[0]['msg']}"})
                continue
            kind = msg.get("type")
            if kind == "frame":
                image = msg.get("image") or ""
                if len(image) > MAX_FRAME_BYTES:
                    await websocket.send_json({"type": "error", "message": "画像が大きすぎます"})
                    continue
                result = await run_in_threadpool(_process_frame, image, settings, stab)
            elif kind == "analyze":
                try:
                    result = {"type": "analysis", "analysis": await run_in_threadpool(analyze, msg.get("tiles") or [], settings)}
                except T.TileError as e:
                    result = {"type": "error", "message": str(e)}
            else:
                result = {"type": "error", "message": f"不明なメッセージ: {kind}"}
            await websocket.send_json(result)
    except WebSocketDisconnect:
        pass
    except (asyncio.CancelledError, RuntimeError):
        pass
