import cv2

from app.logic.tiles import ALL_TILES
from app.vision.detector import TemplateDetector
from app.vision.segmenter import crop, find_tiles
from app.vision.templates import TemplateStore
from tests.synth import table_image

HAND = "1m 2m 3m 0p 6p 7p 3s 4s 6s 7s 8s 5z 5z 1z".split()


def test_segmenter_finds_touching_tiles():
    img = table_image(HAND)
    boxes = find_tiles(img)
    assert len(boxes) == 14
    xs = [b[0] for b in boxes]
    assert xs == sorted(xs)


def test_segmenter_with_gaps_and_scale():
    img = table_image(HAND[:13], scale=1.1, gap=3)
    assert len(find_tiles(img)) == 13


def _teach(store: TemplateStore, tiles: list[str], **kw) -> None:
    img = table_image(tiles, **kw)
    boxes = find_tiles(img)
    assert len(boxes) == len(tiles)
    for t, b in zip(tiles, boxes):
        store.add(t, crop(img, b))


def test_template_recognition_after_teaching(tmp_path):
    store = TemplateStore(tmp_path)
    # 34種＋赤を3回に分けて教える（実際の利用では手牌を映して教える）
    allt = ALL_TILES + ["0m", "0p", "0s"]
    for i in range(0, len(allt), 13):
        _teach(store, allt[i:i + 13])
    assert store.kinds == 37

    det = TemplateDetector(store)
    # 明るさと大きさを変えた別の画像で認識できること
    img = table_image(HAND, scale=1.15, brightness=15, origin=(10, 200))
    tiles = [d.tile for d in det.detect(img)]
    assert tiles == HAND

    # 見本の保存と再読み込み
    store2 = TemplateStore(tmp_path)
    assert store2.count == store.count


def test_upside_down_tile(tmp_path):
    store = TemplateStore(tmp_path)
    _teach(store, ["3m", "7p", "6z"])
    img = table_image(["3m", "7p", "6z"])
    img = cv2.rotate(img, cv2.ROTATE_180)
    tiles = [d.tile for d in TemplateDetector(store).detect(img)]
    assert sorted(tiles) == sorted(["3m", "7p", "6z"])


def test_unknown_without_templates(tmp_path):
    det = TemplateDetector(TemplateStore(tmp_path))
    dets = det.detect(table_image(HAND))
    assert len(dets) == 14 and all(d.tile is None for d in dets)
