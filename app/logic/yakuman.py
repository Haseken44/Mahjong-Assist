"""役満の一覧と、手牌から「狙える役満」を見つけるヒント。

二麻（2人麻雀）はアガリが役満だけなので、配牌から近い役満を教える。
四麻・三麻でも、役満が近いとき（あと数枚）は「狙える役」に出す。
「あと何枚」は、完成形に足りない牌の枚数の目安（簡易計算）。
"""
from __future__ import annotations

from . import tiles as T
from .settings import RoundSettings

# 画面の「役満一覧」に出す内容。example は完成形の一例（牌表記）
YAKUMAN_LIST: list[dict] = [
    {"name": "国士無双", "reading": "こくしむそう", "cond": "門前のみ",
     "desc": "1・9の数牌と字牌の13種類を1枚ずつ＋どれか1枚をもう1枚。",
     "example": "1m 9m 1p 9p 1s 9s 1z 2z 3z 4z 5z 6z 7z 7z"},
    {"name": "四暗刻", "reading": "スーアンコー", "cond": "門前のみ（ロンは単騎待ちだけ）",
     "desc": "鳴かずに刻子（同じ牌3枚）を4組作る。ツモか単騎待ちのロンで成立。",
     "example": "2m 2m 2m 5p 5p 5p 8s 8s 8s 6z 6z 6z 9p 9p"},
    {"name": "大三元", "reading": "だいさんげん", "cond": "鳴いてもOK",
     "desc": "白・發・中の3種類をすべて刻子（3枚ずつ）にする。",
     "example": "5z 5z 5z 6z 6z 6z 7z 7z 7z 2m 3m 4m 9p 9p"},
    {"name": "小四喜", "reading": "しょうスーシー", "cond": "鳴いてもOK",
     "desc": "東・南・西・北のうち3種類を刻子、残り1種類を雀頭（2枚）にする。",
     "example": "1z 1z 1z 2z 2z 2z 3z 3z 3z 4z 4z 5m 6m 7m"},
    {"name": "大四喜", "reading": "だいスーシー", "cond": "鳴いてもOK（ダブル役満のルールもある）",
     "desc": "東・南・西・北の4種類すべてを刻子にする。",
     "example": "1z 1z 1z 2z 2z 2z 3z 3z 3z 4z 4z 4z 9s 9s"},
    {"name": "字一色", "reading": "ツーイーソー", "cond": "鳴いてもOK",
     "desc": "字牌（東南西北白發中）だけで作る。",
     "example": "1z 1z 1z 2z 2z 2z 5z 5z 5z 6z 6z 6z 7z 7z"},
    {"name": "清老頭", "reading": "チンロートー", "cond": "鳴いてもOK",
     "desc": "1と9の数牌だけで作る（字牌も使わない）。",
     "example": "1m 1m 1m 9m 9m 9m 1p 1p 1p 9s 9s 9s 1s 1s"},
    {"name": "緑一色", "reading": "リューイーソー", "cond": "鳴いてもOK",
     "desc": "緑色の牌（2・3・4・6・8索と發）だけで作る。",
     "example": "2s 3s 4s 2s 3s 4s 6s 6s 6s 8s 8s 8s 6z 6z"},
    {"name": "九蓮宝燈", "reading": "チューレンポートー", "cond": "門前のみ",
     "desc": "1種類の数牌で「1112345678999」＋同じ色のどれか1枚。",
     "example": "1p 1p 1p 2p 3p 4p 5p 5p 6p 7p 8p 9p 9p 9p"},
    {"name": "四槓子", "reading": "スーカンツ", "cond": "鳴いてもOK",
     "desc": "カンを4回する（槓子4組＋雀頭）。とてもめずらしい。",
     "example": ""},
    {"name": "天和", "reading": "テンホー", "cond": "親だけ",
     "desc": "親が配牌の14枚でもうアガっている。",
     "example": ""},
    {"name": "地和", "reading": "チーホー", "cond": "子だけ",
     "desc": "子が最初のツモでアガる（それまでに誰も鳴いていないとき）。",
     "example": ""},
]

DRAGONS = (31, 32, 33)
WINDS = (27, 28, 29, 30)
TERMINALS = tuple(o + k for o in (0, 9, 18) for k in (0, 8))
GREEN = (19, 20, 21, 23, 25, 32)  # 2s 3s 4s 6s 8s 發
CHUUREN = (3, 1, 1, 1, 1, 1, 1, 1, 3)


def yakuman_list() -> list[dict]:
    return [dict(y, example=y["example"].split()) for y in YAKUMAN_LIST]


def _sets_needed(counts: list[int], sets: int, pair: bool) -> int:
    """counts の牌種から刻子 sets 組（＋雀頭）を作るのに足りない枚数（多い牌から使う目安）。"""
    cs = sorted((min(c, 3) for c in counts), reverse=True)
    need = sum(3 - c for c in cs[:sets])
    if pair:
        rest = cs[sets:]
        need += 2 - min(rest[0], 2) if rest else 2
    return need


def yakuman_hints(hand: list[str], settings: RoundSettings, max_distance: int | None = None) -> list[dict]:
    """手牌から狙えそうな役満と「あと何枚」の目安。distance は完成までに足りない枚数。"""
    melds = settings.melds
    closed = not any(m.opened for m in melds)
    no_meld = not melds
    arr = [a + b for a, b in zip(T.to_34_array(hand), T.to_34_array(settings.meld_tiles))]
    n = sum(arr)
    gap = max(0, 14 - n)  # 13枚（ツモ前）なら完成まで少なくとも1枚引く
    out: list[dict] = []

    def add(name: str, need: int, note: str) -> None:
        out.append({"name": name, "distance": max(need, 0), "note": note, "han": "役満", "yakuman": True})

    # 国士無双：13種のうち何種あるか＋その中の1種が対子か
    if no_meld:
        kinds = sum(1 for i in range(34) if T.is_terminal_or_honor(i) and arr[i])
        pair = any(arr[i] >= 2 for i in range(34) if T.is_terminal_or_honor(i))
        add("国士無双", 14 - kinds - (1 if pair else 0),
            f"1・9・字牌13種のうち{kinds}種あり。2〜8の牌を切って、足りない種類を集める")

    # 四暗刻：鳴かずに刻子4組＋雀頭
    if closed:
        trips = sum(1 for c in arr if c >= 3)
        pairs = sum(1 for c in arr if c == 2)
        add("四暗刻", _sets_needed(arr, 4, True),
            f"刻子{trips}組・対子{pairs}組。鳴かずに同じ牌を3枚ずつ集める（ポンすると不成立）")

    # 大三元
    d = [arr[i] for i in DRAGONS]
    if sum(d) >= 4:
        add("大三元", _sets_needed(d, 3, False), f"白・發・中が{sum(d)}枚。3種類とも3枚ずつにする（ポンしてもOK）")

    # 小四喜・大四喜
    w = [arr[i] for i in WINDS]
    if sum(w) >= 6:
        add("小四喜", _sets_needed(w, 3, True), f"東南西北が{sum(w)}枚。3種類を3枚・1種類を2枚にする")
        if sum(w) >= 8:
            add("大四喜", _sets_needed(w, 4, False), "東南西北を4種類とも3枚ずつにする")

    # 字一色・清老頭・緑一色：使えない牌の枚数がそのまま「あと何枚」
    honors = sum(arr[27:])
    if honors >= 7:
        add("字一色", n - honors + gap, f"字牌が{honors}枚。字牌以外の{n - honors}枚を字牌に入れ替える")
    term = sum(arr[i] for i in TERMINALS)
    if term >= 7:
        add("清老頭", n - term + gap, f"1・9の数牌が{term}枚。それ以外の{n - term}枚を入れ替える")
    green = sum(arr[i] for i in GREEN)
    if green >= 7:
        add("緑一色", n - green + gap, f"緑の牌（2・3・4・6・8索と發）が{green}枚。それ以外の{n - green}枚を入れ替える")

    # 九蓮宝燈：1種類の数牌で 1112345678999＋1枚
    if no_meld:
        for off, name in ((0, "萬子"), (9, "筒子"), (18, "索子")):
            if settings.is_sanma and off == 0:
                continue
            cnt = sum(arr[off:off + 9])
            if cnt >= 9:
                missing = sum(max(0, CHUUREN[k] - arr[off + k]) for k in range(9))
                add("九蓮宝燈", max(missing, 14 - cnt), f"{name}が{cnt}枚。{name}だけで1112345678999の形を作る")

    out.sort(key=lambda h: (h["distance"], h["name"]))
    if max_distance is not None:
        out = [h for h in out if h["distance"] <= max_distance]
    return out


def is_yakuman_score(score: dict | None) -> bool:
    """点数計算の結果が役満（数え役満を含む）か。"""
    if not score or not score.get("ok"):
        return False
    return any(y.get("yakuman") for y in score.get("yaku") or []) or (score.get("han") or 0) >= 13
