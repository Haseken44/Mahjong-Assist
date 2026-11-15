"""牌の一覧画像（全種類の牌を格子状に並べた画像）から、認識用の見本を一括登録する。

使い方（【Webサーバ(os3-379-22658)】で実行）:
    # 自宅の牌セットの写真（並びの座標は tools/sheets/home_case.json）
    .venv/bin/python -m tools.import_tile_sheet 実物牌.png --config tools/sheets/home_case.json --save --replace
    # 画面の牌の絵も入れ替えるとき（app/static/tiles/*.webp）
    .venv/bin/python -m tools.import_tile_sheet 実物牌.png --config tools/sheets/home_case.json --export-ui app/static/tiles

    cd ~/mahjong-assist
    .venv/bin/python -m tools.import_tile_sheet 麻雀牌一覧.png            # 確認だけ（保存しない）
    .venv/bin/python -m tools.import_tile_sheet 麻雀牌一覧.png --save     # data/templates_seed/ に登録
    .venv/bin/python -m tools.import_tile_sheet 実物の写真.png --save --replace   # 写真を差し替えるとき
    sudo systemctl restart mahjong-assist

元の画像ファイルはリポジトリに入れない（素材のライセンスのため）。画面用の牌の絵 app/static/tiles/ だけはコミットする。サーバーへは【PC(ubuntu26)】から scp で送る。

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


def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def extract_with_config(img: np.ndarray, config: dict) -> list[tuple[str, np.ndarray]]:
    """設定ファイル（牌の並びを四角形で指定）に従って、写真から牌を1枚ずつ切り出す。

    各ブロックは4隅の座標 quad（左上・右上・右下・左下）と段数 rows、列ごとの牌 labels を持つ。
    red は赤五の位置 {"段": {"列": "0p"}}。写真が斜めでも格子を補間して切り出す。
    row_edges（省略可）は段の境目の位置（0〜1）。手前の段ほど大きく写る写真で使う。
    """
    W0, H0 = config.get("image_size", [img.shape[1], img.shape[0]])
    sx, sy = img.shape[1] / W0, img.shape[0] / H0
    out = []
    cw, ch, M = 96, 128, 26  # 格子1マスを 96x128 に広げ、周りに M 画素の余白を付けて縁を探す
    dst = np.float32([[M, M], [M + cw, M], [M + cw, M + ch], [M, M + ch]])
    for b in config["blocks"]:
        tl, tr, br, bl = [(x * sx, y * sy) for x, y in b["quad"]]
        rows, labels = b["rows"], b["labels"]
        red = b.get("red", {})
        edges = b.get("row_edges") or [r / rows for r in range(rows + 1)]
        if len(edges) != rows + 1:
            raise SystemExit(f"row_edges は段数+1 個必要です（{labels[0]} のブロック）")
        for r in range(rows):
            v0, v1 = edges[r], edges[r + 1]
            for c, label in enumerate(labels):
                pts = []
                u0, u1 = c / len(labels), (c + 1) / len(labels)
                for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1)):
                    pts.append(_lerp(_lerp(tl, tr, u), _lerp(bl, br, u), v))
                m = cv2.getPerspectiveTransform(np.float32(pts), dst)
                cell = cv2.warpPerspective(img, m, (cw + 2 * M, ch + 2 * M), borderMode=cv2.BORDER_REPLICATE)
                name = red.get(str(r), {}).get(str(c), label)
                out.append((name, snap_face(cell, M, cw, ch)))
    return out


def _seam_score(gray: np.ndarray, axis: int) -> np.ndarray:
    """列（axis=1）または行（axis=0）ごとの「境目の溝らしさ」(0〜1)。

    境目は牌の端から端まで続く細い溝なので、「両隣より暗い画素の割合」が高くなる。
    絵柄も暗いが途切れるので割合は低い。
    """
    g = gray if axis == 1 else gray.T
    d = 3
    left = np.full_like(g, 255.0)
    right = np.full_like(g, 255.0)
    left[:, d:] = g[:, :-d]
    right[:, :-d] = g[:, d:]
    valley = (g + 4 < left) & (g + 4 < right)
    return valley.mean(axis=0)


def _nearest_seam(score: np.ndarray, center: int, reach: int, thr: float = 0.45) -> int | None:
    """center±reach で一番はっきりした溝（近いほど少し優先）。"""
    best, best_v = None, -1.0
    for x in range(max(1, center - reach), min(len(score) - 1, center + reach + 1)):
        v = score[x] - 0.01 * abs(x - center)
        if score[x] >= thr and v > best_v:
            best, best_v = x, v
    return best


def snap_face(cell: np.ndarray, M: int, cw: int, ch: int) -> np.ndarray:
    """格子のマス（周りに余白 M 付き）から、牌の面の実際の縁を探して切り出す。

    格子の位置は写真のゆがみで数画素〜十数画素ずれるので、牌どうしの境目（端から端まで
    続く細い溝）を探して、隣の牌がはみ出さず牌の面が中央に来るようにする。
    """
    gray = cv2.GaussianBlur(cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY), (3, 3), 0).astype(np.float32)
    reach = 22
    inner = gray[M + int(ch * 0.1):M + int(ch * 0.9)]          # 上下の境目の影響を除いた行
    cols = _seam_score(inner, axis=1)
    left, right = _nearest_seam(cols, M, reach), _nearest_seam(cols, M + cw, reach)
    x0 = left + 2 if left is not None else M + 5
    x1 = right - 1 if right is not None else M + cw - 5
    band = gray[:, max(0, x0 + int(cw * 0.1)):x1 - int(cw * 0.1)]
    rows = _seam_score(band, axis=0)
    top, bottom = _nearest_seam(rows, M, reach), _nearest_seam(rows, M + ch, reach)
    y0 = top + 2 if top is not None else M + 5
    y1 = bottom - 1 if bottom is not None else M + ch - 5
    if not (cw * 0.8 < x1 - x0 < cw * 1.2):  # 境目を見誤ったときは格子どおり
        x0, x1 = M + 7, M + cw - 7
    if not (ch * 0.8 < y1 - y0 < ch * 1.2):
        y0, y1 = M + 6, M + ch - 6
    # 縁の丸み・影を少し内側に削る
    ix, iy = max(2, int((x1 - x0) * 0.04)), max(2, int((y1 - y0) * 0.03))
    return cell[y0 + iy:y1 - iy, x0 + ix:x1 - ix].copy()


def export_ui(tiles: list[tuple[str, np.ndarray]], out_dir: Path) -> None:
    """画面表示用に、牌の種類ごとに一番くっきり写った1枚を WebP（72x96）で書き出す。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    best: dict[str, tuple[float, np.ndarray]] = {}
    for label, im in tiles:
        face = im
        sharp = cv2.Laplacian(cv2.cvtColor(face, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
        if label not in best or sharp > best[label][0]:
            best[label] = (sharp, face)
    for label, (_, face) in best.items():
        face = cv2.resize(face, (72, 96), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(out_dir / f"{label}.webp"), face, [cv2.IMWRITE_WEBP_QUALITY, 88])
    print(f"画面表示用の牌画像を {len(best)} 種類書き出しました: {out_dir}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=Path)
    ap.add_argument("--layout", default="standard", choices=sorted(LAYOUTS))
    ap.add_argument("--config", type=Path, help="牌の並びを座標で指定した設定ファイル（例: tools/sheets/home_case.json）")
    ap.add_argument("--export-ui", type=Path, help="画面表示用の牌画像（1種類1枚）を書き出すフォルダ（例: app/static/tiles）")
    ap.add_argument("--save", action="store_true", help="初期見本として data/templates_seed/ に保存する")
    ap.add_argument("--replace", action="store_true", help="保存前に以前取り込んだ初期見本を消す（写真の差し替え用）")
    ap.add_argument("--preview", type=Path, help="切り出し結果を並べた確認用画像を書き出す")
    args = ap.parse_args(argv)

    img = cv2.imread(str(args.image))
    if img is None:
        print(f"画像を読み込めません: {args.image}", file=sys.stderr)
        return 1
    if args.config:
        import json

        tiles = extract_with_config(img, json.loads(args.config.read_text(encoding="utf-8")))
    else:
        if max(img.shape[:2]) < 900:  # 小さい画像は拡大してから切り出す
            img = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        tiles = extract(img, args.layout)
    kinds = sorted({t for t, _ in tiles})
    print(f"{len(tiles)} 枚（{len(kinds)} 種類）の牌を切り出しました")
    if args.export_ui:
        export_ui(tiles, args.export_ui)

    if args.preview:
        h, per_row = 96, 18
        strip = [cv2.resize(t, (72, h)) for _, t in tiles]
        strip += [np.full_like(strip[0], 255)] * (-len(strip) % per_row)
        rows = [np.hstack(strip[i:i + per_row]) for i in range(0, len(strip), per_row)]
        cv2.imwrite(str(args.preview), np.vstack(rows))
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
