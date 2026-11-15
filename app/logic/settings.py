"""局・アガリ条件の設定（鳴き・ドラ・ルールを含む）。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from . import tiles as T
from .rules import Rules

WIND_NAMES = {"east": "東", "south": "南", "west": "西", "north": "北"}
MELD_NAMES = {"pon": "ポン", "chi": "チー", "kan": "明カン", "ankan": "暗カン"}


class MeldIn(BaseModel):
    """鳴いた面子。kan は明カン（大明槓・加槓）、ankan は暗カン。"""

    type: Literal["pon", "chi", "kan", "ankan"]
    tiles: list[str]

    @field_validator("tiles")
    @classmethod
    def _tiles(cls, v: list[str]) -> list[str]:
        return [T.validate(t) for t in v]

    @model_validator(mode="after")
    def _shape(self) -> "MeldIn":
        base = [T.to_34(t) for t in self.tiles]
        name = MELD_NAMES[self.type]
        if self.type in ("pon",):
            if len(base) != 3 or len(set(base)) != 1:
                raise ValueError(f"{name}は同じ牌3枚です")
        elif self.type in ("kan", "ankan"):
            if len(base) != 4 or len(set(base)) != 1:
                raise ValueError(f"{name}は同じ牌4枚です")
        else:
            b = sorted(base)
            if len(b) != 3 or b[0] >= 27 or b[0] // 9 != b[2] // 9 or b != [b[0], b[0] + 1, b[0] + 2]:
                raise ValueError("チーは同じ種類の数牌が3つ連続した形です（例: 3萬4萬5萬）")
        return self

    @property
    def is_kan(self) -> bool:
        return self.type in ("kan", "ankan")

    @property
    def opened(self) -> bool:
        return self.type != "ankan"


class RoundSettings(BaseModel):
    players: int = Field(4, description="4=四人麻雀, 3=三人麻雀（さんま）")
    rules: Rules = Field(default_factory=Rules)
    nukidora: int = Field(0, ge=0, le=4, description="三麻：抜いた北の枚数（1枚につきドラ1）")
    seat_wind: str = Field("east", description="自風 east/south/west/north（east=親）")
    round_wind: str = Field("east", description="場風 east/south")
    melds: list[MeldIn] = Field(default_factory=list, description="自分の鳴き（ポン・チー・カン）")
    table_kans: int = Field(0, ge=0, le=4, description="この局で卓全体（自分を含む）がしたカンの回数")
    dora_indicators: list[str] = Field(default_factory=list, description="ドラ表示牌（1枚＋カンの回数）")
    ura_indicators: list[str] = Field(default_factory=list, description="裏ドラ表示牌（リーチしてアガったとき）")
    is_riichi: bool = False
    is_tsumo: bool = False
    is_ippatsu: bool = False
    # 特別な状況の役（チェックしたときだけ付く）
    is_double_riichi: bool = Field(False, description="ダブルリーチ（最初の打牌でリーチ）")
    is_rinshan: bool = Field(False, description="嶺上開花（カンしてもらった牌でツモ）")
    is_chankan: bool = Field(False, description="槍槓（他家が加カンした牌でロン）")
    is_last_tile: bool = Field(False, description="最後の牌でアガリ（ツモなら海底摸月・ロンなら河底撈魚）")
    is_first_draw: bool = Field(False, description="配牌直後の最初のツモでアガリ（親は天和・子は地和）")
    honba: int = Field(0, ge=0, le=20)
    kyoutaku: int = Field(0, ge=0, le=20, description="供託リーチ棒の本数")
    win_tile: str | None = Field(None, description="アガリ牌（省略時は手牌の最後の牌）")

    @field_validator("seat_wind", "round_wind")
    @classmethod
    def _wind(cls, v: str) -> str:
        if v not in WIND_NAMES:
            raise ValueError("風は east/south/west/north のいずれか")
        return v

    @field_validator("players")
    @classmethod
    def _players(cls, v: int) -> int:
        if v not in (3, 4):
            raise ValueError("人数は 4 か 3")
        return v

    @field_validator("dora_indicators", "ura_indicators")
    @classmethod
    def _dora(cls, v: list[str]) -> list[str]:
        if len(v) > 5:
            raise ValueError("ドラ表示牌は最大5枚（最初の1枚＋カン4回）です")
        return [T.validate(t) for t in v]

    @field_validator("win_tile")
    @classmethod
    def _win(cls, v: str | None) -> str | None:
        return T.validate(v) if v else v

    @model_validator(mode="after")
    def _check(self) -> "RoundSettings":
        r = self.rules
        if len(self.melds) > 4:
            raise ValueError("鳴きは4つまでです")
        own_kans = sum(1 for m in self.melds if m.is_kan)
        if own_kans > r.max_kans:
            raise ValueError(f"カンは1局で{r.max_kans}回までです")
        if self.table_kans < own_kans:
            self.table_kans = own_kans  # 自分のカンは卓のカン回数に含める
        if self.table_kans > r.max_kans:
            raise ValueError(f"カンは1局で卓全体{r.max_kans}回までです")
        max_ind = 1 + (self.table_kans if r.kan_dora else 0)
        if len(self.dora_indicators) > max_ind:
            raise ValueError(f"ドラ表示牌は{max_ind}枚までです（最初の1枚＋カン{self.table_kans}回）")
        max_ura = 1 + (self.table_kans if r.kan_ura else 0) if r.ura_dora else 0
        if len(self.ura_indicators) > max_ura:
            raise ValueError("裏ドラ表示牌が多すぎます" if max_ura else "このルールでは裏ドラはありません")

        if self.players == 3:
            if self.seat_wind == "north":
                raise ValueError("三人麻雀に北家はありません（自風は東・南・西）")
            used = self.dora_indicators + self.ura_indicators + [t for m in self.melds for t in m.tiles]
            bad = [t for t in used if t in T.SANMA_EXCLUDED]
            if bad:
                raise ValueError(f"三人麻雀では萬子の2〜8は使いません: {', '.join(bad)}")
            if not r.sanma_chi and any(m.type == "chi" for m in self.melds):
                raise ValueError("このルールの三人麻雀ではチーできません")
            if not r.sanma_nukidora and self.nukidora:
                raise ValueError("このルールでは北抜きはありません")
        elif self.nukidora:
            raise ValueError("抜きドラは三人麻雀だけのルールです")
        if not r.aka_dora:
            reds = [t for t in self.dora_indicators + [x for m in self.melds for x in m.tiles] if T.is_red(t)]
            if reds:
                raise ValueError("このルールでは赤ドラ（赤五）はありません")
        return self

    @property
    def is_sanma(self) -> bool:
        return self.players == 3

    @property
    def is_dealer(self) -> bool:
        return self.seat_wind == "east"

    @property
    def is_open(self) -> bool:
        return any(m.opened for m in self.melds)

    @property
    def meld_tiles(self) -> list[str]:
        return [t for m in self.melds for t in m.tiles]

    @property
    def tsumo_son(self) -> bool:
        return self.rules.sanma_tsumo_son
