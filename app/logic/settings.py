"""局・アガリ条件の設定。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from . import tiles as T

WIND_NAMES = {"east": "東", "south": "南", "west": "西", "north": "北"}


class RoundSettings(BaseModel):
    players: int = Field(4, description="4=四人麻雀, 3=三人麻雀（さんま）")
    nukidora: int = Field(0, ge=0, le=4, description="三麻：抜いた北の枚数（1枚につきドラ1）")
    tsumo_son: bool = Field(True, description="三麻：ツモ損あり（北家の分を払わない）。False なら北家分を2人で折半")
    seat_wind: str = Field("east", description="自風 east/south/west/north（east=親）")
    round_wind: str = Field("east", description="場風 east/south")
    dora_indicators: list[str] = Field(default_factory=list, description="ドラ表示牌")
    is_riichi: bool = False
    is_tsumo: bool = False
    is_ippatsu: bool = False
    honba: int = Field(0, ge=0, le=20)
    kyoutaku: int = Field(0, ge=0, le=20, description="供託リーチ棒の本数")
    win_tile: str | None = Field(None, description="アガリ牌（14枚のとき。省略時は最後の牌）")

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

    @model_validator(mode="after")
    def _sanma(self) -> "RoundSettings":
        if self.players == 3:
            if self.seat_wind == "north":
                raise ValueError("三人麻雀に北家はありません（自風は東・南・西）")
            bad = [t for t in self.dora_indicators if t in T.SANMA_EXCLUDED]
            if bad:
                raise ValueError(f"三人麻雀では萬子の2〜8は使いません: {', '.join(bad)}")
        elif self.nukidora:
            raise ValueError("抜きドラは三人麻雀だけのルールです")
        return self

    @property
    def is_sanma(self) -> bool:
        return self.players == 3

    @field_validator("dora_indicators")
    @classmethod
    def _dora(cls, v: list[str]) -> list[str]:
        if len(v) > 5:
            raise ValueError("ドラ表示牌は5枚まで")
        return [T.validate(t) for t in v]

    @field_validator("win_tile")
    @classmethod
    def _win(cls, v: str | None) -> str | None:
        return T.validate(v) if v else v

    @property
    def is_dealer(self) -> bool:
        return self.seat_wind == "east"
