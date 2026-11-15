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
    """牌1枚ずつの (x, y, w, h) を返す。手牌の行（最も枚数の多い行）のみ、左から右の順。

    1. 白い牌の面を二値化し、小さなすき間（絵柄・境目）を埋めて「横長の帯」を見つける
    2. 帯の中で、牌が続いている区間ごとに、境目の縦線と牌の縦横比から枚数を決めて分ける
    牌が小さく写っていても（1枚 20px 程度まで）帯として見つけられるようにしている。
    """
    h_img, w_img = img.shape[:2]
    mask = tile_mask(img)
    if not mask.any():
        return []
    # 絵柄の多い牌（八筒など）は面がまだらになるので、少し太らせて塊にする
    k = max(3, int(round(min(h_img, w_img) * 0.012)) | 1)
    solid = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    solid = _fill_holes(solid)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    boxes: list[tuple[int, int, int, int]] = []
    min_area = h_img * w_img * 0.0008
    contours, _ = cv2.findContours(solid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w * h < min_area or h < 14 or w < 10:
            continue
        if h > h_img * 0.9 or w > w_img * 0.99 and h > h_img * 0.5:
            continue  # 画面全体が白い等
        # 帯の本体（多くの列で牌の面が続いている高さ）に絞る。手前に傾いた牌の側面などを除く
        sub = solid[y:y + h, x:x + w] > 0
        rows_cov = sub.mean(axis=1)
        rows = np.where(rows_cov > 0.5 * rows_cov.max())[0]
        y0, y1 = y + int(rows[0]), y + int(rows[-1]) + 1
        hh = y1 - y0
        if hh < 14:
            continue
        # 列ごとに上端〜下端の間を牌とみなす（索子の棒など、縁まで届く絵柄の切れ込みを埋める）
        band = solid[y0:y1, x:x + w] > 0
        has = band.any(axis=0)
        first = band.argmax(axis=0)
        last = hh - 1 - band[::-1].argmax(axis=0)
        cov = np.where(has, (last - first + 1) / hh, 0.0)
        if cv2.contourArea(c) < 0.5 * w * h and (cov > 0.6).mean() < 0.6:
            continue  # 斜めの線など
        for a, b in _runs(cov > 0.35, min_gap=max(2, int(hh * 0.04))):
            seg_w = b - a
            if seg_w < hh * 0.45:
                continue
            n0 = max(1, round(seg_w / (hh * TILE_ASPECT)))
            if n0 > 20:
                continue
            notch = _corner_notches(mask[:, x + a:x + b], y0, y1)
            cuts = _best_split(gray[y0:y1, x + a:x + b], n0, hh, notch)
            if cuts is None:
                continue
            for c0, c1 in zip(cuts, cuts[1:]):
                boxes.append((x + a + c0, y0, c1 - c0, hh))
    return main_row(boxes)


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
    return filled


def _runs(flags: np.ndarray, min_gap: int) -> list[tuple[int, int]]:
    """True が続く区間 [a, b) の一覧。min_gap 未満の切れ目はつなげる。"""
    out: list[list[int]] = []
    idx = np.where(flags)[0]
    for i in idx:
        if out and i - out[-1][1] < min_gap:
            out[-1][1] = i + 1
        else:
            out.append([int(i), int(i) + 1])
    return [(a, b) for a, b in out]


def _seam_profile(gray: np.ndarray) -> np.ndarray:
    """列ごとの「牌の境目らしさ」(0〜1)。

    境目は上から下まで続く細い溝（左右より少し暗い縦線）になる。絵柄も暗いが、
    上下に途切れるので「左右より暗い行の割合」で区別する。
    """
    h, w = gray.shape
    band = cv2.GaussianBlur(gray[int(h * 0.05):int(h * 0.95)].astype(np.float32), (1, 3), 0)
    d = max(1, int(round(h * 0.03)))
    if w <= 2 * d:
        return np.zeros(w, np.float32)
    left = np.full_like(band, 255.0)
    right = np.full_like(band, 255.0)
    left[:, d:] = band[:, :-d]
    right[:, :-d] = band[:, d:]
    valley = (band + 5 < left) & (band + 5 < right)
    prof = valley.mean(axis=0).astype(np.float32)
    prof = np.maximum(prof, np.r_[prof[1:], 0], dtype=np.float32)  # 溝が2画素幅でも拾う
    return np.convolve(prof, np.ones(3) / 3, mode="same")


def _corner_notches(mask: np.ndarray, y0: int, y1: int) -> np.ndarray:
    """牌の角は丸いので、境目では上下の縁が少しへこむ。そのへこみの深さ (0〜1) を列ごとに返す。"""
    hh = y1 - y0
    m = max(2, int(hh * 0.15))
    top_zone = mask[max(0, y0 - m):y0 + m] > 0
    bot_zone = mask[y1 - m:y1 + m] > 0
    if top_zone.size == 0 or bot_zone.size == 0:
        return np.zeros(mask.shape[1], np.float32)
    top = np.where(top_zone.any(axis=0), top_zone.argmax(axis=0), top_zone.shape[0])
    bot = np.where(bot_zone.any(axis=0), bot_zone.shape[0] - 1 - bot_zone[::-1].argmax(axis=0), -1)
    depth = (top - np.median(top)) + (np.median(bot) - bot)
    out = np.clip(depth / max(2.0, hh * 0.04), 0, 1).astype(np.float32)
    return np.convolve(out, np.ones(3) / 3, mode="same")


def _best_split(gray: np.ndarray, n0: int, h: int, notch: np.ndarray | None = None) -> list[int] | None:
    """枚数の候補 n0-2〜n0+2 から、境目の縦線と牌の縦横比に最も合う分け方を選ぶ。

    手牌の牌は同じ大きさで並ぶので、1枚の幅は全体の平均から ±10% 以内とし、
    その範囲で境目らしさの合計が最大になる切れ目を動的計画法で求める。
    """
    w = gray.shape[1]
    prof = _seam_profile(gray)
    if notch is not None and len(notch) == w:
        prof = 0.5 * prof + 0.5 * notch
    best, best_score = None, -1e9
    for n in sorted({max(1, n0 + d) for d in (-2, -1, 0, 1, 2)}):
        step = w / n
        aspect = step / h
        if not 0.5 < aspect < 1.25:
            continue
        if n == 1:
            cuts, seam = [0, w], 0.25
        else:
            cuts, seam = _dp_cuts(prof, n, step)
        widths = np.diff(cuts)
        uneven = float(np.std(widths) / (np.mean(widths) + 1e-6))
        off = max(0.0, abs(aspect - TILE_ASPECT) - 0.1)  # 0.65〜0.85 は罰なし（斜めから撮ると変わる）
        score = seam - 1.0 * off - uneven
        if score > best_score:
            best, best_score = cuts, score
    return best


def _dp_cuts(prof: np.ndarray, n: int, step: float) -> tuple[list[int], float]:
    """n 枚に分ける切れ目（内側 n-1 か所）を、幅 step±10% の制約で境目らしさ最大に選ぶ。"""
    w = len(prof)
    lo, hi = max(1, int(step * 0.9)), max(1, int(np.ceil(step * 1.1)))
    neg = -1e9
    score = np.full(w + 1, neg)
    score[0] = 0.0
    back = []
    p = np.r_[prof, 0.0]
    for i in range(1, n + 1):
        new = np.full(w + 1, neg)
        arg = np.zeros(w + 1, np.int32)
        for d in range(lo, hi + 1):
            cand = np.full(w + 1, neg)
            cand[d:] = score[:w + 1 - d]
            better = cand > new
            new[better] = cand[better]
            arg[better] = d
        if i < n:
            new = new + p
        back.append(arg)
        score = new
    end = w if score[w] > neg / 2 else int(np.argmax(score))
    if score[end] <= neg / 2:
        cuts = [int(round(i * w / n)) for i in range(n + 1)]
        return cuts, float(np.mean([prof[min(c, w - 1)] for c in cuts[1:-1]]))
    cuts = [end]
    for i in range(n - 1, -1, -1):
        cuts.append(cuts[-1] - int(back[i][cuts[-1]]))
    cuts = cuts[::-1]
    cuts[0], cuts[-1] = 0, w
    return cuts, float(score[end]) / (n - 1)


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
