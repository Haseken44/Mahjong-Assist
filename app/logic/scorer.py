"""アガリ判定・符計算・点数計算（mahjong ライブラリのラッパー）。

現時点では門前（鳴きなし）の手牌のみ対応。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from mahjong.constants import EAST, NORTH, SOUTH, WEST
from mahjong.hand_calculating.hand import HandCalculator
from mahjong.hand_calculating.hand_config import HandConfig, OptionalRules

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
_rules = OptionalRules(has_aka_dora=True, has_open_tanyao=True)


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


def _config(s: RoundSettings) -> HandConfig:
    return HandConfig(
        is_tsumo=s.is_tsumo,
        is_riichi=s.is_riichi,
        is_ippatsu=s.is_ippatsu and s.is_riichi,
        player_wind=WIND_CONST[s.seat_wind],
        round_wind=WIND_CONST[s.round_wind],
        kyoutaku_number=s.kyoutaku,
        tsumi_number=s.honba,
        options=_rules,
    )


def _payment_text(cost: dict, s: RoundSettings) -> str:
    if not s.is_tsumo:
        return f"ロン {cost['main'] + cost['main_bonus']}点"
    if s.is_dealer:
        return f"ツモ {cost['main'] + cost['main_bonus']}点オール"
    child = cost["additional"] + cost["additional_bonus"]
    dealer = cost["main"] + cost["main_bonus"]
    return f"ツモ 子{child}点 / 親{dealer}点"


def score_hand(hand: list[str], settings: RoundSettings, win_tile: str | None = None) -> ScoreResult:
    """14枚の手牌の点数を計算する。win_tile 省略時は settings.win_tile、それも無ければ最後の牌。"""
    if len(hand) != 14:
        return ScoreResult(ok=False, error="点数計算には14枚の手牌が必要です")
    T.check_counts(hand + settings.dora_indicators)
    win = win_tile or settings.win_tile or hand[-1]
    if T.normalize(win) not in [T.normalize(t) for t in hand]:
        return ScoreResult(ok=False, error=ERROR_JA["winning_tile_not_in_hand"], win_tile=win)

    hand_136 = T.to_136_array(hand)
    win_136 = T.tile_to_136(win, hand_136)
    dora_136 = [T.to_34(t) * 4 + 1 for t in settings.dora_indicators]

    r = _calculator.estimate_hand_value(hand_136, win_136, dora_indicators=dora_136 or None, config=_config(settings))
    if r.error:
        return ScoreResult(ok=False, error=ERROR_JA.get(r.error, r.error), win_tile=win)

    yaku = [
        {"name": YAKU_JA.get(y.yaku_id, y.name), "han": y.han_closed, "yakuman": bool(y.is_yakuman)}
        for y in r.yaku
    ]
    level = LEVEL_JA.get(r.cost.get("yaku_level", ""), r.cost.get("yaku_level", ""))
    return ScoreResult(
        ok=True,
        han=r.han,
        fu=r.fu,
        yaku=yaku,
        total=r.cost["total"],
        payment=_payment_text(r.cost, settings),
        level=level,
        win_tile=win,
    )

