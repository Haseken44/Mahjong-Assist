"""映像の写り具合を調べて、プレイヤーに直し方を伝えるための目安を返す。"""
from __future__ import annotations

import cv2
import numpy as np

# 牌1枚の高さ（処理後の画像の画素）がこれ未満だと、絵柄がつぶれて読み違えやすい
MIN_TILE_PX = 40


def frame_hints(img: np.ndarray, boxes: list[tuple[int, int, int, int]], expected: int) -> list[str]:
    """写り具合の問題を、直してほしい順に返す。

    dark: 暗い / glare: 白飛び・反射 / none: 牌が見つからない / small: 牌が小さい /
    blurry: ピンボケ / partial: 手牌の一部しか写っていない
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hints = []
    if float(gray.mean()) < 60:
        hints.append("dark")
    if not boxes:
        if float((gray > 250).mean()) > 0.2:
            hints.append("glare")
        hints.append("none")
        return hints
    heights = sorted(b[3] for b in boxes)
    if heights[len(heights) // 2] < MIN_TILE_PX:
        hints.append("small")
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    region = gray[y0:y1, x0:x1]
    if region.size and float(cv2.Laplacian(region, cv2.CV_64F).var()) < 60:
        hints.append("blurry")
    if float((region > 252).mean()) > 0.25:
        hints.append("glare")
    if len(boxes) < expected - 1:
        hints.append("partial")
    return hints
