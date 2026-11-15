# Mahjong Vision Assist（麻雀アシスト）

スマホのブラウザでカメラを起動し、手牌から「何を切るか」「狙える役」「待ち牌」「アガリ時の点数」をリアルタイムで表示する、麻雀初心者向けの Web アプリです。

本番 URL: https://mahjong-assist.dxc-labo.cloud

## できること（v0.2）

| 機能 | 内容 |
|---|---|
| 自動認識 | スマホのカメラ映像をサーバーへ連続送信（約3フレーム/秒）。サーバーが牌を読み取り、手牌が変わるたびにアシストを更新 |
| アシストに従わなくてOK | おすすめと違う牌を切っても、次に読めた手牌で分析し直す（アシストの通りに動いた前提にしない） |
| 4人同時 | 各プレイヤーが自分のスマホで開けば、それぞれ独立して動く（手牌・設定は混ざらない） |
| 向聴数・何切る | 14枚のとき、各打牌の向聴数と受け入れ枚数をおすすめ順に表示。テンパイになる打牌は待ちと点数も |
| 待ち・点数 | テンパイなら待ち牌ごとの残り枚数・役・点数。役なしなら「リーチすれば何点」 |
| 点数計算 | アガリ形で翻・符・役・点数（親/子、ロン/ツモ、本場、リーチ、一発、ドラ・赤ドラ） |
| 狙える役 | タンヤオ・役牌・混一色/清一色・七対子・対々和・一気通貫・三色・国士の「あと何枚」 |
| 手で修正 | 読み違えた牌はタップして正しい牌に置き換え。その並びで「覚える」と次から自動で読める |

未対応（今後）: 鳴き（ポン・チー・カン）、河・他家の捨て牌の考慮、カメラでのドラ表示牌の自動認識。

## 牌の認識のしくみ

学習済みの AI モデルが無くても動くよう、2段構えにしています。

1. **見本照合方式（標準）**: 画像処理で白い牌の面を見つけて1枚ずつ切り出し、登録された「見本」と照合します。CPU だけで1フレーム約0.1秒。
   - 牌セットによって絵柄が違うため、**最初に一度、その卓の牌を覚えさせます**。手牌を横一列に並べてカメラに映し、画面下で左から順に正しい牌を入力して「この並びで覚える」を押します。37種類（34種＋赤五3種）がひと通り映るまで数回くり返すと、以降は自動で読めます。
   - 見本はサーバーの `data/templates/` に保存され、全員で共有されます（同じ卓の誰かが覚えさせれば4人全員に効く）。読み違いを直して「覚える」たびに精度が上がります。
   - 別の牌セットに切り替えるときは `data/templates/` を消してください。
2. **YOLO 方式（任意）**: `models/mahjong_best.pt`（Ultralytics YOLOv8/YOLO11 の学習済み牌検出モデル）を置き、`requirements-vision.txt` をインストールすると自動でこちらに切り替わります。クラス名は `1m`〜`9m`, `1p`〜`9p`, `1s`〜`9s`, `1z`(東)〜`7z`(中), 赤五 `0m/0p/0s` を推奨（`3man`, `5p_red`, `chun` などの別名も自動変換）。

共通: 「横一列に並んだ一番牌の多い行」を手牌とみなし左から右へ並べます。直近5フレーム中3回同じ手牌が読めたときだけ確定し、表示のちらつきを抑えます。

### うまく読めないとき
- 手牌を画面の横幅いっぱいに、真上〜やや手前から映す
- 牌どうしをくっつけて横一列に並べる（ほかの牌が同じ高さに映らないように）
- 明るい場所で、強い反射を避ける

## 構成

```
app/
  main.py              FastAPI（/, /api/analyze, /ws, /healthz）
  logic/tiles.py       牌表記と変換
  logic/settings.py    局の設定（自風・場風・ドラ・リーチ等）
  logic/analyzer.py    向聴数・何切る・有効牌・役ヒント
  logic/scorer.py      点数計算（mahjong ライブラリ）
  vision/preprocessor.py  画像デコード・縮小・明るさ補正
  vision/segmenter.py  牌の切り出し（画像処理）
  vision/templates.py  見本の保存と照合
  vision/detector.py   YOLO 検出 / 見本照合の切り替え
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
#   別ターミナルで: curl http://127.0.0.1:8030/healthz  → {"status":"ok","detector":"template"}

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
- 4人同時利用時の負荷はおよそ CPU 1〜2コア分です。同時に画像処理するフレーム数は環境変数 `MAHJONG_FRAME_SLOTS`（既定 4）で調整できます。

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
