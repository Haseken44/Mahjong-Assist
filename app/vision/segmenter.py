"""学習済みモデル無しで牌の位置を見つける（古典的な画像処理）。

牌の表面は「彩度が低く明るい（白〜アイボリー）」領域なので、そこを二値化して輪郭を取る。
手牌は牌同士が接して1つの横長の塊になるため、牌1枚の縦横比から枚数を推定して等分する。
"""
from __future__ import annotations

import cv2
import numpy as np

TILE_ASPECT = 0.75  # 牌の表面の 幅/高さ（一般的な麻雀牌は約0.72〜0.78）


def tile_mask(img: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    low_sat = s < 70
    vals = v[low_sat]
    if vals.size < 100:
        return np.zeros(v.shape, np.uint8)
    otsu, _ = cv2.threshold(vals.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = (low_sat & (v > max(120, otsu))).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    # 牌の絵柄（色の付いた部分）の穴を埋める。隣の牌とはくっつけない
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
    return filled


def find_tiles(img: np.ndarray) -> list[tuple[int, int, int, int]]:
    """牌1枚ずつの (x, y, w, h) を返す。手牌の行（最も枚数の多い行）のみ、左から右の順。"""
    h_img, w_img = img.shape[:2]
    mask = tile_mask(img)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = h_img * w_img * 0.0008
    blobs = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w * h < min_area or h < 16 or w < 10:
            continue
        # 塊の面積が外接矩形に対して小さすぎるもの（斜めの線など）は除外
        if cv2.contourArea(c) < 0.55 * w * h:
            continue
        if h > h_img * 0.9 or w > w_img * 0.99 and h > h_img * 0.5:
            continue  # 画面全体が白い等
        blobs.append((x, y, w, h))
    if not blobs:
        return []

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    boxes: list[tuple[int, int, int, int]] = []
    for x, y, w, h in blobs:
        n0 = max(1, round(w / (h * TILE_ASPECT)))
        if n0 > 18:
            continue
        cuts = _best_split(gray[y:y + h, x:x + w], n0, h)
        if cuts is None:
            continue
        for a, b in zip(cuts, cuts[1:]):
            boxes.append((x + a, y, b - a, h))
    return main_row(boxes)


def _seam_profile(gray: np.ndarray) -> np.ndarray:
    """列ごとの「牌の境目らしさ」(0〜1)。境目は上から下まで続く縦線（影・溝）になる。"""
    h = gray.shape[0]
    band = gray[int(h * 0.1):int(h * 0.9)].astype(np.float32)  # 上下の端は除く
    white = float(np.percentile(band, 75))
    dark = band < white - 25  # 牌の地より暗い画素（境目の影・絵柄）
    gx = np.abs(cv2.Sobel(band, cv2.CV_32F, 1, 0, ksize=3)) > 60
    prof = np.maximum(dark.mean(axis=0), gx.mean(axis=0))
    return np.convolve(prof, np.ones(3) / 3, mode="same")


def _best_split(gray: np.ndarray, n0: int, h: int) -> list[int] | None:
    """枚数の候補 n0-1〜n0+1 から、境目の縦線と牌の縦横比に最も合う分け方を選ぶ。"""
    w = gray.shape[1]
    prof = _seam_profile(gray)
    best, best_score = None, -1e9
    for n in {max(1, n0 - 1), n0, n0 + 1}:
        step = w / n
        aspect = step / h
        if not 0.5 < aspect < 1.05:
            continue
        cuts, seam = [0], []
        for i in range(1, n):
            center = int(i * step)
            r = max(1, int(step * 0.2))
            lo, hi = max(cuts[-1] + int(step * 0.5), center - r), min(w - 1, center + r)
            if lo > hi:
                lo = hi = center
            j = lo + int(np.argmax(prof[lo:hi + 1]))
            cuts.append(j)
            seam.append(prof[j])
        cuts.append(w)
        widths = np.diff(cuts)
        uneven = float(np.std(widths) / (np.mean(widths) + 1e-6))
        score = (float(np.mean(seam)) if seam else 0.25) - 1.5 * abs(aspect - TILE_ASPECT) - uneven
        if score > best_score:
            best, best_score = cuts, score
    return best


def main_row(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """最も枚数の多い横一列（手牌）だけを残し、左から右に並べる。"""
    if not boxes:
        return boxes
    hs = sorted(b[3] for b in boxes)
    med_h = hs[len(hs) // 2]
    # 高さが手牌と大きく違うもの（遠くの河の牌など）を除く
    boxes = [b for b in boxes if 0.7 * med_h <= b[3] <= 1.4 * med_h]
    rows: list[list[tuple[int, int, int, int]]] = []
    for b in sorted(boxes, key=lambda b: b[1] + b[3] / 2):
        cy = b[1] + b[3] / 2
        for row in rows:
            rcy = sum(r[1] + r[3] / 2 for r in row) / len(row)
            if abs(cy - rcy) < med_h * 0.5:
                row.append(b)
                break
        else:
            rows.append([b])
    return sorted(max(rows, key=len), key=lambda b: b[0])


def crop(img: np.ndarray, box: tuple[int, int, int, int], inset: float = 0.08) -> np.ndarray:
    x, y, w, h = box
    dx, dy = int(w * inset), int(h * inset)
    return img[y + dy:y + h - dy, x + dx:x + w - dx]
