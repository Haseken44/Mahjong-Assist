"""FastAPI エントリーポイント。

- GET  /            スマホ用 UI
- POST /api/analyze 手牌（牌表記の配列）を分析
- WS   /ws          カメラ映像（JPEG フレーム）を連続で受け取り、検出＋分析結果を返す
- GET  /api/info    認識方式と登録済みの見本数
- GET  /healthz     死活監視
- GET  /taikai      はせけん麻雀大会・個人成績（API は /api/league/...。app/league_api.py）
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from collections import Counter, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from .league_api import router as league_router
from .league_public import router as public_router
from .logic import tiles as T
from .logic.analyzer import analyze
from .logic.settings import RoundSettings
from .vision.detector import load_detector
from .vision.quality import frame_hints
from .vision.preprocessor import decode_image, preprocess

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mahjong-assist")

STATIC = Path(__file__).parent / "static"
MAX_FRAME_BYTES = 3 * 1024 * 1024

app = FastAPI(title="Mahjong Vision Assist", version="0.5.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(public_router)  # 公開の成績ページ /seiseki/ と Markdown 書き出し（閲覧専用）
app.include_router(league_router)
detector = load_detector()


class AnalyzeRequest(BaseModel):
    tiles: list[str] = Field(default_factory=list, max_length=18)
    settings: RoundSettings = Field(default_factory=RoundSettings)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "version": app.version, "detector": detector.mode}


@app.get("/api/rules")
async def rules() -> dict:
    """ルール設定画面用：プリセットと各項目の説明。"""
    from .logic.rules import PRESETS, RULE_LABELS

    return {"presets": {k: v.model_dump() for k, v in PRESETS.items()}, "labels": RULE_LABELS}


@app.get("/api/yakuman")
async def yakuman() -> dict:
    """役満一覧（二麻はアガリが役満だけなので、いつでも見られるようにする）。"""
    from .logic.yakuman import yakuman_list

    return {"yakuman": yakuman_list()}


@app.get("/api/info")
async def info() -> dict:
    # 牌ごとの登録数は返さない（誰かが学習した直後の増え方から手牌を推測されないように）
    return _hello()


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest) -> dict:
    try:
        return await run_in_threadpool(analyze, req.tiles, req.settings)
    except T.TileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class Stabilizer:
    """直近のフレームの読み取り結果を多数決でまとめ、手牌を「確定」する（表示のちらつきを抑える）。

    カメラ映像では1〜2枚が毎回少しずつ読み違えることがあるので、手牌全体の一致ではなく
    「枚数が同じフレームどうしで、位置ごとの多数決」で決める。
    プレイヤーがアシストと違う牌を切っても、次に安定して読めた手牌で分析し直す。
    """

    def __init__(self, size: int = 5, need: int = 3):
        self.history: deque[tuple] = deque(maxlen=size)
        self.need = need
        self.stable: tuple | None = None

    def push(self, tiles: list[str | None]) -> tuple[list[str] | None, bool]:
        """(確定した手牌, 今回変わったか) を返す。tiles は一番近い牌の候補（不明は None）。"""
        self.history.append(tuple(tiles))
        length, n = Counter(len(h) for h in self.history if h).most_common(1)[0] if any(self.history) else (0, 0)
        if n >= self.need:
            same = [h for h in self.history if len(h) == length]
            cand = []
            for i in range(length):
                votes = Counter(h[i] for h in same if h[i])
                if not votes:
                    cand = None
                    break
                tile, k = votes.most_common(1)[0]
                if k * 2 <= len(same):  # 過半数に届かない位置がある → まだ決めない
                    cand = None
                    break
                cand.append(tile)
            if cand and tuple(cand) != self.stable:
                self.stable = tuple(cand)
                return list(cand), True
        return (list(self.stable) if self.stable else None), False


class PlayerSession:
    """1台のスマホ（1人のプレイヤー）ごとの状態。4人が同時に使っても互いに影響しない。

    手牌・分析結果・カメラ映像はこの接続の中だけに保持し、他の接続へ送ることはない。
    映像はディスクに保存せず、メモリ上の直近1フレームだけを持つ（切断で破棄）。
    """

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
    raw = detector.detect(img)
    dets = _drop_meld_tiles(raw, sess.settings)
    tiles = [d.tile for d in dets]
    h, w = img.shape[:2]
    boxes = [(int(d.box[0] * w), int(d.box[1] * h), int((d.box[2] - d.box[0]) * w), int((d.box[3] - d.box[1]) * h))
             for d in raw]
    hand, changed = sess.stab.push([d.best for d in dets])
    out = {
        "type": "detection",
        "mode": detector.mode,
        "detections": [d.as_dict() for d in dets],
        "seen": len(dets),
        "unknown": sum(1 for t in tiles if t is None),
        "hints": frame_hints(img, boxes, 14 - 3 * len(sess.settings.melds)),
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


def _drop_meld_tiles(dets: list, settings: RoundSettings) -> list:
    """鳴いた牌を手牌の右側に並べている場合、その分を手牌から除く（同じ行に映るため）。"""
    if not settings.melds:
        return dets
    meld_n = len(settings.meld_tiles)
    full = 14 - 3 * len(settings.melds)
    if len(dets) in (full - 1 + meld_n, full + meld_n):
        return dets[: len(dets) - meld_n]
    return dets


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
    meld_tiles = sess.settings.meld_tiles
    if meld_tiles and len(boxes) == len(tiles) + len(meld_tiles):
        tiles = tiles + meld_tiles  # 右側に並べた鳴きの牌もまとめて覚える
    if len(boxes) != len(tiles):
        return {"type": "error", "message": f"枚数が合いません（映っている牌 {len(boxes)}枚 / 入力 {len(tiles)}枚）。牌を横一列に並べて映し直してください"}
    pairs = list(zip(tiles, boxes))
    random.shuffle(pairs)  # 保存順から並び（手牌）を復元できないようにする
    for t, b in pairs:
        store.add(t, crop(sess.last_frame, b))
    sess.last_frame = None  # 映像はメモリ上の直近1枚だけ。学習後は捨てる
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
    finally:
        sess.last_frame = None
        sess.stab = Stabilizer()


def _hello() -> dict:
    store = getattr(detector, "store", None)
    return {
        "type": "hello",
        "mode": detector.mode,
        "kinds": store.kinds if store else None,
        "templates": store.count if store else None,
    }
