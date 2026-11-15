import pytest

from app.logic import tiles as T
from app.logic.analyzer import analyze
from app.logic.scorer import score_hand
from app.logic.settings import RoundSettings


def h(s: str) -> list[str]:
    return s.split()


def test_tile_conversion_roundtrip():
    for i in range(34):
        assert T.to_34(T.from_34(i)) == i
    assert T.to_34("0p") == T.to_34("5p")
    assert T.display_name("0s") == "赤五索"
    assert T.display_name("7z") == "中"


def test_red_five_uses_aka_id():
    arr = T.to_136_array(["5m", "0m", "5m"])
    assert 16 in arr and len(set(arr)) == 3


def test_five_of_a_kind_rejected():
    with pytest.raises(T.TileError):
        analyze(h("1m 1m 1m 1m 1m"), RoundSettings())


def test_tanyao_ron_child():
    r = score_hand(h("2m 3m 4m 3p 4p 5p 6p 7p 8p 2s 2s 6s 7s 8s"), RoundSettings(seat_wind="south"))
    assert r.ok
    names = [y["name"] for y in r.yaku]
    assert "断么九" in names and "平和" in names
    assert r.han == 2 and r.fu == 30
    assert r.total == 2000


def test_dealer_tsumo_riichi_dora_aka():
    s = RoundSettings(seat_wind="east", is_riichi=True, is_tsumo=True, dora_indicators=["1m"])
    r = score_hand(h("2m 2m 4m 4m 4m 3p 3p 3p 0p 6p 7p 4s 4s 4s"), s)
    assert r.ok
    names = [y["name"] for y in r.yaku]
    assert {"立直", "門前清自摸和", "断么九", "三暗刻", "ドラ", "赤ドラ"} <= set(names)
    assert r.level == "倍満"
    assert r.payment == "ツモ 8000点オール"


def test_child_tsumo_payment_text():
    s = RoundSettings(seat_wind="south", is_tsumo=True, is_riichi=True)
    r = score_hand(h("1m 2m 3m 4p 5p 6p 7s 8s 9s 2p 3p 4p 9m 9m"), s, win_tile="4p")
    assert r.ok
    assert r.payment.startswith("ツモ 子") and "親" in r.payment


def test_no_yaku():
    r = score_hand(h("1m 2m 3m 5p 6p 7p 2s 3s 4s 9m 9m 9m 1z 1z"), RoundSettings(seat_wind="south"))
    assert not r.ok and "役" in r.error


def test_kokushi_yakuman():
    r = score_hand(h("1m 9m 1p 9p 1s 9s 1z 2z 3z 4z 5z 6z 7z 1m"), RoundSettings())
    assert r.ok and r.yaku[0]["yakuman"]


def test_analyze_tenpai_waits_and_scores():
    a = analyze(h("1m 2m 3m 5p 6p 7p 2s 3s 4s 7z 7z 9m 9m"), RoundSettings())
    assert a["shanten"] == 0
    waits = {w["tile"]: w for w in a["waits"]}
    assert set(waits) == {"9m", "7z"}
    assert waits["7z"]["ok"] and "役牌 中" in waits["7z"]["yaku"]
    assert waits["9m"]["riichi_needed"] and "立直" in waits["9m"]["yaku"]  # 役なし→リーチで和了


def test_analyze_discard_recommendation():
    # 東（オタ風の孤立牌）を切るのが最善
    a = analyze(h("2m 3m 4m 0p 6p 7p 3s 4s 6s 7s 8s 5z 5z 3z"), RoundSettings(seat_wind="south"))
    assert a["discards"][0]["discard"] == "3z"
    assert a["discards"][0]["shanten"] == 0
    assert "waits" in a["discards"][0]


def test_analyze_complete_hand_gives_score():
    a = analyze(h("2m 3m 4m 3p 4p 5p 6p 7p 8p 2s 2s 6s 7s 8s"), RoundSettings())
    assert a["shanten"] == -1
    assert a["score"]["ok"]


def test_hints_tanyao_and_yakuhai():
    a = analyze(h("2m 3m 4m 5p 6p 7p 3s 4s 6s 7s 5z 5z 1m"), RoundSettings(seat_wind="south"))
    names = {x["name"]: x for x in a["hints"]}
    assert names["断么九（タンヤオ）"]["distance"] == 3
    assert names["役牌 白"]["distance"] == 1


def test_wrong_tile_count_message():
    a = analyze(h("1m 2m 3m 4m 5m 6m"), RoundSettings())
    assert "13枚か14枚" in a["message"]


# ---------- 三人麻雀（さんま） ----------

def S3(**kw) -> RoundSettings:
    return RoundSettings(players=3, **kw)


def test_sanma_dora_indicator_wraps_1m_to_9m():
    assert T.sanma_dora_from_indicator("1m") == "9m"
    assert T.sanma_dora_from_indicator("9m") == "1m"
    assert T.sanma_dora_from_indicator("4z") == "1z"
    assert T.sanma_dora_from_indicator("7z") == "5z"
    hand = h("9m 9m 9m 1p 2p 3p 4p 5p 6p 7s 8s 9s 2s 2s")
    r = score_hand(hand, S3(seat_wind="south", is_riichi=True, dora_indicators=["1m"]))
    assert r.ok
    dora = next(y for y in r.yaku if y["name"] == "ドラ")
    assert dora["han"] == 3  # 九萬3枚


def test_sanma_rejects_2m_to_8m():
    with pytest.raises(T.TileError):
        analyze(h("1m 2m 3m 1p 2p 3p 4p 5p 6p 7s 8s 9s 2s"), S3())
    with pytest.raises(ValueError):
        S3(seat_wind="north")


def test_sanma_effective_tiles_exclude_manzu_middle():
    a = analyze(h("1m 9m 1p 2p 3p 4p 5p 6p 7s 8s 9s 2s 2s"), S3())
    tiles = {e["tile"] for e in a["effective"]}
    assert not tiles & T.SANMA_EXCLUDED


def test_sanma_nukidora_adds_han():
    hand = h("1p 2p 3p 4p 5p 6p 7p 8p 9p 2s 3s 4s 5s 5s")
    base = score_hand(hand, S3(seat_wind="south", is_riichi=True))
    nuki = score_hand(hand, S3(seat_wind="south", is_riichi=True, nukidora=2))
    assert nuki.han == base.han + 2
    assert any(y["name"].startswith("抜きドラ") for y in nuki.yaku)
    assert nuki.total > base.total


def test_sanma_nukidora_alone_is_not_yaku():
    r = score_hand(h("1p 2p 3p 4p 5p 6p 7s 8s 9s 9m 9m 9m 1z 1z"), S3(seat_wind="south", nukidora=1), win_tile="1z")
    assert not r.ok


def test_sanma_tsumo_son_vs_split():
    hand = h("1p 2p 3p 4p 5p 6p 7p 8p 9p 2s 3s 4s 5s 5s")
    # 子のツモ：ツモ損ありは2人分だけ、折半なら北家分も2人で払う
    son = score_hand(hand, S3(seat_wind="south", is_riichi=True, is_tsumo=True))
    split = score_hand(hand, S3(seat_wind="south", is_riichi=True, is_tsumo=True, tsumo_son=False))
    four = score_hand(hand, RoundSettings(seat_wind="south", is_riichi=True, is_tsumo=True))
    assert son.total < four.total
    assert split.total >= four.total
    assert "ツモ損" in son.payment and "折半" in split.payment
    # 親のツモ
    d = score_hand(hand, S3(seat_wind="east", is_riichi=True, is_tsumo=True))
    d4 = score_hand(hand, RoundSettings(seat_wind="east", is_riichi=True, is_tsumo=True))
    assert d.total * 3 == d4.total * 2


def test_sanma_hints():
    a = analyze(h("1p 2p 3p 4p 5p 6p 7p 8p 2s 3s 4z 4z 9m"), S3(seat_wind="south"))
    names = [x["name"] for x in a["hints"]]
    assert "抜きドラ（北）" in names
    assert "三色同順（サンショク）" not in names
