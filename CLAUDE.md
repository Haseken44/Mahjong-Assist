# CLAUDE.md

麻雀初心者向けのスマホ用リアルタイム支援サイト（FastAPI）。仕様の元は `麻雀アシスト開発.md`。

## 開発ルール
- UI 文言・コメントは日本語。ユーザーは麻雀の素人を想定し、専門用語には読みや説明を添える。
- 牌表記は `app/logic/tiles.py` の「数字+スート」(1m〜9m, 1p〜9p, 1s〜9s, 1z〜7z, 赤五は 0m/0p/0s) に統一する。
- 点数計算は `mahjong` ライブラリ (1.4.0) を `app/logic/scorer.py` 経由で使う。直接呼ばない。
- 画像認識は `app/vision/detector.py`。`models/mahjong_best.pt` が無ければモック（手動入力モード）で動く。モデルファイルはコミットしない。
- 本番は `127.0.0.1:8030` で uvicorn（workers=1）。nginx が https://mahjong-assist.dxc-labo.cloud から転送する。同じサーバーの他サイト（ポート 8000, 8010-8014, 8020, 8021）に触れない。

## コマンド
- 開発サーバー: `uvicorn app.main:app --reload --port 8030`
- テスト: `pytest -q`
