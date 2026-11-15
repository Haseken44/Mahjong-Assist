"""テスト用：合成の牌画像（緑の卓に牌を横一列に並べた画像）を作る。"""
from __future__ import annotations

import cv2
import numpy as np

SUIT_COLOR = {"m": (30, 30, 30), "p": (170, 70, 20), "s": (40, 140, 40), "z": (30, 30, 30)}
HONOR_TEXT = {1: "E", 2: "S", 3: "W", 4: "N", 5: "", 6: "F", 7: "C"}


def draw_tile(tile: str, w: int = 60, h: int = 80) -> np.ndarray:
    img = np.full((h, w, 3), (232, 240, 245), np.uint8)
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (170, 180, 185), 2)  # 牌の縁（実物は境目に影が出る）
    n, s = tile[0], tile[1]
    color = SUIT_COLOR[s]
    if s == "z":
        num = int(n)
        if num == 7:
            color = (30, 30, 200)
        if num == 6:
            color = (40, 140, 40)
        if num == 5:
            cv2.rectangle(img, (12, 14), (w - 12, h - 14), (170, 70, 20), 3)
        cv2.putText(img, HONOR_TEXT[num], (14, h - 22), cv2.FONT_HERSHEY_SIMPLEX, 1.5, color, 4)
        return img
    num = 5 if n == "0" else int(n)
    if n == "0":
        color = (30, 30, 200)
    cv2.putText(img, str(num), (16, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.3, color, 3)
    mark = {"m": "m", "p": "o", "s": "|"}[s]
    for i in range(num if s != "m" else 1):
        cv2.putText(img, mark, (6 + (i % 5) * 10, 58 + (i // 5) * 14), cv2.FONT_HERSHEY_PLAIN, 1.0, color, 2)
    if s == "m":
        cv2.putText(img, "MAN", (8, 72), cv2.FONT_HERSHEY_PLAIN, 1.0, color, 2)
    return img


def table_image(tiles: list[str], scale: float = 1.0, brightness: int = 0, gap: int = 0,
                size=(800, 480), origin=(20, 260)) -> np.ndarray:
    """緑の卓に手牌を横一列（接した状態）で並べた BGR 画像。"""
    img = np.full((size[1], size[0], 3), (40, 110, 30), np.uint8)
    noise = np.random.default_rng(0).integers(0, 12, img.shape, dtype=np.uint8)
    img = cv2.add(img, noise)
    w, h = int(40 * scale), int(54 * scale)
    x, y = origin
    for t in tiles:
        tile = cv2.resize(draw_tile(t), (w, h))
        img[y:y + h, x:x + w] = tile
        x += w + gap
    if brightness:
        img = cv2.convertScaleAbs(img, alpha=1.0, beta=brightness)
    return img
