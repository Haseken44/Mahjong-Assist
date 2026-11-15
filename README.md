# Mahjong Vision Assist（麻雀アシスト）

スマホのブラウザでカメラを起動し、手牌から「何を切るか」「狙える役」「待ち牌」「アガリ時の点数」をリアルタイムで表示する、麻雀初心者向けの Web アプリです。

本番 URL: https://mahjong-assist.dxc-labo.cloud

## できること（初期版 v0.1）

| 機能 | 内容 |
|---|---|
| 手牌入力 | カメラ認識（学習済みモデルがある場合）または画面の牌ボタンで手動入力。赤五・ドラ表示牌に対応 |
| 向聴数 | 「2向聴（あと2枚でテンパイ）」のように表示 |
| 何切る | 14枚のとき、各打牌の向聴数と受け入れ枚数をおすすめ順に表示。テンパイになる打牌は待ちと点数も表示 |
| 待ち・点数 | 13枚でテンパイなら待ち牌ごとの残り枚数・役・点数。役なしの場合は「リーチすれば何点」を表示 |
| 点数計算 | 14枚のアガリ形で翻・符・役・点数（親/子、ロン/ツモ、本場、リーチ、一発、ドラ・赤ドラ） |
| 狙える役 | タンヤオ・役牌・混一色/清一色・七対子・対々和・一気通貫・三色・国士の「あと何枚」目安 |

未対応（今後）: 鳴き（ポン・チー・カン）、河・他家の捨て牌の考慮、カメラでのドラ表示牌の自動認識。

## 画像認識について

- `models/mahjong_best.pt`（Ultralytics YOLOv8/YOLO11 の学習済み牌検出モデル）を置き、`requirements-vision.txt` をインストールすると自動で「AI認識」モードになります。
- モデルが無い間は **手動入力モード** で動きます（カメラ映像は表示されますが、サーバーには送信しません）。
- モデルのクラス名は `1m`〜`9m`, `1p`〜`9p`, `1s`〜`9s`, `1z`(東)〜`7z`(中), 赤五 `0m/0p/0s` を推奨。`3man`, `5p_red`, `chun` などの別名も自動変換します。
- 検出結果は「横一列に並んだ一番牌の多い行」を手牌とみなし、左から右に並べます。直近3フレームで多数決してちらつきを抑えます。

## 構成

```
app/
  main.py              FastAPI（/, /api/analyze, /ws, /healthz）
  logic/tiles.py       牌表記と変換
  logic/settings.py    局の設定（自風・場風・ドラ・リーチ等）
  logic/analyzer.py    向聴数・何切る・有効牌・役ヒント
  logic/scorer.py      点数計算（mahjong ライブラリ）
  vision/preprocessor.py  画像デコード・縮小・明るさ補正
  vision/detector.py   YOLO 検出 / モック
  static/              スマホ用 UI（HTML/CSS/Vanilla JS）
deploy/                systemd ユニット・nginx 設定例・更新スクリプト
tests/                 単体テスト
```

## ローカル開発

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8030
pytest -q
```

## サーバーへのデプロイ（Ubuntu 24.04 / Python 3.12）

nginx（https://mahjong-assist.dxc-labo.cloud → http://127.0.0.1:8030）と証明書は設定済みの前提です。以下を `ubuntu` ユーザーで実行します。

```bash
# 1. 必要パッケージ（未導入なら）
sudo apt update && sudo apt install -y python3.12-venv git

# 2. 取得
cd ~
git clone https://github.com/Haseken44/Mahjong-Assist.git mahjong-assist
cd mahjong-assist

# 3. 仮想環境と依存パッケージ
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# 4. 動作確認（Ctrl+C で終了）
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8030
#   別ターミナルで: curl http://127.0.0.1:8030/healthz  → {"status":"ok","detector":"mock"}

# 5. systemd に登録して常駐
sudo cp deploy/mahjong-assist.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mahjong-assist
sudo systemctl status mahjong-assist --no-pager
curl https://mahjong-assist.dxc-labo.cloud/healthz
```

- ユーザー名やパスが `ubuntu` / `/home/ubuntu/mahjong-assist` と違う場合は `deploy/mahjong-assist.service` の `User`, `Group`, `WorkingDirectory`, `ExecStart` を合わせてください。
- nginx 側の設定例は `deploy/nginx-mahjong-assist.conf`（WebSocket の `Upgrade` ヘッダーが必要）。
- ログ: `journalctl -u mahjong-assist -f`

### 更新

```bash
cd ~/mahjong-assist && bash deploy/update.sh
```

### 画像認識（YOLO）を有効にする場合

PyTorch を含むため数 GB のディスクと十分なメモリが必要です。CPU のみのサーバーでは 1 フレーム数百 ms〜1 秒程度かかります。

```bash
.venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r requirements-vision.txt
cp /path/to/mahjong_best.pt models/mahjong_best.pt
sudo systemctl restart mahjong-assist
curl http://127.0.0.1:8030/healthz   # → "detector":"yolo"
```
