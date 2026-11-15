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
    split = score_hand(hand, S3(seat_wind="south", is_riichi=True, is_tsumo=True, rules={"sanma_tsumo_son": False}))
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


# ---------- 鳴き・カン・ドラ・ルール ----------

def test_pon_yakuhai_open_hand_score():
    s = RoundSettings(seat_wind="south", melds=[{"type": "pon", "tiles": ["7z", "7z", "7z"]}])
    r = score_hand(h("2m 3m 4m 5p 6p 7p 3s 4s 5s 9s 9s"), s, win_tile="9s")
    assert r.ok and "役牌 中" in [y["name"] for y in r.yaku]


def test_open_hand_without_yaku():
    s = RoundSettings(seat_wind="south", melds=[{"type": "chi", "tiles": ["1m", "2m", "3m"]}])
    r = score_hand(h("4p 5p 6p 7s 8s 9s 2p 3p 4p 9s 9s"), s)
    assert not r.ok


def test_kuitan_rule():
    hand = h("2m 3m 4m 5p 6p 7p 3s 4s 5s 6s 6s")
    melds = [{"type": "chi", "tiles": ["4p", "5p", "6p"]}]
    assert score_hand(hand, RoundSettings(seat_wind="south", melds=melds)).ok
    assert not score_hand(hand, RoundSettings(seat_wind="south", melds=melds, rules={"kuitan": False})).ok


def test_riichi_ignored_when_open():
    s = RoundSettings(seat_wind="south", is_riichi=True, melds=[{"type": "pon", "tiles": ["7z", "7z", "7z"]}])
    r = score_hand(h("2m 3m 4m 5p 6p 7p 3s 4s 5s 9s 9s"), s)
    assert r.ok and "立直" not in [y["name"] for y in r.yaku]


def test_kan_adds_dora_indicator_slot_and_limits():
    kan = {"type": "ankan", "tiles": ["1z"] * 4}
    # 自分のカン1回 → ドラ表示牌は2枚まで
    s = RoundSettings(seat_wind="east", melds=[kan], dora_indicators=["4z", "1p"])
    assert s.table_kans == 1
    with pytest.raises(ValueError):
        RoundSettings(melds=[kan], dora_indicators=["4z", "1p", "2p"])
    # 卓全体で最大4回、ドラ表示牌は最大5枚
    RoundSettings(table_kans=4, dora_indicators=["1p", "2p", "3p", "4p", "5p"])
    with pytest.raises(ValueError):
        RoundSettings(table_kans=5)
    with pytest.raises(ValueError):
        RoundSettings(melds=[{"type": "kan", "tiles": [t] * 4} for t in ("1p", "2p", "3p", "4p")] + [{"type": "kan", "tiles": ["5s"] * 4}])
    # カンドラなしのルールなら表示牌は1枚だけ
    with pytest.raises(ValueError):
        RoundSettings(table_kans=1, dora_indicators=["1p", "2p"], rules={"kan_dora": False})


def test_ankan_score_with_kan_dora():
    kan = {"type": "ankan", "tiles": ["1z"] * 4}
    s = RoundSettings(seat_wind="east", round_wind="east", is_tsumo=True, melds=[kan], dora_indicators=["4z"])
    r = score_hand(h("1m 2m 3m 4p 5p 6p 7s 8s 9s 2s 2s"), s, win_tile="2s")
    assert r.ok
    names = {y["name"]: y["han"] for y in r.yaku}
    assert names["ドラ"] == 4  # 北が表示牌 → 東がドラ、暗カンで4枚
    assert "門前清自摸和" in names  # 暗カンは門前のまま


def test_ura_dora_only_with_riichi():
    hand = h("2m 3m 4m 5p 6p 7p 3s 4s 5s 6s 7s 8s 9p 9p")
    s = RoundSettings(seat_wind="south", is_riichi=True, dora_indicators=["1z"], ura_indicators=["8p"])
    assert {y["name"]: y["han"] for y in score_hand(hand, s).yaku}["裏ドラ"] == 2
    with pytest.raises(ValueError):
        RoundSettings(seat_wind="south", is_riichi=True, ura_indicators=["8p"], rules={"ura_dora": False})


def test_aka_dora_rule_off():
    hand = h("2m 3m 4m 0p 6p 7p 3s 4s 5s 6s 7s 8s 9p 9p")
    r = score_hand(hand, RoundSettings(seat_wind="south", is_riichi=True, rules={"aka_dora": False}))
    assert not r.ok


def test_honba_values():
    hand = h("2m 3m 4m 3p 4p 5p 6p 7p 8p 2s 2s 6s 7s 8s")
    r4 = score_hand(hand, RoundSettings(seat_wind="south", honba=2))
    assert r4.total == 2000 + 600
    hand3 = h("1p 2p 3p 3p 4p 5p 6p 7p 8p 2s 2s 6s 7s 8s")
    base3 = score_hand(hand3, RoundSettings(players=3, seat_wind="south")).total
    r3 = score_hand(hand3, RoundSettings(players=3, seat_wind="south", honba=2))
    assert r3.total == base3 + 400


def test_analyze_with_melds_counts_and_waits():
    s = RoundSettings(seat_wind="south", melds=[{"type": "pon", "tiles": ["7z", "7z", "7z"]}])
    a = analyze(h("2m 3m 4m 5p 6p 7p 3s 4s 5s 9s"), s)
    assert a["shanten"] == 0
    assert a["waits"][0]["tile"] == "9s" and a["waits"][0]["ok"]
    a2 = analyze(h("2m 3m 4m 5p 6p 7p 3s 4s 5s 9s 1z"), s)
    assert a2["discards"][0]["discard"] in ("1z", "9s")
    names = [x["name"] for x in a2["hints"]]
    assert "立直" not in names and "七対子（チートイツ）" not in names


def test_sanma_chi_not_allowed_by_default():
    with pytest.raises(ValueError):
        RoundSettings(players=3, melds=[{"type": "chi", "tiles": ["1p", "2p", "3p"]}])
    RoundSettings(players=3, melds=[{"type": "chi", "tiles": ["1p", "2p", "3p"]}], rules={"sanma_chi": True})


def test_bad_meld_shapes():
    for m in ({"type": "pon", "tiles": ["1m", "1m", "2m"]}, {"type": "chi", "tiles": ["8p", "9p", "1s"]},
              {"type": "chi", "tiles": ["1z", "2z", "3z"]}, {"type": "kan", "tiles": ["1m"] * 3}):
        with pytest.raises(ValueError):
            RoundSettings(melds=[m])


def test_score_both_ron_and_tsumo_payments():
    from app.logic.scorer import score_both

    hand = "2m 3m 4m 0p 6p 7p 3s 4s 5s 6s 7s 8s 5p 5p".split()
    child = score_both(hand, RoundSettings(seat_wind="south"))
    ron, tsumo = child["ron"], child["tsumo"]
    assert ron["ok"] and tsumo["ok"]
    assert ron["pays"] == [{"who": "放銃した人（ロンされた人）", "points": ron["total"]}]
    who = [p["who"] for p in tsumo["pays"]]
    assert who == ["親", "子 2人がそれぞれ"]
    assert tsumo["total"] == tsumo["pays"][0]["points"] + 2 * tsumo["pays"][1]["points"]
    dealer = score_both(hand, RoundSettings(seat_wind="east"))["tsumo"]
    assert dealer["pays"][0]["who"] == "子 3人がそれぞれ"
    assert dealer["payment"].endswith("オール")


def test_fu_breakdown():
    # 1索の暗刻（么九牌の暗刻 8符）+ 嵌張待ち 2符 + 門前ロン → 20+10+8+2 = 40符
    hand = "1s 1s 1s 2m 3m 4m 6p 7p 8p 5s 5s 4p 6p 5p".split()
    r = score_hand(hand, RoundSettings(seat_wind="south", is_riichi=True), win_tile="5p", tsumo=False)
    names = {d["name"]: d["fu"] for d in r.fu_details}
    assert names["副底（アガリの基本）"] == 20 and names["門前ロン（鳴かずにロン）"] == 10
    assert names["暗刻（1・9・字牌）"] == 8 and names["嵌張（カンチャン）待ち"] == 2
    assert r.fu_raw == 40 and r.fu == 40
    chiitoi = "1m 1m 3p 3p 5s 5s 7s 7s 2z 2z 6z 6z 9p 9p".split()
    r = score_hand(chiitoi, RoundSettings(seat_wind="south", is_riichi=True))
    assert r.fu == 25 and r.fu_details == [{"name": "七対子（固定）", "fu": 25}]


def test_special_situation_yaku():
    hand = "2m 3m 4m 0p 6p 7p 3s 4s 5s 6s 7s 8s 5p 5p".split()
    s = RoundSettings(seat_wind="south", is_rinshan=True, is_last_tile=True)
    tsumo = score_hand(hand, s, tsumo=True)
    assert "嶺上開花" in [y["name"] for y in tsumo.yaku]
    assert not score_hand(hand, s, tsumo=False).ok  # 嶺上開花はロンでは無い
    ron = score_hand(hand, RoundSettings(seat_wind="south", is_last_tile=True), tsumo=False)
    assert "河底撈魚" in {y["name"] for y in ron.yaku}
    ron = score_hand(hand, RoundSettings(seat_wind="south", is_chankan=True), tsumo=False)
    assert "槍槓" in {y["name"] for y in ron.yaku}
    both = score_hand(hand, RoundSettings(seat_wind="south", is_last_tile=True, is_chankan=True), tsumo=False)
    assert not both.ok and "同時" in both.error
    first = score_hand(hand, RoundSettings(seat_wind="east", is_first_draw=True), tsumo=True)
    assert any(y["name"] == "天和" for y in first.yaku)
