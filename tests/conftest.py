import os
import tempfile

# テストでは見本の保存先を一時ディレクトリにし、YOLO モデルは使わない
os.environ.setdefault("MAHJONG_DATA_DIR", tempfile.mkdtemp(prefix="mj-test-"))
os.environ.setdefault("MAHJONG_DETECTOR", "template")
