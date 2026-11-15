"""スマホカメラ映像の前処理（デコード・リサイズ・明るさ補正）。"""
from __future__ import annotations

import base64

import cv2
import numpy as np

MAX_SIDE = 960


def decode_image(data: str | bytes) -> np.ndarray | None:
    """data URL / base64 文字列 / JPEG バイト列を BGR 画像にする。"""
    if isinstance(data, str):
        if data.startswith("data:"):
            data = data.split(",", 1)[-1]
        try:
            data = base64.b64decode(data)
        except (ValueError, TypeError):
            return None
    buf = np.frombuffer(data, dtype=np.uint8)
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def preprocess(img: np.ndarray) -> np.ndarray:
    """長辺を MAX_SIDE に縮小し、CLAHE で明るさムラを補正する。"""
    h, w = img.shape[:2]
    scale = MAX_SIDE / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
    img = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
    return img
