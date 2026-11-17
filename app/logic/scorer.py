"""アガリ判定・符計算・点数計算（mahjong ライブラリのラッパー）。

鳴き・ドラ（三麻・裏ドラ・抜きドラ）・本場・供託に対応。
ロンとツモの両方の点数と、符計算の内訳（何で何符か）を返す。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from mahjong.constants import EAST, NORTH, SOUTH, WEST
from mahjong.hand_calculating.hand import HandCalculator
from mahjong.hand_calculating.hand_config import HandConfig, HandConstants, OptionalRules
from mahjong.meld import Meld
from mahjong.hand_calculating.scores import ScoresCalculator

from . import tiles as T
from .settings import RoundSettings

WIND_CONST = {"east": EAST, "south": SOUTH, "west": WEST, "north": NORTH}

YAKU_JA = {
    0: "門前清自摸和", 1: "立直", 2: "オープン立直", 3: "一発", 4: "槍槓", 5: "嶺上開花",
    6: "海底摸月", 7: "河底撈魚", 8: "ダブル立直", 9: "ダブルオープン立直", 10: "流し満貫",
    11: "人和", 12: "平和", 13: "断么九", 14: "一盃口", 15: "役牌 白", 16: "役牌 發",
    17: "役牌 中", 18: "役牌 東", 19: "役牌 南", 20: "役牌 西", 21: "役牌 北",
    22: "自風牌", 23: "場風牌", 24: "三色同順", 25: "一気通貫", 26: "混全帯么九",
    27: "混老頭", 28: "対々和", 29: "三暗刻", 30: "三槓子", 31: "三色同刻", 32: "七対子",
    33: "小三元", 34: "混一色", 35: "純全帯么九", 36: "二盃口", 37: "清一色",
    38: "国士無双", 39: "九蓮宝燈", 40: "四暗刻", 41: "大三元", 42: "小四喜", 43: "緑一色",
    44: "四槓子", 45: "字一色", 46: "清老頭", 47: "大車輪", 48: "大数隣", 49: "大四喜",
    50: "国士無双十三面待ち", 51: "四暗刻単騎", 52: "純正九蓮宝燈", 53: "天和", 54: "地和",
    55: "人和", 56: "差し込み", 57: "八連荘", 58: "ドラ", 59: "赤ドラ",
}

LEVEL_JA = {
    "mangan": "満貫", "haneman": "跳満", "baiman": "倍満", "sanbaiman": "三倍満",
    "yakuman": "役満", "kazoe yakuman": "数え役満", "2x yakuman": "ダブル役満",
    "3x yakuman": "トリプル役満", "4x yakuman": "四倍役満", "5x yakuman": "五倍役満",
    "6x yakuman": "六倍役満",
}

ERROR_JA = {
    "winning_tile_not_in_hand": "アガリ牌が手牌にありません",
    "open_hand_riichi_not_allowed": "鳴いているとリーチできません",
    "hand_not_winning": "アガリの形になっていません",
    "no_yaku": "役がありません（役なし）。リーチをかけるか、役を作りましょう",
    "no_yaku_open": "役がありません（役なし）",
    "chankan_with_tsumo_not_allowed": "槍槓はロンのときだけです",
    "rinshan_without_tsumo_not_allowed": "嶺上開花はツモのときだけです",
    "haitei_without_tsumo_not_allowed": "海底摸月はツモのときだけです",
    "houtei_with_tsumo_not_allowed": "河底撈魚はロンのときだけです",
    "haitei_with_rinshan_not_allowed": "嶺上開花と海底摸月は同時に付きません",
    "houtei_with_chankan_not_allowed": "槍槓と河底撈魚は同時に付きません",
    "tenhou_not_as_dealer_not_allowed": "天和は親だけです",
    "tenhou_without_tsumo_not_allowed": "天和はツモのときだけです",
    "tenhou_with_meld_not_allowed": "天和は鳴いていると付きません",
    "chiihou_as_dealer_not_allowed": "地和は子だけです",
    "chiihou_without_tsumo_not_allowed": "地和はツモのときだけです",
    "chiihou_with_meld_not_allowed": "地和は鳴いていると付きません",
    "ippatsu_without_riichi_not_allowed": "一発はリーチのときだけです",
    "daburi_without_riichi_not_allowed": "ダブルリーチはリーチのときだけです",
}

_calculator = HandCalculator()
_scores = ScoresCalculator()


# 符の内訳の名前（mahjong ライブラリの reason → 日本語と説明）
FU_JA = {
    "closed_pon": "暗刻（2〜8の牌）",
    "closed_terminal_pon": "暗刻（1・9・字牌）",
    "open_pon": "明刻（2〜8の牌）",
    "open_terminal_pon": "明刻（1・9・字牌）",
    "closed_kan": "暗槓（2〜8の牌）",
    "closed_terminal_kan": "暗槓（1・9・字牌）",
    "open_kan": "明槓（2〜8の牌）",
    "open_terminal_kan": "明槓（1・9・字牌）",
    "valued_pair": "雀頭が役牌",
    "double_valued_pair": "雀頭が連風牌（自風かつ場風）",
    "pair_wait": "単騎待ち",
    "kanchan": "嵌張（カンチャン）待ち",
    "penchan": "辺張（ペンチャン）待ち",
    "tsumo": "ツモ符",
    "hand_without_fu": "鳴いた平和形（30符にする加符）",
}


@dataclass
class ScoreResult:
    ok: bool
    error: str | None = None
    han: int = 0
    fu: int = 0
    yaku: list[dict] = field(default_factory=list)
    total: int = 0
    payment: str = ""
    level: str = ""
    win_tile: str | None = None
    tsumo: bool = False
    pays: list[dict] = field(default_factory=list)   # 誰がいくら払うか [{"who": "放銃した人", "points": 8000}]
    fu_details: list[dict] = field(default_factory=list)  # 符の内訳 [{"name": "副底", "fu": 20}]
    fu_raw: int = 0  # 切り上げ前の符

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _options(s: RoundSettings) -> OptionalRules:
    r = s.rules
    return OptionalRules(
        has_aka_dora=r.aka_dora,
        has_open_tanyao=r.kuitan,
        has_double_yakuman=r.double_yakuman,
        kazoe_limit=HandConstants.KAZOE_LIMITED if r.kazoe_yakuman else HandConstants.KAZOE_SANBAIMAN,
        kiriage=r.kiriage,
    )


def _config(s: RoundSettings, tsumo: bool | None = None) -> HandConfig:
    tsumo = s.is_tsumo if tsumo is None else tsumo
    riichi = (s.is_riichi or s.is_double_riichi) and not s.is_open  # 鳴いているとリーチできない
    first = s.is_first_draw and tsumo and not s.melds
    return HandConfig(
        is_tsumo=tsumo,
        is_riichi=riichi,
        is_ippatsu=s.is_ippatsu and riichi and s.rules.ippatsu,
        is_daburu_riichi=s.is_double_riichi and riichi,
        is_rinshan=s.is_rinshan and tsumo,
        is_chankan=s.is_chankan and not tsumo,
        is_haitei=s.is_last_tile and tsumo and not s.is_rinshan,
        is_houtei=s.is_last_tile and not tsumo,
        is_tenhou=first and s.is_dealer,
        is_chiihou=first and not s.is_dealer,
        player_wind=WIND_CONST[s.seat_wind],
        round_wind=WIND_CONST[s.round_wind],
        kyoutaku_number=s.kyoutaku,
        tsumi_number=0,  # 本場はルールの加算額で自前計算する
        options=_options(s),
    )


def _ceil100(x: float) -> int:
    return int(-(-x // 100) * 100)


def _payments(cost: dict, s: RoundSettings, tsumo: bool) -> tuple[int, str, list[dict]]:
    """(アガった人が受け取る合計, 支払いの説明, 誰がいくら払うか) を返す。

    本場は1本につき 四麻300点・三麻200点（ルールで変更可）。ツモなら払う人で分ける。
    三麻のツモは「ツモ損あり（2人だけが払う）」と「北家分を折半」に対応。
    """
    kyoutaku = s.kyoutaku * 1000
    per_honba = s.rules.honba_3p if s.is_sanma else s.rules.honba_4p
    payers = 2 if s.is_sanma else 3
    honba_each = _ceil100(per_honba * s.honba / payers) if s.honba else 0
    note = f"（供託 {kyoutaku}点も受け取る）" if kyoutaku else ""
    if not tsumo:
        ron = cost["main"] + per_honba * s.honba
        if s.is_nima:
            return ron + kyoutaku, f"ロン 相手から {ron}点{note}", [{"who": "相手（ロンされた人）", "points": ron}]
        return ron + kyoutaku, f"ロン 放銃した人から {ron}点{note}", [{"who": "放銃した人（ロンされた人）", "points": ron}]

    main, add = cost["main"], cost["additional"]
    if s.is_nima:
        # 二麻のツモ：相手1人が四麻の3人分をまとめて払う（ロンと同じ点数）
        whole = (main * 3 if s.is_dealer else main + add * 2) + per_honba * s.honba
        return whole + kyoutaku, f"ツモ 相手から {whole}点（二麻）{note}", [{"who": "相手", "points": whole}]
    if s.players == 3 and not s.tsumo_son:
        # ツモ損なし：いない北家の分を2人で折半する
        if s.is_dealer:
            main = main + _ceil100(main / 2)
        else:
            half = _ceil100(add / 2)
            main, add = main + half, add + half
    dealer_pay = main + honba_each
    child_pay = add + honba_each
    tag = "" if s.players == 4 else ("（ツモ損あり）" if s.tsumo_son else "（北家分を折半）")
    if s.is_dealer:
        n = payers
        return (dealer_pay * n + kyoutaku, f"ツモ {dealer_pay}点オール{tag}{note}",
                [{"who": f"子 {n}人がそれぞれ", "points": dealer_pay}])
    n_child = payers - 1
    return (dealer_pay + child_pay * n_child + kyoutaku,
            f"ツモ 子{child_pay}点・親{dealer_pay}点{tag}{note}",
            [{"who": "親", "points": dealer_pay}, {"who": f"子 {n_child}人がそれぞれ" if n_child > 1 else "子", "points": child_pay}])


def _fu_breakdown(r, s: RoundSettings, tsumo: bool) -> tuple[list[dict], int]:
    """符の内訳と、切り上げ前の合計を返す。"""
    out = []
    for d in r.fu_details or []:
        reason, fu = d["reason"], d["fu"]
        if reason == "base":
            if fu == 25:
                out.append({"name": "七対子（固定）", "fu": 25})
            elif fu == 30 and not s.is_open and not tsumo:
                out += [{"name": "副底（アガリの基本）", "fu": 20}, {"name": "門前ロン（鳴かずにロン）", "fu": 10}]
            else:
                out.append({"name": "副底（アガリの基本）", "fu": fu})
        else:
            out.append({"name": FU_JA.get(reason, reason), "fu": fu})
    if tsumo and r.fu == 20 and not s.is_open and not any(x["name"] == "ツモ符" for x in out):
        out.append({"name": "平和のツモはツモ符なし", "fu": 0})
    raw = sum(x["fu"] for x in out)
    return out, raw


def _build_tiles(hand: list[str], s: RoundSettings) -> tuple[list[int], list[Meld]]:
    """手牌（鳴き以外）と鳴きの牌を、重複しない136番号にまとめて変換する。"""
    all_tiles = list(hand) + s.meld_tiles
    ids = T.to_136_array(all_tiles)
    hand_ids = ids[: len(hand)]
    melds, pos = [], len(hand)
    for m in s.melds:
        mids = ids[pos: pos + len(m.tiles)]
        pos += len(m.tiles)
        kind = {"pon": Meld.PON, "chi": Meld.CHI, "kan": Meld.KAN, "ankan": Meld.KAN}[m.type]
        melds.append(Meld(meld_type=kind, tiles=mids, opened=m.opened))
    return hand_ids + ids[len(hand):], melds


def _dora_count(tiles: list[str], indicators: list[str], s: RoundSettings) -> int:
    dora = [T.sanma_dora_from_indicator(i) if s.is_sanma else _next_tile(i) for i in indicators]
    names = [T.normalize(t) for t in tiles]
    return sum(names.count(d) for d in dora)


def _next_tile(indicator: str) -> str:
    t = T.normalize(indicator)
    n, suit = int(t[0]), t[1]
    if suit == "z":
        return f"{n % 4 + 1}z" if n <= 4 else f"{(n - 5 + 1) % 3 + 5}z"
    return f"{n % 9 + 1}{suit}"


def score_hand(hand: list[str], settings: RoundSettings, win_tile: str | None = None,
               tsumo: bool | None = None) -> ScoreResult:
    """アガリ形の点数を計算する。hand は鳴き以外の手牌（14 − 3×鳴きの数 枚）。

    win_tile 省略時は settings.win_tile、それも無ければ手牌の最後の牌。
    tsumo 省略時は設定の「ツモ」に従う（True=ツモ、False=ロン）。
    """
    s = settings
    tsumo = s.is_tsumo if tsumo is None else tsumo
    if tsumo and s.is_chankan:
        return ScoreResult(ok=False, error="槍槓はロンのときだけです", tsumo=tsumo)
    if not tsumo and (s.is_rinshan or s.is_first_draw):
        return ScoreResult(ok=False, error="嶺上開花・天和・地和はツモのときだけです", tsumo=tsumo)
    need = 14 - 3 * len(s.melds)
    if len(hand) != need:
        return ScoreResult(ok=False, error=f"点数計算には鳴き以外の手牌が{need}枚必要です")
    T.check_counts(hand + s.meld_tiles + s.dora_indicators)
    if s.is_sanma:
        bad = [t for t in hand if t in T.SANMA_EXCLUDED]
        if bad:
            return ScoreResult(ok=False, error=f"三人麻雀では萬子の2〜8は使いません: {', '.join(bad)}")
    if not s.rules.aka_dora and any(T.is_red(t) for t in hand):
        return ScoreResult(ok=False, error="このルールでは赤ドラ（赤五）はありません")
    win = win_tile or s.win_tile or hand[-1]
    if T.normalize(win) not in [T.normalize(t) for t in hand]:
        return ScoreResult(ok=False, error=ERROR_JA["winning_tile_not_in_hand"], win_tile=win)

    tiles_136, melds = _build_tiles(hand, s)
    win_136 = T.tile_to_136(win, tiles_136[: len(hand)])
    config = _config(s, tsumo)
    # ドラは自前で数える（三麻の 1m→9m・裏ドラ・ルールの有無に対応するため）
    r = _calculator.estimate_hand_value(tiles_136, win_136, melds=melds or None, config=config)
    if r.error:
        return ScoreResult(ok=False, error=ERROR_JA.get(r.error, r.error), win_tile=win, tsumo=tsumo)

    yaku = [
        {"name": YAKU_JA.get(y.yaku_id, y.name), "han": y.han_open if s.is_open and y.han_open else y.han_closed,
         "yakuman": bool(y.is_yakuman)}
        for y in r.yaku
    ]
    han, cost = r.han, r.cost
    is_yakuman = any(y["yakuman"] for y in yaku)
    if not is_yakuman:
        all_tiles = hand + s.meld_tiles
        extra = []
        n = _dora_count(all_tiles, s.dora_indicators, s)
        if n:
            extra.append(("ドラ", n))
        if s.is_riichi and not s.is_open and s.rules.ura_dora:
            n = _dora_count(all_tiles, s.ura_indicators, s)
            if n:
                extra.append(("裏ドラ", n))
        if s.is_sanma and s.nukidora:
            extra.append(("抜きドラ（北）", s.nukidora))
        for name, n in extra:
            han += n
            yaku.append({"name": name, "han": n, "yakuman": False})
        if extra:
            cost = _scores.calculate_scores(han, r.fu, config)

    total, payment, pays = _payments(cost, s, tsumo)
    level = LEVEL_JA.get(cost.get("yaku_level", ""), cost.get("yaku_level", ""))
    details, raw = ([], 0) if is_yakuman else _fu_breakdown(r, s, tsumo)
    return ScoreResult(ok=True, han=han, fu=r.fu, yaku=yaku, total=total, payment=payment, level=level,
                       win_tile=win, tsumo=tsumo, pays=pays, fu_details=details, fu_raw=raw)


def score_both(hand: list[str], settings: RoundSettings, win_tile: str | None = None) -> dict:
    """同じアガリ形を「ロンした場合」「ツモした場合」の両方で計算する。"""
    # 親・子を入れ替えた場合のツモの支払い（参考。自風の設定を間違えやすいので両方見せる）
    other_seat = "south" if settings.is_dealer else "east"
    flipped = settings.model_copy(update={"seat_wind": other_seat})
    other = score_hand(hand, flipped, win_tile, tsumo=True)
    other_ron = score_hand(hand, flipped, win_tile, tsumo=False)
    return {
        "ron": score_hand(hand, settings, win_tile, tsumo=False).as_dict(),
        "tsumo": score_hand(hand, settings, win_tile, tsumo=True).as_dict(),
        "tsumo_other": other.as_dict() | {"dealer": not settings.is_dealer},
        "ron_other": other_ron.as_dict() | {"dealer": not settings.is_dealer},
        "dealer": settings.is_dealer,
        "selected": "tsumo" if settings.is_tsumo else "ron",
    }
