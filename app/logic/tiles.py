"""牌の表記と変換。

アプリ内の牌表記は「数字 + スート」の2文字に統一する。
  萬子: 1m-9m / 筒子: 1p-9p / 索子: 1s-9s
  字牌: 1z=東 2z=南 3z=西 4z=北 5z=白 6z=發 7z=中
  赤ドラ: 0m / 0p / 0s （赤五）
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable

SUITS = "mpsz"
SUIT_OFFSET = {"m": 0, "p": 9, "s": 18, "z": 27}
HONOR_NAMES = {1: "東", 2: "南", 3: "西", 4: "北", 5: "白", 6: "發", 7: "中"}
SUIT_NAMES = {"m": "萬", "p": "筒", "s": "索"}

ALL_TILES = [f"{n}{s}" for s in "mps" for n in range(1, 10)] + [f"{n}z" for n in range(1, 8)]
RED_TILES = ["0m", "0p", "0s"]

# mahjong ライブラリの赤五の136番号（各五の1枚目）
RED_136 = {"m": 16, "p": 52, "s": 88}


class TileError(ValueError):
    pass


def validate(tile: str) -> str:
    if not isinstance(tile, str) or len(tile) != 2:
        raise TileError(f"不正な牌表記: {tile!r}")
    n, s = tile[0], tile[1]
    if s not in SUITS or not n.isdigit():
        raise TileError(f"不正な牌表記: {tile!r}")
    num = int(n)
    if s == "z" and not 1 <= num <= 7:
        raise TileError(f"不正な字牌: {tile!r}")
    if s != "z" and not 0 <= num <= 9:
        raise TileError(f"不正な数牌: {tile!r}")
    return tile


def is_red(tile: str) -> bool:
    return tile[0] == "0"


def normalize(tile: str) -> str:
    """赤五を通常の五に直す。"""
    return f"5{tile[1]}" if is_red(tile) else tile


def to_34(tile: str) -> int:
    validate(tile)
    t = normalize(tile)
    return SUIT_OFFSET[t[1]] + int(t[0]) - 1


def from_34(index: int) -> str:
    if index < 27:
        return f"{index % 9 + 1}{'mps'[index // 9]}"
    return f"{index - 27 + 1}z"


def to_34_array(tiles: Iterable[str]) -> list[int]:
    arr = [0] * 34
    for t in tiles:
        arr[to_34(t)] += 1
    return arr


def to_136_array(tiles: Iterable[str]) -> list[int]:
    """牌を136番号に変換する（入力と同じ順番で返す）。赤五は各五の1枚目（ライブラリの赤ドラ番号）を使う。"""
    tiles = list(tiles)
    used: dict[int, set[int]] = {}
    result: list[int | None] = [None] * len(tiles)
    # 赤五を先に割り当て、通常の五が赤の番号を使わないようにする
    order = sorted(range(len(tiles)), key=lambda i: 0 if is_red(tiles[i]) else 1)
    for i in order:
        t = tiles[i]
        idx = to_34(t)
        copies = used.setdefault(idx, set())
        if is_red(t):
            if 0 in copies:
                raise TileError(f"赤五が重複しています: {t}")
            copy = 0
        else:
            free = [c for c in range(4) if c not in copies]
            if idx in (4, 13, 22):
                free = [c for c in free if c != 0] or free
            if not free:
                raise TileError(f"同じ牌が5枚以上あります: {normalize(t)}")
            copy = free[0]
        copies.add(copy)
        result[i] = idx * 4 + copy
    return result  # type: ignore[return-value]


def tile_to_136(tile: str, hand_136: list[int]) -> int:
    """手牌中の特定の牌（アガリ牌）の136番号を返す。"""
    target = to_34(tile)
    for n in hand_136:
        if n // 4 == target and (is_red(tile) == (n in RED_136.values())):
            return n
    for n in hand_136:
        if n // 4 == target:
            return n
    raise TileError(f"アガリ牌 {tile} が手牌にありません")


# 三人麻雀では萬子の2〜8（赤五萬を含む）を使わない
SANMA_EXCLUDED = {f"{n}m" for n in range(2, 9)} | {"0m"}


def tile_set(players: int) -> list[str]:
    """使う牌の種類（34種 or 三麻の27種）。"""
    return [t for t in ALL_TILES if players == 4 or t not in SANMA_EXCLUDED]


def sanma_dora_from_indicator(indicator: str) -> str:
    """三麻のドラ表示牌 → ドラ。萬子は 1m→9m→1m と1と9だけで回る。"""
    t = normalize(indicator)
    if t == "1m":
        return "9m"
    if t == "9m":
        return "1m"
    n, s = int(t[0]), t[1]
    if s == "z":
        if n <= 4:
            return f"{n % 4 + 1}z"
        return f"{(n - 5 + 1) % 3 + 5}z"
    return f"{n % 9 + 1}{s}"


def sort_tiles(tiles: Iterable[str]) -> list[str]:
    return sorted(tiles, key=lambda t: (to_34(t), 0 if is_red(t) else 1))


def check_counts(tiles: Iterable[str]) -> None:
    c = Counter(normalize(t) for t in tiles)
    over = [t for t, n in c.items() if n > 4]
    if over:
        raise TileError(f"同じ牌が5枚以上あります: {', '.join(over)}")
    reds = Counter(t for t in tiles if is_red(t))
    if any(n > 1 for n in reds.values()):
        raise TileError("赤五は各色1枚までです")


def display_name(tile: str) -> str:
    t = normalize(tile)
    n, s = int(t[0]), t[1]
    if s == "z":
        return HONOR_NAMES[n]
    kanji = "一二三四五六七八九"[n - 1]
    return f"{'赤' if is_red(tile) else ''}{kanji}{SUIT_NAMES[s]}"


def is_terminal_or_honor(index34: int) -> bool:
    return index34 >= 27 or index34 % 9 in (0, 8)
