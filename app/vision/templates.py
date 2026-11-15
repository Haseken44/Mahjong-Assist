"""登録した牌の見本（テンプレート）と照合して牌の種類を判定する。

プレイヤーが「カメラに映っている牌を左から順に入力 → 学習」すると、切り出した牌1枚ずつの画像が
data/templates/<牌の種類>/ に保存される。卓の牌セットごとに見た目が違っても、その卓の牌で学習できる。

共有されるのは「この牌はこういう見た目」という牌1枚単位の見本だけで、誰が・いつ・どの並びで
教えたか（＝手牌）は残さない（ファイル名は乱数、保存順もシャッフル）。見本は対局前に
全種類の牌を表向きに並べて教えることを推奨する。
"""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

import cv2
import numpy as np

from ..logic import tiles as T

DATA_DIR = Path(os.environ.get("MAHJONG_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
MAX_PER_TILE = 20
SIZE = (32, 48)  # 幅, 高さ
COLOR_WEIGHT = 3.0
UNKNOWN_DISTANCE = 1.0  # これより似ていなければ「？（不明）」
AUG_COUNT = 8  # augment() が返す枚数

_hog = cv2.HOGDescriptor(SIZE, (16, 16), (8, 8), (8, 8), 9)


def _color_feature(img: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0].astype(int), hsv[:, :, 1], hsv[:, :, 2]
    colored = (s > 80) & (v > 60)
    total = h.size
    red = np.count_nonzero(colored & ((h < 10) | (h > 165))) / total
    green = np.count_nonzero(colored & (h >= 35) & (h <= 90)) / total
    blue = np.count_nonzero(colored & (h > 90) & (h <= 135)) / total
    dark = np.count_nonzero(v < 80) / total
    return np.array([red, green, blue, dark], np.float32)


def tighten(tile_img: np.ndarray) -> np.ndarray:
    """切り出した画像から、牌の白い面だけを囲み直す（傾き・位置ずれの吸収）。"""
    hsv = cv2.cvtColor(tile_img, cv2.COLOR_BGR2HSV)
    v = hsv[:, :, 2]
    face = (hsv[:, :, 1] < 70) & (v > np.percentile(v, 40))
    rows = np.where(face.mean(axis=1) > 0.5)[0]
    cols = np.where(face.mean(axis=0) > 0.5)[0]
    if rows.size < tile_img.shape[0] * 0.6 or cols.size < tile_img.shape[1] * 0.6:
        return tile_img
    return tile_img[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]


def feature(tile_img: np.ndarray) -> np.ndarray:
    img = cv2.resize(tighten(tile_img), SIZE, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(cv2.equalizeHist(gray), (3, 3), 0)
    hog = _hog.compute(gray).ravel()
    hog /= np.linalg.norm(hog) + 1e-6
    small = cv2.resize(gray, (8, 12), interpolation=cv2.INTER_AREA).ravel().astype(np.float32)
    small = (small - small.mean()) / (small.std() + 1e-6) / np.sqrt(small.size)
    col = _color_feature(img) * COLOR_WEIGHT
    return np.concatenate([hog, small * 0.7, col]).astype(np.float32)


def augment(tile_img: np.ndarray) -> list[np.ndarray]:
    """見本1枚から、少しずらす・拡大縮小・ぼかした画像を作り、照合の頑健性を上げる。"""
    h, w = tile_img.shape[:2]
    out = [tile_img]
    for dx, dy, sc in ((0.05, 0, 1.0), (-0.05, 0, 1.0), (0, 0.05, 1.0), (0, -0.05, 1.0), (0, 0, 1.08), (0, 0, 0.93)):
        m = cv2.getRotationMatrix2D((w / 2, h / 2), 0, sc)
        m[0, 2] += dx * w
        m[1, 2] += dy * h
        out.append(cv2.warpAffine(tile_img, m, (w, h), borderMode=cv2.BORDER_REPLICATE))
    out.append(cv2.GaussianBlur(tile_img, (5, 5), 1.5))
    return out


class TemplateStore:
    """見本の保存先は2つ。

    - root（data/templates/）: プレイヤーが画面で「覚える」で教えた見本
    - seed（data/templates_seed/）: 牌の一覧画像から tools/import_tile_sheet.py で取り込んだ初期見本。
      写真を差し替えるときは同ツールの --replace でここだけ入れ替える。
    """

    def __init__(self, root: Path = DATA_DIR / "templates", seed: Path | None = None):
        self.root = root
        self.seed = seed if seed is not None else root.parent / (root.name + "_seed")
        self.lock = threading.Lock()
        self.labels: list[str] = []
        self.features = np.zeros((0, 1), np.float32)
        self.reload()

    def reload(self) -> None:
        labels, feats = [], []
        for base in (self.seed, self.root):
            if not base.exists():
                continue
            for d in sorted(base.iterdir()):
                if not d.is_dir():
                    continue
                try:
                    T.validate(d.name)
                except T.TileError:
                    continue
                for f in sorted(d.glob("*.png")):
                    img = cv2.imread(str(f))
                    if img is None:
                        continue
                    for a in augment(img):
                        labels.append(d.name)
                        feats.append(feature(a))
        with self.lock:
            self.labels = labels
            self.features = np.stack(feats) if feats else np.zeros((0, 1), np.float32)

    @property
    def kinds(self) -> int:
        return len(set(self.labels))

    @property
    def count(self) -> int:
        """登録された見本の枚数（水増し分は除く）。"""
        return len(self.labels) // AUG_COUNT

    def summary(self) -> dict:
        from collections import Counter

        c = Counter(self.labels)
        return {t: n // AUG_COUNT for t, n in sorted(c.items())}

    def add(self, tile: str, tile_img: np.ndarray, seed: bool = False) -> None:
        T.validate(tile)
        d = (self.seed if seed else self.root) / tile
        d.mkdir(parents=True, exist_ok=True)
        # ファイル名は乱数のみ（時刻を入れると同時に学習した牌＝手牌がまとまって分かってしまう）
        name = f"{uuid.uuid4().hex}.png"
        cv2.imwrite(str(d / name), cv2.resize(tile_img, (SIZE[0] * 2, SIZE[1] * 2), interpolation=cv2.INTER_AREA))
        files = sorted(d.glob("*.png"), key=lambda f: f.stat().st_mtime)
        for old in files[:-MAX_PER_TILE]:
            old.unlink(missing_ok=True)
        fs = np.stack([feature(a) for a in augment(tile_img)])
        with self.lock:
            self.labels = self.labels + [tile] * len(fs)
            self.features = np.vstack([self.features, fs]) if self.features.shape[1] == fs.shape[1] else fs

    def classify(self, tile_img: np.ndarray) -> tuple[str | None, float]:
        """(牌, 信頼度0〜1) を返す。見本が無い・似ていない場合は (None, 0)。"""
        with self.lock:
            labels, feats = self.labels, self.features
        if not labels:
            return None, 0.0
        best_label, best_d = None, 1e9
        second_d = 1e9
        for img in (tile_img, cv2.rotate(tile_img, cv2.ROTATE_180)):  # 逆さの牌にも対応
            d = np.linalg.norm(feats - feature(img), axis=1)
            order = np.argsort(d)
            lab = labels[order[0]]
            other = next((d[i] for i in order[1:] if labels[i] != lab), 1e9)
            if d[order[0]] < best_d:
                best_label, best_d, second_d = lab, float(d[order[0]]), float(other)
        if best_d > UNKNOWN_DISTANCE:
            return None, 0.0
        conf = 1.0 - best_d / second_d if second_d < 1e9 else 1.0 - best_d
        return best_label, max(0.0, min(1.0, conf))
