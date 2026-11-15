"""アガリ判定・符計算・点数計算（mahjong ライブラリのラッパー）。

現時点では門前（鳴きなし）の手牌のみ対応。
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
}

_calculator = HandCalculator()
_scores = ScoresCalculator()


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


def _config(s: RoundSettings) -> HandConfig:
    riichi = s.is_riichi and not s.is_open  # 鳴いているとリーチできない
    return HandConfig(
        is_tsumo=s.is_tsumo,
        is_riichi=riichi,
        is_ippatsu=s.is_ippatsu and riichi and s.rules.ippatsu,
        player_wind=WIND_CONST[s.seat_wind],
        round_wind=WIND_CONST[s.round_wind],
        kyoutaku_number=s.kyoutaku,
        tsumi_number=0,  # 本場はルールの加算額で自前計算する
        options=_options(s),
    )


def _ceil100(x: float) -> int:
    return int(-(-x // 100) * 100)


def _payments(cost: dict, s: RoundSettings) -> tuple[int, str]:
    """(アガった人が受け取る合計, 支払いの説明) を返す。三麻のツモ損/折半に対応。"""
    kyoutaku = s.kyoutaku * 1000
    per_honba = s.rules.honba_3p if s.is_sanma else s.rules.honba_4p
    payers = 2 if s.is_sanma else 3
    honba_each = _ceil100(per_honba * s.honba / payers) if s.honba else 0
    cost = dict(cost, main_bonus=honba_each, additional_bonus=honba_each)
    dealer_pay = cost["main"] + cost["main_bonus"]
    child_pay = cost["additional"] + cost["additional_bonus"]
    if not s.is_tsumo:
        ron = cost["main"] + per_honba * s.honba
        return ron + kyoutaku, f"ロン {ron}点"

    if s.players == 4:
        if s.is_dealer:
            return dealer_pay * 3 + kyoutaku, f"ツモ {dealer_pay}点オール"
        return dealer_pay + child_pay * 2 + kyoutaku, f"ツモ 子{child_pay}点 / 親{dealer_pay}点"

    # 三人麻雀：支払うのは2人だけ
    if s.tsumo_son:
        if s.is_dealer:
            return dealer_pay * 2 + kyoutaku, f"ツモ {dealer_pay}点オール（2人から・ツモ損あり）"
        return dealer_pay + child_pay + kyoutaku, f"ツモ 子{child_pay}点 / 親{dealer_pay}点（ツモ損あり）"
    # ツモ損なし：いない北家の分を2人で折半する
    if s.is_dealer:
        each = cost["main"] + _ceil100(cost["main"] / 2) + cost["main_bonus"]
        return each * 2 + kyoutaku, f"ツモ {each}点オール（2人から・北家分折半）"
    half = _ceil100(cost["additional"] / 2)
    d = cost["main"] + half + cost["main_bonus"]
    c = cost["additional"] + half + cost["additional_bonus"]
    return d + c + kyoutaku, f"ツモ 子{c}点 / 親{d}点（北家分折半）"


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


def score_hand(hand: list[str], settings: RoundSettings, win_tile: str | None = None) -> ScoreResult:
    """アガリ形の点数を計算する。hand は鳴き以外の手牌（14 − 3×鳴きの数 枚）。

    win_tile 省略時は settings.win_tile、それも無ければ手牌の最後の牌。
    """
    s = settings
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
    config = _config(s)
    # ドラは自前で数える（三麻の 1m→9m・裏ドラ・ルールの有無に対応するため）
    r = _calculator.estimate_hand_value(tiles_136, win_136, melds=melds or None, config=config)
    if r.error:
        return ScoreResult(ok=False, error=ERROR_JA.get(r.error, r.error), win_tile=win)

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

    total, payment = _payments(cost, s)
    level = LEVEL_JA.get(cost.get("yaku_level", ""), cost.get("yaku_level", ""))
    return ScoreResult(ok=True, han=han, fu=r.fu, yaku=yaku, total=total, payment=payment, level=level, win_tile=win)
