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
| 四人／三人 | 四人麻雀と三人麻雀（さんま）を画面で切り替え |
| 鳴き | ポン・チー・明カン・暗カンを画面で入力（三麻は既定でチーなし） |
| ドラ選択 | ドラ表示牌をタップして選ぶ。カンのたびに表示牌の枠が1つ増える。リーチ時は裏ドラも |
| ルール設定 | 雀魂（段位戦）を既定のプリセットにし、各項目を切り替え可能 |
| 手で修正 | 読み違えた牌はタップして正しい牌に置き換え。その並びで「覚える」と次から自動で読める |

未対応（今後）: 河・他家の捨て牌の考慮、カメラでのドラ表示牌・鳴きの自動認識、北を役牌とする三麻ルール、二翻縛り。

## 鳴き・カン・ドラ

- **鳴き**: 「ポン」「チー」「明カン」「暗カン」を押してから牌を選びます。チーは順子のいちばん小さい牌を選びます（3萬を選ぶと3萬4萬5萬）。手牌にある牌は自動で鳴きの方へ移します。鳴きをタップすると取り消せます。
- **ドラ表示牌**: 枠をタップしてから牌を選びます。矢印の先が実際のドラです。
- **カン**: 誰かがカンするたびに「この局のカン回数（全員分）」を1増やすと、ドラ表示牌の枠が1つ増えます。自分のカンは自動で数えます。
- **カンの上限**: カンは1局に卓全体で4回までです（ドラ表示牌は最大5枚）。5回目のカンはできません。なお、4回のカンを2人以上でした場合は「四槓散了（スーカンサンラ）」で流局になり、1人で4回カンした場合だけ四槓子（役満）を狙えます。
- **赤ドラ**: 赤い5（赤五萬・赤五筒・赤五索）は持っているだけでドラ1です。牌ボタンの右下にある赤い5で入力します。

## ルール設定（雀魂プリセット）

雀魂の画面からルールを自動で読み込むことはできないため、雀魂の段位戦ルールを調べてプリセットにしました。「ルール設定」を開くと項目ごとに変更でき、変更すると「カスタム」になります（スマホごとに保存）。

| 項目 | 雀魂（段位戦）の既定 |
|---|---|
| 赤ドラ | あり（四麻は5萬・5筒・5索に各1枚、三麻は5筒・5索に各1枚） |
| 喰いタン・後付け | あり |
| 一発・裏ドラ・カンドラ・カン裏 | あり |
| 切り上げ満貫 | なし |
| 数え役満 | あり（13翻以上） |
| ダブル役満 | あり（国士無双十三面・四暗刻単騎・純正九蓮宝燈・大四喜） |
| 本場 | 四麻 1本300点、三麻 1本200点 |
| 三麻 | チーなし、北は抜きドラ、ツモ損あり、萬子2〜8なし |

## 三人麻雀（さんま）

画面の「局の設定」で「三人麻雀」を選ぶと、次のルールで分析・点数計算します。三麻はお店や仲間内でルール差が大きいため、よくある形を既定にしています。

| 項目 | このアプリの扱い |
|---|---|
| 使う牌 | 萬子は1と9だけ（2〜8萬と赤五萬は無し）。筒子・索子・字牌はすべて使う（108枚） |
| ドラ表示牌 | 一萬 → 九萬、九萬 → 一萬（萬子は1と9で回る） |
| 北 | 抜きドラ。抜いた枚数を設定に入れると1枚につきドラ1。役ではないので北だけではアガれない |
| 自風 | 東・南・西の3つ（北家なし） |
| ツモの支払い | 「ツモ損あり」（既定）：いない北家の分はもらえない。ルール設定で外すと北家の分を2人で折半 |
| チー | 既定ではできない（ルール設定で変更可） |
| 何切る・有効牌 | 2〜8萬は存在しないものとして数える。三色同順・萬子の一通/染め手はヒントに出さない |

未対応の三麻ルール：北を役牌として扱うルール、二翻縛り。

## 手牌の秘密について

対局中に自分の手牌が他のプレイヤーに見えることはありません。

- 手牌・分析結果・カメラ映像は、その人のスマホとサーバーの間の接続（`PlayerSession`）の中だけで扱い、ほかの人の接続や API には一切出しません。
- カメラ映像はディスクに保存しません。サーバーのメモリに直近1コマだけ持ち、学習後と切断時に捨てます。
- 共有されるのは「牌の見本」だけです。これは「この画像は五筒」という牌1枚ずつの見た目で、誰が・いつ・どの並びで教えたかは残りません（ファイル名は乱数、保存順もシャッフル）。登録状況も「何種類覚えたか」しか表示しません。
- それでも念のため、見本は**対局を始める前に**、牌を表向きに並べて覚えさせてください。

## 牌の認識のしくみ

学習済みの AI モデルが無くても動くよう、2段構えにしています。

0. **初期見本（牌の一覧画像）**: 全種類の牌を並べた画像から見本を一括登録できます。いまは仮の素材画像を使い、実物の牌の写真が届いたら差し替えます。

   【PC(ubuntu26)】画像をサーバーへ送る

   ```bash
   scp 麻雀牌一覧.png ubuntu@mahjong-assist.dxc-labo.cloud:~/mahjong-assist/
   ```

   【Webサーバ(os3-379-22658)】取り込む（`--replace` で以前の一覧画像の見本を入れ替え）

   ```bash
   cd ~/mahjong-assist
   .venv/bin/python -m tools.import_tile_sheet 麻雀牌一覧.png --preview check.png   # 確認だけ
   .venv/bin/python -m tools.import_tile_sheet 麻雀牌一覧.png --save --replace
   sudo systemctl restart mahjong-assist
   ```

   画像は「1段目 萬子1〜5・赤5・6〜9、2段目 索子、3段目 筒子、4段目 東南西北白發中」の並びを想定しています。一覧画像の見本は `data/templates_seed/` に、画面で覚えさせた見本は `data/templates/` に分けて保存するので、差し替えても画面で覚えさせた分は残ります。画像ファイルはリポジトリに入れないでください（素材のライセンスのため）。

1. **見本照合方式（標準）**: 画像処理で白い牌の面を見つけて1枚ずつ切り出し、登録された「見本」と照合します。CPU だけで1フレーム約0.1秒。
   - 牌セットによって絵柄が違うため、**最初に一度、その卓の牌を覚えさせます**。手牌を横一列に並べてカメラに映し、画面下で左から順に正しい牌を入力して「この並びで覚える」を押します。37種類（34種＋赤五3種）がひと通り映るまで数回くり返すと、以降は自動で読めます。
   - 見本（牌1枚ずつの見た目）はサーバーの `data/templates/` に保存され、同じ牌セットを使う全員の認識に使われます。手牌は共有されません（「手牌の秘密について」参照）。読み違いを直して「覚える」たびに精度が上がります。
   - 別の牌セットに切り替えるときは【Webサーバ(os3-379-22658)】で `rm -rf ~/mahjong-assist/data/templates` を実行し、`sudo systemctl restart mahjong-assist` してください。
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

## 実行場所の表記

コマンドや操作には、どこで実行するかを必ず付けています。

| 表記 | 場所 |
|---|---|
| 【PC(ubuntu26)】 | 開発用PC（`/home/dev-admin/CodeEdit/麻雀アシストサイト`） |
| 【Webサーバ(os3-379-22658)】 | 本番サーバー（`ubuntu` ユーザー、mahjong-assist.dxc-labo.cloud） |
| 【ブラウザ(GitHub)】 | github.com での操作（PR のマージなど） |
| 【スマホ】 | プレイヤーのスマホのブラウザ |

## ローカル開発

【PC(ubuntu26)】

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8030
pytest -q
```

## サーバーへのデプロイ（Ubuntu 24.04 / Python 3.12）

nginx（https://mahjong-assist.dxc-labo.cloud → http://127.0.0.1:8030）と証明書は設定済みの前提です。

0. 【ブラウザ(GitHub)】反映したい PR を main にマージしておく（サーバーは main を取得します）

1〜5 はすべて【Webサーバ(os3-379-22658)】で `ubuntu` ユーザーとして実行します。

【Webサーバ(os3-379-22658)】

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
#   【Webサーバ(os3-379-22658)】の別ターミナルで: curl http://127.0.0.1:8030/healthz  → {"status":"ok","detector":"template"}

# 5. systemd に登録して常駐
sudo cp deploy/mahjong-assist.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mahjong-assist
sudo systemctl status mahjong-assist --no-pager
curl https://mahjong-assist.dxc-labo.cloud/healthz
```

6. 【スマホ】 https://mahjong-assist.dxc-labo.cloud を開き、「カメラ開始」を押す

- ユーザー名やパスが `ubuntu` / `/home/ubuntu/mahjong-assist` と違う場合は `deploy/mahjong-assist.service` の `User`, `Group`, `WorkingDirectory`, `ExecStart` を合わせてください。
- nginx 側の設定例は `deploy/nginx-mahjong-assist.conf`（WebSocket の `Upgrade` ヘッダーが必要）。
- ログ: `journalctl -u mahjong-assist -f`
- 4人同時利用時の負荷はおよそ CPU 1〜2コア分です。同時に画像処理するフレーム数は環境変数 `MAHJONG_FRAME_SLOTS`（既定 4）で調整できます。

### 更新

1. 【ブラウザ(GitHub)】PR を main にマージ
2. 【Webサーバ(os3-379-22658)】

```bash
cd ~/mahjong-assist && bash deploy/update.sh
```

### 画像認識（YOLO）を有効にする場合

PyTorch を含むため数 GB のディスクと十分なメモリが必要です。CPU のみのサーバーでは 1 フレーム数百 ms〜1 秒程度かかります。

【PC(ubuntu26)】モデルファイルをサーバーへ送る

```bash
scp mahjong_best.pt ubuntu@mahjong-assist.dxc-labo.cloud:~/mahjong-assist/models/mahjong_best.pt
```

【Webサーバ(os3-379-22658)】

```bash
cd ~/mahjong-assist
.venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r requirements-vision.txt
sudo systemctl restart mahjong-assist
curl http://127.0.0.1:8030/healthz   # → "detector":"yolo"
```
