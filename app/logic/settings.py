"""局・アガリ条件の設定。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from . import tiles as T

WIND_NAMES = {"east": "東", "south": "南", "west": "西", "north": "北"}


class RoundSettings(BaseModel):
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
