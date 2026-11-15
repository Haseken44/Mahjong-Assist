"""牌の検出と判定。

1. models/mahjong_best.pt（YOLOv8/YOLO11 の学習済みモデル）と ultralytics があれば YOLO で検出する。
2. 無ければ「切り出し＋見本照合」方式（segmenter.py + templates.py）で動く。
   見本はプレイヤーが画面から教える（学習ボタン）。見本が無い牌は「？」になる。

モデルのクラス名は「1m」「5p」「7z」「0s(赤五)」形式を推奨。よくある別名（1man, 5pin_red, east 等）も変換する。
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

DEFAULT_MODEL = Path(__file__).resolve().parents[2] / "models" / "mahjong_best.pt"

_HONOR_ALIASES = {
    "east": "1z", "ton": "1z", "south": "2z", "nan": "2z", "west": "3z", "sha": "3z", "xia": "3z",
    "north": "4z", "pei": "4z", "bei": "4z", "white": "5z", "haku": "5z", "green": "6z", "hatsu": "6z",
    "fa": "6z", "red": "7z", "chun": "7z", "zhong": "7z",
}
_SUIT_ALIASES = {
    "m": "m", "man": "m", "wan": "m", "c": "m", "character": "m", "characters": "m",
    "p": "p", "pin": "p", "dot": "p", "dots": "p", "circle": "p", "circles": "p",
    "s": "s", "sou": "s", "so": "s", "bamboo": "s", "bamboos": "s", "b": "s",
    "z": "z", "j": "z",
}


def normalize_label(label: str) -> str | None:
    """モデルのクラス名をアプリの牌表記に変換する。変換できなければ None。"""
    s = label.strip().lower().replace("-", "_").replace(" ", "_")
    if s in _HONOR_ALIASES:
        return _HONOR_ALIASES[s]
    red = bool(re.search(r"(^|_)(r|red|aka|dora)($|_)", s)) or s.startswith("0")
    m = re.match(r"^(\d)_?([a-z]+)", s) or re.match(r"^([a-z]+)_?(\d)", s)
    if not m:
        return None
    a, b = m.groups()
    num, suit = (a, b) if a.isdigit() else (b, a)
    stripped = re.sub(r"_?(red|aka|dora|r)$", "", suit)
    if stripped != suit and stripped in _SUIT_ALIASES:
        red, suit = True, stripped
    suit = _SUIT_ALIASES.get(suit)
    if suit is None:
        return None
    n = int(num)
    if suit == "z":
        return f"{n}z" if 1 <= n <= 7 else None
    if n == 0 or (red and n == 5):
        return f"0{suit}"
    return f"{n}{suit}" if 1 <= n <= 9 else None


@dataclass
class Detection:
    tile: str | None  # 判定できない牌は None
    confidence: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 （0〜1 に正規化）

    def as_dict(self) -> dict:
        return {"tile": self.tile, "confidence": round(self.confidence, 3), "box": [round(v, 4) for v in self.box]}


class BaseDetector:
    mode = "base"

    def detect(self, img: np.ndarray) -> list[Detection]:
        raise NotImplementedError


class MockDetector(BaseDetector):
    """何も検出しないダミー（テスト・手動入力専用）。"""

    mode = "mock"

    def detect(self, img: np.ndarray) -> list[Detection]:
        return []


class TemplateDetector(BaseDetector):
    """白い牌の領域を切り出し、登録された見本と照合する。学習済みモデル不要・CPU で軽量。"""

    mode = "template"

    def __init__(self, store=None):
        from .templates import TemplateStore

        self.store = store or TemplateStore()

    def detect(self, img: np.ndarray) -> list[Detection]:
        from .segmenter import crop, find_tiles

        h, w = img.shape[:2]
        out = []
        for box in find_tiles(img):
            tile, conf = self.store.classify(crop(img, box))
            x, y, bw, bh = box
            out.append(Detection(tile, conf, (x / w, y / h, (x + bw) / w, (y + bh) / h)))
        return out


class YoloDetector(BaseDetector):
    mode = "yolo"

    def __init__(self, model_path: Path, conf: float = 0.45, imgsz: int = 960):
        from ultralytics import YOLO  # 重いので必要なときだけ import

        self.model = YOLO(str(model_path))
        self.conf = conf
        self.imgsz = imgsz
        self.names = {int(k): v for k, v in self.model.names.items()}
        unknown = [v for v in self.names.values() if normalize_label(v) is None]
        if unknown:
            log.warning("牌表記に変換できないクラス名: %s", unknown)

    def detect(self, img: np.ndarray) -> list[Detection]:
        h, w = img.shape[:2]
        res = self.model.predict(img, conf=self.conf, imgsz=self.imgsz, verbose=False)[0]
        out: list[Detection] = []
        for xyxy, cls, conf in zip(res.boxes.xyxy.tolist(), res.boxes.cls.tolist(), res.boxes.conf.tolist()):
            tile = normalize_label(self.names.get(int(cls), ""))
            if tile is None:
                continue
            x1, y1, x2, y2 = xyxy
            out.append(Detection(tile, float(conf), (x1 / w, y1 / h, x2 / w, y2 / h)))
        return sort_left_to_right(out)


def sort_left_to_right(dets: list[Detection]) -> list[Detection]:
    """手牌は横一列に並ぶ前提で、左から右に並べ替える。

    縦方向に大きく離れた検出（ドラ表示牌や河の牌など）は、最も検出数の多い行だけを手牌として残す。
    """
    if not dets:
        return dets
    heights = sorted(d.box[3] - d.box[1] for d in dets)
    row_h = heights[len(heights) // 2] or 0.05
    rows: list[list[Detection]] = []
    for d in sorted(dets, key=lambda d: (d.box[1] + d.box[3]) / 2):
        cy = (d.box[1] + d.box[3]) / 2
        for row in rows:
            rcy = sum((r.box[1] + r.box[3]) / 2 for r in row) / len(row)
            if abs(cy - rcy) < row_h * 0.6:
                row.append(d)
                break
        else:
            rows.append([d])
    main = max(rows, key=len)
    return sorted(main, key=lambda d: d.box[0])


def load_detector() -> BaseDetector:
    path = Path(os.environ.get("MAHJONG_MODEL", DEFAULT_MODEL))
    choice = os.environ.get("MAHJONG_DETECTOR", "auto")
    if choice == "mock":
        return MockDetector()
    if choice == "template" or not path.exists():
        log.info("見本照合方式で起動します（YOLO モデル: %s なし）", path)
        return TemplateDetector()
    try:
        det = YoloDetector(path, conf=float(os.environ.get("MAHJONG_CONF", "0.45")))
        log.info("YOLO モデルを読み込みました: %s", path)
        return det
    except Exception:  # ultralytics 未インストールなど
        log.exception("YOLO モデルを読み込めないので見本照合方式で起動します")
        return TemplateDetector()
