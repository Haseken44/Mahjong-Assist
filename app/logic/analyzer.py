"""手牌の分析：向聴数・何切る推奨・有効牌・狙える役のヒント。"""
from __future__ import annotations

from collections import Counter

from mahjong.shanten import Shanten

from . import tiles as T
from .scorer import score_hand
from .settings import RoundSettings

_shanten = Shanten()

WIND_INDEX = {"east": 27, "south": 28, "west": 29, "north": 30}


def shanten_of(arr34: list[int]) -> int:
    return _shanten.calculate_shanten(arr34)


def shanten_label(n: int) -> str:
    if n == -1:
        return "アガリ"
    if n == 0:
        return "テンパイ"
    return f"{n}向聴（あと{n}枚でテンパイ）"


def _remaining(index: int, hand34: list[int], visible34: list[int]) -> int:
    return max(4 - hand34[index] - visible34[index], 0)


_SANMA_SKIP = {T.to_34(t) for t in T.SANMA_EXCLUDED}


def effective_tiles(hand34: list[int], visible34: list[int], players: int = 4) -> tuple[int, list[dict]]:
    """13枚（または 3n+1 枚）の手牌に対する向聴数と有効牌（受け入れ）。三麻では萬子2〜8を除く。"""
    base = shanten_of(hand34)
    result = []
    for i in range(34):
        if players == 3 and i in _SANMA_SKIP:
            continue
        if hand34[i] >= 4:
            continue
        remaining = _remaining(i, hand34, visible34)
        hand34[i] += 1
        if shanten_of(hand34) < base:
            result.append({"tile": T.from_34(i), "remaining": remaining})
        hand34[i] -= 1
    return base, result


def _visible(settings: RoundSettings, extra: list[str] | None = None) -> list[int]:
    return T.to_34_array(list(settings.dora_indicators) + list(extra or []))


def _wait_scores(hand13: list[str], waits: list[dict], settings: RoundSettings) -> list[dict]:
    out = []
    for w in waits:
        tile = w["tile"]
        r = score_hand(hand13 + [tile], settings, win_tile=tile)
        riichi_needed = False
        if not r.ok and not settings.is_riichi and r.error and "役なし" in r.error:
            # 門前なのでリーチをかければアガれる。リーチ時の点数を示す
            r2 = score_hand(hand13 + [tile], settings.model_copy(update={"is_riichi": True}), win_tile=tile)
            if r2.ok:
                r, riichi_needed = r2, True
        out.append({
            "riichi_needed": riichi_needed,
            "tile": tile,
            "remaining": w["remaining"],
            "ok": r.ok,
            "total": r.total,
            "payment": r.payment,
            "han": r.han,
            "fu": r.fu,
            "level": r.level,
            "yaku": [y["name"] for y in r.yaku],
            "error": r.error,
        })
    return out


def discard_options(hand: list[str], settings: RoundSettings) -> list[dict]:
    """14枚（3n+2枚）の手牌から、各打牌後の向聴数と受け入れ枚数を返す（良い順）。"""
    visible = _visible(settings)
    seen: set[str] = set()
    options = []
    for i, tile in enumerate(hand):
        if tile in seen:
            continue
        seen.add(tile)
        rest = hand[:i] + hand[i + 1:]
        arr = T.to_34_array(rest)
        sh, eff = effective_tiles(arr, visible, settings.players)
        options.append({
            "discard": tile,
            "shanten": sh,
            "ukeire": sum(e["remaining"] for e in eff),
            "effective": eff,
            "_rest": rest,
        })
    # 向聴数が小さい順、受け入れが多い順。同点なら字牌・端牌を先に切る（初心者向けの定石）
    options.sort(key=lambda o: (o["shanten"], -o["ukeire"], 0 if T.is_terminal_or_honor(T.to_34(o["discard"])) else 1, T.is_red(o["discard"])))
    for o in options[:3]:
        if o["shanten"] == 0:
            o["waits"] = _wait_scores(o["_rest"], o["effective"], settings)
    for o in options:
        o.pop("_rest")
    return options


def yaku_hints(hand: list[str], settings: RoundSettings) -> list[dict]:
    """初心者向け：狙えそうな役と「あと何枚」の目安（簡易ヒューリスティック）。"""
    arr = T.to_34_array(hand)
    n = len(hand)
    hints: list[dict] = []

    def add(name: str, distance: int, note: str, han: str) -> None:
        hints.append({"name": name, "distance": max(distance, 0), "note": note, "han": han})

    # 立直
    add("立直", 0, "鳴かずにテンパイしたら「リーチ」と宣言するだけで1翻。迷ったらまずこれ", "1翻")

    # 断么九
    yaochu = sum(arr[i] for i in range(34) if T.is_terminal_or_honor(i))
    if yaochu <= 4:
        add("断么九（タンヤオ）", yaochu, f"1・9・字牌を{yaochu}枚切れば成立。2〜8だけで作る", "1翻")

    # 役牌
    yakuhai: dict[int, list[str]] = {31: ["三元牌"], 32: ["三元牌"], 33: ["三元牌"]}
    yakuhai.setdefault(WIND_INDEX[settings.seat_wind], []).append("自風")
    yakuhai.setdefault(WIND_INDEX[settings.round_wind], []).append("場風")
    for idx in sorted(yakuhai):
        names = "・".join(yakuhai[idx])
        tile_name = T.display_name(T.from_34(idx))
        han = f"{len(yakuhai[idx])}翻"
        if arr[idx] >= 3:
            add(f"役牌 {tile_name}", 0, f"{tile_name}（{names}）を3枚持っているので役が確定", han)
        elif arr[idx] == 2:
            add(f"役牌 {tile_name}", 1, f"{tile_name}（{names}）があと1枚で役。出たらポンしてもOK", han)

    sanma = settings.is_sanma
    suits = (("p", "筒子"), ("s", "索子")) if sanma else (("m", "萬子"), ("p", "筒子"), ("s", "索子"))

    # 抜きドラ（三麻）
    if sanma and arr[30] > 0:
        add("抜きドラ（北）", 0, f"北を{arr[30]}枚持っています。「北」と言って抜くとドラ1になり、代わりの牌を引けます（抜いたら設定の抜きドラを増やす）", "ドラ1/枚")

    # 混一色・清一色
    honors = sum(arr[27:])
    for s, name in suits:
        off = T.SUIT_OFFSET[s]
        cnt = sum(arr[off:off + 9])
        others = n - cnt - honors
        if others <= 4 and cnt >= 6:
            add("混一色（ホンイツ）", others, f"{name}と字牌以外の{others}枚を切れば狙える", "3翻（鳴き2翻）")
        if n - cnt <= 4 and cnt >= 9:
            add("清一色（チンイツ）", n - cnt, f"{name}以外の{n - cnt}枚を切れば狙える", "6翻（鳴き5翻）")

    # 七対子
    pairs = sum(1 for c in arr if c >= 2)
    if pairs >= 4:
        add("七対子（チートイツ）", 7 - pairs, f"対子が{pairs}組。あと{7 - pairs}組で完成（同じ牌2枚×7組）", "2翻")

    # 対々和
    trip = sum(1 for c in arr if c >= 3)
    if trip >= 2 and pairs >= 4:
        add("対々和（トイトイ）", 4 - trip, f"刻子が{trip}組。対子をポンして刻子4組を目指す", "2翻")

    # 一気通貫
    for s, name in suits:
        off = T.SUIT_OFFSET[s]
        missing = sum(1 for k in range(9) if arr[off + k] == 0)
        if missing <= 3:
            add("一気通貫（イッツー）", missing, f"{name}の1〜9を揃える。あと{missing}種類", "2翻（鳴き1翻）")

    # 三色同順
    best = None
    for start in range(0 if sanma else 7):  # 三麻は萬子の2〜8が無いので三色同順はできない
        missing = sum(1 for s in (0, 9, 18) for k in range(3) if arr[s + start + k] == 0)
        if best is None or missing < best[0]:
            best = (missing, start)
    if best and best[0] <= 3:
        a = best[1] + 1
        add("三色同順（サンショク）", best[0], f"萬子・筒子・索子で{a}{a + 1}{a + 2}を揃える。あと{best[0]}枚", "2翻（鳴き1翻）")

    # 国士無双
    kinds = sum(1 for i in range(34) if T.is_terminal_or_honor(i) and arr[i] > 0)
    if kinds >= 9:
        add("国士無双", 13 - kinds, f"1・9・字牌13種のうち{kinds}種あり。役満！", "役満")

    hints.sort(key=lambda h: (h["distance"], h["name"] != "立直"))
    return hints


def analyze(hand: list[str], settings: RoundSettings) -> dict:
    """手牌を総合分析する。13枚=待ち/有効牌、14枚=何切る＋アガリなら点数。"""
    hand = [T.validate(t) for t in hand]
    T.check_counts(hand + settings.dora_indicators)
    n = len(hand)
    if settings.is_sanma:
        bad = [t for t in hand if t in T.SANMA_EXCLUDED]
        if bad:
            raise T.TileError(f"三人麻雀では萬子の2〜8は使いません（{'・'.join(T.display_name(t) for t in bad)}）。読み違いなら直してください")
    result: dict = {
        "tiles": hand,
        "sorted": T.sort_tiles(hand),
        "count": n,
        "names": [T.display_name(t) for t in hand],
    }
    if n == 0:
        result["message"] = "牌が認識されていません。手牌をカメラに映すか、手動で入力してください"
        return result
    if n > 14:
        result["message"] = f"牌が{n}枚あります。14枚以下にしてください"
        return result

    result["hints"] = yaku_hints(hand, settings)

    if n % 3 == 1:
        sh, eff = effective_tiles(T.to_34_array(hand), _visible(settings), settings.players)
        result.update(shanten=sh, shanten_label=shanten_label(sh), effective=eff,
                      ukeire=sum(e["remaining"] for e in eff))
        if sh == 0:
            result["waits"] = _wait_scores(hand, eff, settings)
            result["message"] = "テンパイ！待ち牌とアガったときの点数です"
        else:
            result["message"] = f"{shanten_label(sh)}。有効牌を引いたら手が進みます"
    elif n % 3 == 2:
        sh = shanten_of(T.to_34_array(hand))
        result.update(shanten=sh, shanten_label=shanten_label(sh))
        if sh == -1 and n == 14:
            result["score"] = score_hand(hand, settings).as_dict()
            result["message"] = "アガリ形です！"
        options = discard_options(hand, settings)
        result["discards"] = options
        if sh != -1 and options:
            best = options[0]
            if settings.is_sanma and "4z" in hand:
                # 三麻の北は切るより抜く方が得（ドラ1＋もう1枚引ける）
                result["message"] = "「北」は捨てずに抜きドラにしましょう（「北」と言って脇に出し、1枚引く）。抜いたら設定の抜きドラを1つ増やしてください"
            else:
                result["message"] = f"おすすめは「{T.display_name(best['discard'])}」切り（{shanten_label(best['shanten'])}・受け入れ{best['ukeire']}枚）"
    else:
        result["message"] = f"牌が{n}枚です。13枚か14枚にしてください（鳴きは未対応）"
    return result
