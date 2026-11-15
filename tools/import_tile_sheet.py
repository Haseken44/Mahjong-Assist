"""牌の一覧画像（全種類の牌を格子状に並べた画像）から、認識用の見本を一括登録する。

使い方（【Webサーバ(os3-379-22658)】で実行）:
    cd ~/mahjong-assist
    .venv/bin/python -m tools.import_tile_sheet 麻雀牌一覧.png            # 確認だけ（保存しない）
    .venv/bin/python -m tools.import_tile_sheet 麻雀牌一覧.png --save     # data/templates_seed/ に登録
    .venv/bin/python -m tools.import_tile_sheet 実物の写真.png --save --replace   # 写真を差し替えるとき
    sudo systemctl restart mahjong-assist

画像ファイルはリポジトリに入れない（素材のライセンスのため）。サーバーへは【PC(ubuntu26)】から scp で送る。

画像の並び（既定 --layout standard）:
    1段目: 一〜伍萬, 赤伍萬, 六〜九萬
    2段目: 一〜五索, 赤五索, 六〜九索
    3段目: 一〜五筒, 赤五筒, 六〜九筒
    4段目: 東 南 西 北 白 發 中（その右の牌の裏側などは無視）
横向きの牌（細長いもの）は自動で除外する。

注意: 一覧画像はイラストなので、実物の牌とは見た目が少し違う。最初の見本として使い、
実際の卓で読み違えた牌は画面から「覚える」で直すと精度が上がる。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

LAYOUTS = {
    "standard": [
        ["1m", "2m", "3m", "4m", "5m", "0m", "6m", "7m", "8m", "9m"],
        ["1s", "2s", "3s", "4s", "5s", "0s", "6s", "7s", "8s", "9s"],
        ["1p", "2p", "3p", "4p", "5p", "0p", "6p", "7p", "8p", "9p"],
        ["1z", "2z", "3z", "4z", "5z", "6z", "7z"],
    ],
}


def find_tile_faces(img: np.ndarray) -> list[list[tuple[int, int, int, int]]]:
    """黒い枠線で囲まれた牌の面を見つけ、段ごと・左から順に返す。"""
    # 枠線は黒（どの色の成分も暗い）。青い筒子や赤い萬子の絵柄は枠とみなさない
    border = (img.max(axis=2) < 100).astype(np.uint8) * 255
    border = cv2.morphologyEx(border, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))  # 途切れた枠線をつなぐ
    contours, hierarchy = cv2.findContours(border, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []
    h_img = img.shape[0]
    boxes = []
    for c, hier in zip(contours, hierarchy[0]):
        if hier[3] < 0:  # 穴（枠の内側）だけを見る
            continue
        x, y, w, h = cv2.boundingRect(c)
        if h < h_img * 0.08 or not 0.55 < w / h < 0.95:
            continue  # 小さすぎる・横向きの牌
        boxes.append((x, y, w, h))
    # 同じ牌の中の小さな穴（絵柄）を除く：大きさの中央値に近いものだけ
    if not boxes:
        return []
    med = float(np.median([b[3] for b in boxes]))
    boxes = [b for b in boxes if 0.85 * med < b[3] < 1.15 * med]
    rows: list[list[tuple[int, int, int, int]]] = []
    for b in sorted(boxes, key=lambda b: b[1]):
        if rows and abs(rows[-1][0][1] - b[1]) < med * 0.5:
            rows[-1].append(b)
        else:
            rows.append([b])
    rows = [sorted(r, key=lambda b: b[0]) for r in rows]
    return _fill_gaps(rows)


def _fill_gaps(rows: list[list[tuple[int, int, int, int]]]) -> list[list[tuple[int, int, int, int]]]:
    """格子状に並んでいる前提で、枠線が途切れて見つからなかった牌の位置を他の段から補う。"""
    xs = sorted(b[0] for r in rows for b in r)
    if not xs:
        return rows
    w = int(np.median([b[2] for r in rows for b in r]))
    cols: list[list[int]] = []
    for x in xs:
        if cols and x - cols[-1][-1] < w * 0.5:
            cols[-1].append(x)
        else:
            cols.append([x])
    col_x = [int(np.median(c)) for c in cols]
    filled = []
    for r in rows:
        y, h = int(np.median([b[1] for b in r])), int(np.median([b[3] for b in r]))
        last = max(b[0] for b in r)
        out = []
        for cx in col_x:
            if cx > last + w * 0.5:
                break  # その段の右端より先は補わない
            hit = next((b for b in r if abs(b[0] - cx) < w * 0.5), None)
            out.append(hit or (cx, y, w, h))
        filled.append(out)
    return filled


def extract(img: np.ndarray, layout: str = "standard") -> list[tuple[str, np.ndarray]]:
    from app.vision.segmenter import crop

    rows = find_tile_faces(img)
    spec = LAYOUTS[layout]
    if len(rows) < len(spec):
        raise SystemExit(f"牌の段が {len(rows)} 段しか見つかりません（{len(spec)} 段必要）")
    out = []
    for labels, row in zip(spec, rows):
        if len(row) < len(labels):
            raise SystemExit(f"{labels[0]} の段で牌が {len(row)} 枚しか見つかりません（{len(labels)} 枚必要）")
        for label, box in zip(labels, row):
            out.append((label, crop(img, box, inset=0.04)))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=Path)
    ap.add_argument("--layout", default="standard", choices=sorted(LAYOUTS))
    ap.add_argument("--save", action="store_true", help="初期見本として data/templates_seed/ に保存する")
    ap.add_argument("--replace", action="store_true", help="保存前に以前取り込んだ初期見本を消す（写真の差し替え用）")
    ap.add_argument("--preview", type=Path, help="切り出し結果を並べた確認用画像を書き出す")
    args = ap.parse_args(argv)

    img = cv2.imread(str(args.image))
    if img is None:
        print(f"画像を読み込めません: {args.image}", file=sys.stderr)
        return 1
    if max(img.shape[:2]) < 900:  # 小さい画像は拡大してから切り出す
        img = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    tiles = extract(img, args.layout)
    print(f"{len(tiles)} 種類の牌を切り出しました: {' '.join(t for t, _ in tiles)}")

    if args.preview:
        h = 96
        strip = [cv2.resize(t, (int(h * t.shape[1] / t.shape[0]), h)) for _, t in tiles]
        cv2.imwrite(str(args.preview), np.hstack(strip))
        print(f"確認用画像: {args.preview}")

    if args.save:
        from app.vision.templates import TemplateStore

        import shutil

        store = TemplateStore()
        if args.replace and store.seed.exists():
            shutil.rmtree(store.seed)
            print(f"以前の初期見本を削除しました: {store.seed}")
        for label, t in tiles:
            store.add(label, t, seed=True)
        print(f"保存しました: {store.seed}（登録 {store.kinds} 種類）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
