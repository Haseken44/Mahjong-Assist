"""卓ごとのルール設定（雀魂の段位戦ルールを既定のプリセットにする）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Rules(BaseModel):
    """点数計算と分析に関わるルール。値を変えればハウスルールにも合わせられる。"""

    preset: str = Field("mahjongsoul", description="プリセット名（mahjongsoul / custom）")
    aka_dora: bool = Field(True, description="赤ドラ（赤五）あり")
    kuitan: bool = Field(True, description="喰いタン（鳴いた断么九）あり")
    ippatsu: bool = Field(True, description="一発あり")
    ura_dora: bool = Field(True, description="裏ドラあり")
    kan_dora: bool = Field(True, description="カンドラあり（カンのたびにドラ表示牌が1枚増える）")
    kan_ura: bool = Field(True, description="カン裏あり")
    kiriage: bool = Field(False, description="切り上げ満貫（4翻30符・3翻60符を満貫にする）")
    kazoe_yakuman: bool = Field(True, description="数え役満（13翻以上を役満にする）")
    double_yakuman: bool = Field(True, description="ダブル役満あり（国士十三面・四暗刻単騎・純正九蓮・大四喜）")
    honba_4p: int = Field(300, ge=0, le=1500, description="四麻の1本場あたりの加算（ロン時）")
    honba_3p: int = Field(200, ge=0, le=1500, description="三麻の1本場あたりの加算（ロン時）")
    sanma_chi: bool = Field(False, description="三麻でチーを認める")
    sanma_nukidora: bool = Field(True, description="三麻で北を抜きドラにする")
    sanma_tsumo_son: bool = Field(True, description="三麻のツモ損あり（なしなら北家分を折半）")
    max_kans: int = Field(4, ge=1, le=4, description="1局で卓全体のカンの上限")


PRESETS: dict[str, Rules] = {
    "mahjongsoul": Rules(),
}

# 画面に表示するための説明
RULE_LABELS = {
    "aka_dora": "赤ドラ（赤五）",
    "kuitan": "喰いタン",
    "ippatsu": "一発",
    "ura_dora": "裏ドラ",
    "kan_dora": "カンドラ",
    "kan_ura": "カン裏",
    "kiriage": "切り上げ満貫",
    "kazoe_yakuman": "数え役満",
    "double_yakuman": "ダブル役満",
    "sanma_chi": "三麻のチー",
    "sanma_nukidora": "三麻の北抜きドラ",
    "sanma_tsumo_son": "三麻のツモ損",
}
