import base64

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.logic.league import Forbidden, LeagueError, LeagueStore, block_sizes, formats
from app.main import app


@pytest.fixture
def store(tmp_path):
    return LeagueStore(tmp_path)


def _players(store, n):
    return [store.add_player(f"P{i}", emoji="🀄")["id"] for i in range(n)]


def test_formats_12_players_has_both():
    f = {x["blocks"]: x for x in formats(12)}
    assert set(f) == {3, 4}
    assert f[4]["sizes"] == [3, 3, 3, 3] and "決勝は四麻" in f[4]["label"]
    assert f[3]["sizes"] == [4, 4, 4] and "決勝は三麻" in f[3]["label"]


def test_formats_other_counts():
    assert [x["blocks"] for x in formats(9)] == [3, 4]  # 二麻の卓が少ない方がおすすめ
    assert [x["blocks"] for x in formats(16)] == [4]
    assert block_sizes(13, 4) == [4, 3, 3, 3]
    assert formats(1) == [] and formats(17) == []
    for n in (2, 3, 4):
        assert formats(n) == [{"blocks": 1, "sizes": [n], "final_players": n, "label": formats(n)[0]["label"]}]
    f5 = formats(5)
    assert [x["blocks"] for x in f5] == [2] and f5[0]["sizes"] == [3, 2] and "決勝は二麻" in f5[0]["label"]
    assert [x["blocks"] for x in formats(8)] == [2, 3, 4]  # 四麻2卓 → 三麻2卓＋二麻1卓 → 二麻4卓
    assert all(formats(n) for n in range(2, 17))


def test_player_requires_name_and_avatar(store):
    with pytest.raises(LeagueError):
        store.add_player("", emoji="🀄")
    with pytest.raises(LeagueError):
        store.add_player("たろう")  # アバターなし
    store.add_player("たろう", emoji="🐯")
    with pytest.raises(LeagueError):
        store.add_player(" たろう ", emoji="🐼")  # 同じ名前


def test_player_photo_is_cropped(store):
    img = np.full((300, 200, 3), 128, np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    p = store.add_player("写真さん", photo=buf.tobytes())
    path = store.avatar_path(p["photo"])
    assert path is not None
    assert cv2.imread(str(path)).shape[:2] == (160, 160)
    assert store.avatar_path("../league.json") is None


def test_ron_tsumo_riichi_and_stats(store):
    a, b, c, d = _players(store, 4)
    g = store.add_game([a, b, c, d], shuffle=False)
    # 子(b)が親(a)から 3900 ロン。a はリーチしていた
    store.add_hand(g["id"], {"kind": "ron", "winner": b, "loser": a, "points": 3900, "riichi": [a]})
    assert g["points"] == {a: 20100, b: 29900, c: 25000, d: 25000}
    assert g["dealer"] == 1  # 子がアガったので親が b へ
    # 親(b)のツモ 2000オール
    store.add_hand(g["id"], {"kind": "tsumo", "winner": b, "pay_child": 2000})
    assert g["points"][b] == 35900 and g["dealer"] == 1
    # 子(d)のツモ 子1000・親2000
    store.add_hand(g["id"], {"kind": "tsumo", "winner": d, "pay_child": 1000, "pay_dealer": 2000})
    assert g["points"] == {a: 17100, b: 33900, c: 22000, d: 27000}
    assert sum(g["points"].values()) == 100000
    s = store.stats()
    assert s[b]["plus"] == 10900 and s[b]["minus"] == -2000 and s[b]["net"] == 8900
    assert s[a]["minus"] == -7900 and s[a]["deal_ins"] == 1
    # 取り消し
    store.undo_hand(g["id"])
    assert g["points"][d] == 23000 and g["dealer"] == 1
    store.finish_game(g["id"])
    assert g["ranks"][0] == b
    assert store.stats()[b]["tops"] == 1


def test_sanma_tsumo_and_other(store):
    a, b, c = _players(store, 3)
    g = store.add_game([a, b, c], shuffle=False)
    assert g["start"] == 35000
    store.add_hand(g["id"], {"kind": "other", "deltas": {a: 1000, b: 1000, c: -2000}, "note": "流局"})
    assert g["points"] == {a: 36000, b: 36000, c: 33000}
    with pytest.raises(LeagueError):
        store.add_hand(g["id"], {"kind": "ron", "winner": a, "loser": a, "points": 1000})


def test_tie_breaks_by_seat(store):
    a, b, c = _players(store, 3)
    g = store.add_game([a, b, c], shuffle=False)
    store.add_hand(g["id"], {"kind": "other", "deltas": {c: 1000, a: 1000, b: -2000}})
    store.finish_game(g["id"])
    assert g["ranks"] == [a, c, b]


def _finish_with_winner(store, gid, winner):
    g = store.data["games"][gid]
    loser = next(p for p in g["players"] if p != winner)
    store.add_hand(gid, {"kind": "ron", "winner": winner, "loser": loser, "points": 8000})
    store.finish_game(gid)


def test_tournament_sanma_blocks_to_yonma_final(store):
    ids = _players(store, 12)
    t, key = store.add_tournament("はせけん麻雀大会", ids, 4)
    assert [len(b) for b in t["blocks"]] == [3, 3, 3, 3]
    assert sorted(sum(t["blocks"], [])) == sorted(ids)
    with pytest.raises(Forbidden):
        store.start_tournament(t["id"], "wrong")
    store.redraw(t["id"], key)
    store.start_tournament(t["id"], key)
    assert t["status"] == "blocks" and len(t["block_games"]) == 4
    with pytest.raises(LeagueError):
        store.start_final(t["id"], key)  # まだブロックが終わっていない
    winners = []
    for gid, members in zip(t["block_games"], t["blocks"]):
        _finish_with_winner(store, gid, members[1])
        winners.append(members[1])
    store.start_final(t["id"], key)
    final = store.data["games"][t["final_game"]]
    assert sorted(final["players"]) == sorted(winners) and final["start"] == 25000  # 決勝は四麻
    with pytest.raises(LeagueError):
        store.reopen_game(t["block_games"][0])
    _finish_with_winner(store, final["id"], winners[2])
    assert t["status"] == "done" and t["king"] == winners[2]
    assert store.stats()[winners[2]]["kings"] == 1
    store.reopen_game(final["id"])
    assert t["king"] is None and t["status"] == "final"


def test_tournament_yonma_blocks_to_sanma_final(store):
    ids = _players(store, 12)
    t, key = store.add_tournament("", ids, 3)
    assert t["name"] == "はせけん麻雀大会"
    store.start_tournament(t["id"], key)
    for gid, members in zip(t["block_games"], t["blocks"]):
        _finish_with_winner(store, gid, members[0])
    store.start_final(t["id"], key)
    final = store.data["games"][t["final_game"]]
    assert len(final["players"]) == 3 and final["start"] == 35000


def test_tournament_bad_headcount(store):
    with pytest.raises(LeagueError):
        store.add_tournament("x", _players(store, 1), 1)
    with pytest.raises(LeagueError):
        store.add_tournament("x", _players(store, 6), 4)  # 6人を4ブロックには分けられない


def test_store_persists(tmp_path):
    s1 = LeagueStore(tmp_path)
    a, b, c = _players(s1, 3)
    g = s1.add_game([a, b, c])
    s1.add_hand(g["id"], {"kind": "ron", "winner": a, "loser": b, "points": 1000})
    s2 = LeagueStore(tmp_path)
    assert s2.stats()[a]["plus"] == 1000


def test_league_api_flow():
    client = TestClient(app)
    assert client.get("/taikai").status_code == 200
    img = np.full((200, 200, 3), 200, np.uint8)
    photo = "data:image/jpeg;base64," + base64.b64encode(cv2.imencode(".jpg", img)[1].tobytes()).decode()
    r = client.post("/api/league/players", json={"name": "API写真", "photo": photo})
    assert r.status_code == 200, r.text
    assert client.post("/api/league/players", json={"name": "アバターなし"}).status_code == 400
    ids = [r.json()["id"]] + [client.post("/api/league/players", json={"name": f"API{i}", "emoji": "🐼"}).json()["id"] for i in range(11)]
    state = client.get("/api/league").json()
    me = next(p for p in state["players"] if p["id"] == ids[0])
    assert client.get(me["avatar"]).status_code == 200

    r = client.post("/api/league/tournaments", json={"players": ids, "blocks": 4, "owner_player": ids[0]})
    assert r.status_code == 200
    tid, key = r.json()["tournament"]["id"], r.json()["owner_key"]
    assert "owner" not in r.json()["tournament"]
    assert client.post(f"/api/league/tournaments/{tid}/start").status_code == 403
    assert client.post(f"/api/league/tournaments/{tid}/start", headers={"X-Owner-Key": key}).status_code == 200
    t = next(x for x in client.get("/api/league").json()["tournaments"] if x["id"] == tid)
    gid = t["block_games"][0]
    a, b = t["blocks"][0][:2]
    r = client.post(f"/api/league/games/{gid}/hands", json={"kind": "ron", "winner": a, "loser": b, "points": 12000})
    assert r.status_code == 200 and r.json()["points"][a] == 47000
    assert client.post(f"/api/league/games/{gid}/finish").json()["ranks"][0] == a
    stats = {p["id"]: p["stats"] for p in client.get("/api/league").json()["players"]}
    assert stats[a]["plus"] >= 12000 and stats[b]["minus"] <= -12000


def test_free_game_seats_are_drawn(store):
    ids = _players(store, 4)
    seen = {tuple(store.add_game(ids)["players"]) for _ in range(30)}
    assert all(sorted(s) == sorted(ids) for s in seen) and len(seen) > 1


def test_owner_edits_tournament(store):
    ids = _players(store, 13)
    t, key = store.add_tournament("大会", ids[:12], 4)
    # 開始前：名前・手動の入れ替え・参加者の変更
    swapped = [list(b) for b in t["blocks"]]
    swapped[0][0], swapped[1][0] = swapped[1][0], swapped[0][0]
    store.edit_tournament(t["id"], key, name="第1回", blocks=swapped)
    assert t["name"] == "第1回" and t["blocks"] == swapped
    with pytest.raises(Forbidden):
        store.edit_tournament(t["id"], "x", name="のっとり")
    with pytest.raises(LeagueError):
        store.edit_tournament(t["id"], key, blocks=[swapped[0] + swapped[1][:2], swapped[2], swapped[3]])  # 5人の卓
    store.change_entries(t["id"], key, ids[:12], 3)
    assert [len(b) for b in t["blocks"]] == [4, 4, 4]
    store.start_tournament(t["id"], key)
    # 開始後：記録のないブロックだけ差し替えできる（13人目と交代）
    g0 = store.data["games"][t["block_games"][0]]
    new = [list(b) for b in t["blocks"]]
    out = new[1][2]
    new[1][2] = ids[12]
    store.edit_tournament(t["id"], key, blocks=new)
    g1 = store.data["games"][t["block_games"][1]]
    assert ids[12] in g1["players"] and out not in g1["players"] and g1["points"][ids[12]] == 25000
    assert ids[12] in t["players"] and out not in t["players"]
    store.add_hand(g0["id"], {"kind": "ron", "winner": g0["players"][0], "loser": g0["players"][1], "points": 1000})
    locked = [list(b) for b in t["blocks"]]
    locked[0][0], locked[2][0] = locked[2][0], locked[0][0]
    with pytest.raises(LeagueError):
        store.edit_tournament(t["id"], key, blocks=locked)
    with pytest.raises(LeagueError):
        store.change_entries(t["id"], key, ids[:12], 3)
    store.edit_tournament(t["id"], key, name="第2回")
    assert g0["title"].startswith("第2回")


def test_start_points_and_owner_flag(store):
    ids = _players(store, 12)
    with pytest.raises(LeagueError):
        store.add_tournament("x", ids, 4, start_points={"4": 25050})
    t, key = store.add_tournament("x", ids, 4, start_points={"4": 30000, "3": 40000}, owner_player=ids[0])
    assert t["owner_player"] == ids[0] and t["start_points"] == {"4": 30000, "3": 40000, "2": 25000}
    store.edit_tournament(t["id"], key, start_points={"4": 30000, "3": 50000}, owner_player=ids[1])
    assert t["owner_player"] == ids[1]
    store.start_tournament(t["id"], key)
    g0, g1 = (store.data["games"][gid] for gid in t["block_games"][:2])
    assert g0["start"] == 50000 and set(g0["points"].values()) == {50000}  # 三麻の卓
    # 開始後でも、まだ記録のない卓には反映される
    store.add_hand(g1["id"], {"kind": "ron", "winner": g1["players"][0], "loser": g1["players"][1], "points": 1000})
    store.edit_tournament(t["id"], key, start_points={"4": 25000, "3": 35000})
    assert g0["start"] == 35000 and g1["start"] == 50000
    # 卓ごとの変更：大会の卓はオーナーだけ、記録後は不可
    with pytest.raises(Forbidden):
        store.set_game_start(g0["id"], 40000)
    store.set_game_start(g0["id"], 40000, key)
    assert g0["points"][g0["players"][0]] == 40000
    with pytest.raises(LeagueError):
        store.set_game_start(g1["id"], 40000, key)
    # 大会以外の対局
    g = store.add_game(ids[:4], start=30000)
    assert g["start"] == 30000
    store.set_game_start(g["id"], 27000)
    assert set(g["points"].values()) == {27000}


def test_fix_wrong_ron_target(store):
    a, b, c, d = _players(store, 4)
    g = store.add_game([a, b, c, d], shuffle=False)
    store.add_hand(g["id"], {"kind": "ron", "winner": b, "loser": c, "points": 3900, "riichi": [d]})
    store.add_hand(g["id"], {"kind": "tsumo", "winner": c, "pay_child": 1000, "pay_dealer": 2000})  # 親は b
    assert g["hands"][0]["points"] == 3900 and g["hands"][0]["riichi"] == [d]
    # 1局目のロンの相手は c ではなく a だった
    store.edit_hand(g["id"], 0, {"kind": "ron", "winner": b, "loser": a, "points": 3900, "riichi": [d]})
    assert g["points"] == {a: 20100, b: 27900, c: 29000, d: 23000}
    assert sum(g["points"].values()) == 100000 and g["hands"][0]["edited"]
    s = store.stats()
    assert s[a]["deal_ins"] == 1 and s[c]["deal_ins"] == 0
    # 最後の局を直すと次の親も決め直す（子 c のツモ → 親流れ。親 b のツモに直すと連荘）
    assert g["dealer"] == 2
    store.edit_hand(g["id"], 1, {"kind": "tsumo", "winner": b, "pay_child": 2000})
    assert g["dealer"] == 1 and g["points"] == {a: 19100, b: 35900, c: 23000, d: 22000}
    # 途中の局を消す
    store.delete_hand(g["id"], 0)
    assert len(g["hands"]) == 1 and g["points"] == {a: 23000, b: 31000, c: 23000, d: 23000}
    with pytest.raises(LeagueError):
        store.edit_hand(g["id"], 5, {"kind": "other", "deltas": {a: 1000}})
    store.finish_game(g["id"])
    with pytest.raises(LeagueError):
        store.edit_hand(g["id"], 0, {"kind": "other", "deltas": {a: 1000, b: -1000}})


def test_league_api_edit_hand():
    client = TestClient(app)
    ids = [client.post("/api/league/players", json={"name": f"修正{i}", "emoji": "🐸"}).json()["id"] for i in range(3)]
    g = client.post("/api/league/games", json={"players": ids}).json()
    a, b, c = g["players"]
    client.post(f"/api/league/games/{g['id']}/hands", json={"kind": "ron", "winner": a, "loser": b, "points": 8000})
    r = client.put(f"/api/league/games/{g['id']}/hands/0", json={"kind": "ron", "winner": a, "loser": c, "points": 8000})
    assert r.status_code == 200 and r.json()["points"][b] == 35000 and r.json()["points"][c] == 27000
    assert client.delete(f"/api/league/games/{g['id']}/hands/last").status_code == 200
    assert client.delete(f"/api/league/games/{g['id']}/hands/0").status_code == 400


def test_two_player_tournament_goes_straight_to_final(store):
    a, b = _players(store, 2)
    t, key = store.add_tournament("二人大会", [a, b], 1)
    store.start_tournament(t["id"], key)
    assert t["status"] == "final" and not t["block_games"]
    g = store.data["games"][t["final_game"]]
    assert g["start"] == 25000 and len(g["players"]) == 2
    p0, p1 = g["players"]
    # 二麻は役満のみ：子の 8,000 点ロンはアガれない
    with pytest.raises(LeagueError, match="役満"):
        store.add_hand(g["id"], {"kind": "ron", "winner": p1, "loser": p0, "points": 8000})
    with pytest.raises(LeagueError, match="48,000"):
        store.add_hand(g["id"], {"kind": "ron", "winner": p0, "loser": p1, "points": 32000})  # 親は 48,000
    store.add_hand(g["id"], {"kind": "tsumo", "winner": p1, "pay_child": 32000})  # 二麻のツモは相手が全部払う
    assert g["points"] == {p0: -7000, p1: 57000}
    store.finish_game(g["id"])
    assert t["king"] == p1 and t["status"] == "done"


def test_five_players_two_blocks_nima_final(store):
    ids = _players(store, 5)
    t, key = store.add_tournament("五人", ids, 2)
    assert sorted(len(x) for x in t["blocks"]) == [2, 3]
    store.start_tournament(t["id"], key)
    for gid in t["block_games"]:
        g = store.data["games"][gid]
        w, l = g["players"][1], g["players"][0]  # 子が親からロン
        store.add_hand(gid, {"kind": "ron", "winner": w, "loser": l, "points": 32000})
        store.finish_game(gid)
    store.start_final(t["id"], key)
    final = store.data["games"][t["final_game"]]
    assert len(final["players"]) == 2 and final["start"] == 25000


def test_league_api_nima_free_game():
    client = TestClient(app)
    ids = [client.post("/api/league/players", json={"name": f"二麻{i}", "emoji": "🐼"}).json()["id"] for i in range(2)]
    r = client.post("/api/league/games", json={"players": ids})
    assert r.status_code == 200 and len(r.json()["players"]) == 2
    assert client.post("/api/league/games", json={"players": ids[:1]}).status_code == 422


def test_end_tournament_keeps_scores(store):
    ids = _players(store, 5)
    t, key = store.add_tournament("途中終了", ids, 2)
    with pytest.raises(LeagueError):
        store.end_tournament(t["id"], key)  # 開始前は「やめる」で削除
    store.start_tournament(t["id"], key)
    g0 = store.data["games"][t["block_games"][0]]
    w, l = g0["players"][1], g0["players"][0]
    store.add_hand(g0["id"], {"kind": "ron", "winner": w, "loser": l, "points": 32000 if len(g0["players"]) == 2 else 8000})
    with pytest.raises(Forbidden):
        store.end_tournament(t["id"], "wrong")
    store.end_tournament(t["id"], key)
    assert t["status"] == "done" and t["ended_early"] and t["king"] is None
    assert all(store.data["games"][gid]["finished"] for gid in t["block_games"])
    st = store.stats()
    assert st[w]["plus"] > 0 and st[w]["finished"] == 0  # 点数は残る・打ち切りの卓は順位なし
    assert store.snapshot()["tournaments"][0]["winners"] == [None, None]
    with pytest.raises(LeagueError):
        store.reopen_game(g0["id"])
    # 終わった後は新しい大会を作れる
    store.add_tournament("次", ids[:4], 1)


def test_reset_needs_owner_of_every_active_tournament(store, tmp_path):
    ids = _players(store, 6)
    t1, k1 = store.add_tournament("A", ids[:3], 1, owner_player=ids[0])
    t2, k2 = store.add_tournament("A", ids[3:], 1, owner_player=ids[3])
    assert t2["name"] == "A（2）"  # 同じ名前は（2）を付けて見分ける
    with pytest.raises(Forbidden) as e:
        store.reset({t1["id"]: k1})  # もう1つの大会のオーナー権限がない
    assert "A（2）" in str(e.value)
    with pytest.raises(Forbidden):
        store.reset({t1["id"]: k1, t2["id"]: "wrong"})
    r = store.reset({t1["id"]: k1, t2["id"]: k2}, keep_players=True)
    assert (tmp_path / r["backup"]).exists() and r["players"] == 6
    assert not store.data["games"] and not store.data["tournaments"] and len(store.data["players"]) == 6
    store.reset(None)  # 大会がなければ誰でも
    assert not store.data["players"]
    assert LeagueStore(tmp_path).data["players"] == {}


def test_reset_after_all_done_needs_any_owner(store):
    ids = _players(store, 4)
    t1, k1 = store.add_tournament("A", ids[:2], 1)
    t2, k2 = store.add_tournament("B", ids[2:], 1)
    for t, k in ((t1, k1), (t2, k2)):
        store.start_tournament(t["id"], k)
        store.end_tournament(t["id"], k)
    assert store.reset_blockers({}) and not store.reset_blockers({t2["id"]: k2})
    store.reset({t2["id"]: k2})


def test_multiple_tournaments_run_at_once(store):
    ids = _players(store, 8)
    t1, k1 = store.add_tournament("春", ids[:4], 1, owner_player=ids[0])
    t2, k2 = store.add_tournament("春", ids[4:], 1, owner_player=ids[5])
    store.start_tournament(t1["id"], k1)
    store.start_tournament(t2["id"], k2)
    with pytest.raises(Forbidden):
        store.start_final(t2["id"], k1)  # ほかの大会のオーナーは操作できない
    with pytest.raises(LeagueError):
        store.edit_tournament(t1["id"], k1, owner_player="")  # オーナーは外せない
    store.edit_tournament(t1["id"], k1, name="春（2）", owner_player=ids[1])
    assert t1["name"] == "春（2）（2）" and t1["owner_player"] == ids[1]  # 名前はかぶらない
    assert [t["status"] for t in store.snapshot()["tournaments"]] == ["final", "final"]  # 4人以下は決勝の卓だけ


def test_reset_api_needs_confirm_word(tmp_path, monkeypatch):
    import app.league_api as api
    monkeypatch.setattr(api, "store", LeagueStore(tmp_path))
    client = TestClient(app)
    ids = [client.post("/api/league/players", json={"name": f"消す{i}", "emoji": "🐸"}).json()["id"] for i in range(3)]
    assert client.post("/api/league/tournaments", json={"players": ids, "blocks": 1}).status_code == 422  # オーナー必須
    r = client.post("/api/league/tournaments", json={"players": ids, "blocks": 1, "owner_player": ids[0]}).json()
    keys = {r["tournament"]["id"]: r["owner_key"]}
    assert client.post("/api/league/reset", json={"confirm": "はい", "owner_keys": keys}).status_code == 400
    assert client.post("/api/league/reset", json={"confirm": "リセット"}).status_code == 403
    r = client.post("/api/league/reset", json={"confirm": "リセット", "owner_keys": keys})
    assert r.status_code == 200
    s = client.get("/api/league").json()
    assert s["players"] == [] and s["tournaments"] == []


def test_tournament_standings_and_player_history(store):
    ids = _players(store, 5)
    free = store.add_game(ids[:2], "練習")
    store.add_hand(free["id"], {"kind": "ron", "winner": free["players"][1], "loser": free["players"][0], "points": 32000})
    t, key = store.add_tournament("一回目", ids, 2)
    store.start_tournament(t["id"], key)
    for gid in t["block_games"]:
        g = store.data["games"][gid]
        w, l = g["players"][1], g["players"][0]
        store.add_hand(gid, {"kind": "ron", "winner": w, "loser": l, "points": 32000 if len(g["players"]) == 2 else 8000})
        store.finish_game(gid)
    store.start_final(t["id"], key)
    final = store.data["games"][t["final_game"]]
    k, other = final["players"][1], final["players"][0]
    store.add_hand(final["id"], {"kind": "ron", "winner": k, "loser": other, "points": 32000})
    store.finish_game(final["id"])
    rows = store.snapshot()["tournaments"][0]["standings"]
    assert rows[0]["id"] == k and rows[0]["result"] == "👑 キング" and len(rows) == 5
    assert {r["id"]: r["result"] for r in rows}[other] == "決勝2位"
    # 大会ごとの成績は大会の対局だけ（練習の対局は入らない）
    t_sum = sum(r["net"] for r in rows)
    assert t_sum == 0
    # 2回目の大会は0から
    t2, key2 = store.add_tournament("二回目", ids[:3], 1)
    rows2 = next(x for x in store.snapshot()["tournaments"] if x["id"] == t2["id"])["standings"]
    assert all(r["net"] == 0 and r["hands"] == 0 for r in rows2)
    # プレイヤーの成績は大会が終わっても見られる（通算＝大会＋大会以外）
    h = store.player_history(k)
    one = next(x for x in h["tournaments"] if x["name"] == "一回目")
    assert one["result"] == "👑 キング" and h["stats"]["kings"] == 1
    assert h["stats"]["net"] == sum(x["stats"]["net"] for x in h["tournaments"]) + h["free"]["net"]
    with pytest.raises(LeagueError):
        store.player_history("nobody")


def test_standings_order_final_before_blocks(store):
    ids = _players(store, 5)
    t, key = store.add_tournament("順番", ids, 2)
    store.start_tournament(t["id"], key)
    for gid in t["block_games"]:
        g = store.data["games"][gid]
        store.add_hand(gid, {"kind": "ron", "winner": g["players"][1], "loser": g["players"][0],
                             "points": 32000 if len(g["players"]) == 2 else 8000})
        store.finish_game(gid)
    store.start_final(t["id"], key)
    f = store.data["games"][t["final_game"]]
    store.add_hand(f["id"], {"kind": "ron", "winner": f["players"][1], "loser": f["players"][0], "points": 32000})
    store.finish_game(f["id"])
    res = [r["result"] for r in store.tour_standings(t)]
    assert res[:2] == ["👑 キング", "決勝2位"] and all("ブロック" in x for x in res[2:])


def test_device_binding_until_tournament_ends(store):
    ids = _players(store, 3)
    t, key = store.add_tournament("紐づけ", ids, 1, owner_player=ids[0])
    with pytest.raises(Forbidden):
        store.invite_device(t["id"], "wrong", ids[1])
    with pytest.raises(LeagueError):
        store.invite_device(t["id"], key, "nobody")
    tok = store.invite_device(t["id"], key, ids[1])
    with pytest.raises(LeagueError):
        store.join_device(t["id"], ids[1], "wrong")
    dk = store.join_device(t["id"], ids[1], tok)
    assert store.device_ok(t["id"], ids[1], dk) and not store.device_ok(t["id"], ids[2], dk)
    with pytest.raises(LeagueError):
        store.join_device(t["id"], ids[1], tok)  # 招待は1回だけ
    snap = next(x for x in store.snapshot()["tournaments"] if x["id"] == t["id"])
    assert list(snap["devices"]) == [ids[1]] and "key" not in snap["devices"][ids[1]]
    # 別のスマホでつなぎ直すと、前のスマホは外れる
    dk2 = store.join_device(t["id"], ids[1], store.invite_device(t["id"], key, ids[1]))
    assert store.device_ok(t["id"], ids[1], dk2) and not store.device_ok(t["id"], ids[1], dk)
    # オーナーが強制解除
    store.unbind_device(t["id"], key, ids[1])
    assert not store.device_ok(t["id"], ids[1], dk2)
    # 大会が終わると全員の紐づけも終わる
    dk3 = store.join_device(t["id"], ids[2], store.invite_device(t["id"], key, ids[2]))
    tok4 = store.invite_device(t["id"], key, ids[0])
    store.start_tournament(t["id"], key)
    g = store.data["games"][t["final_game"]]
    store.add_hand(g["id"], {"kind": "ron", "winner": ids[2], "loser": ids[1], "points": 8000})
    assert store.device_ok(t["id"], ids[2], dk3)
    store.finish_game(g["id"])
    assert t["status"] == "done" and not store.device_ok(t["id"], ids[2], dk3)
    with pytest.raises(LeagueError):
        store.join_device(t["id"], ids[0], tok4)
    with pytest.raises(LeagueError):
        store.invite_device(t["id"], key, ids[0])


def test_device_binding_ends_with_forced_end_and_self_leave(store):
    ids = _players(store, 5)
    t, key = store.add_tournament("途中", ids, 2, owner_player=ids[0])
    dk = store.join_device(t["id"], ids[3], store.invite_device(t["id"], key, ids[3]))
    store.leave_device(t["id"], ids[3], "wrong")
    assert store.device_ok(t["id"], ids[3], dk)
    store.leave_device(t["id"], ids[3], dk)
    assert not store.device_ok(t["id"], ids[3], dk)
    dk = store.join_device(t["id"], ids[4], store.invite_device(t["id"], key, ids[4]))
    store.start_tournament(t["id"], key)
    store.end_tournament(t["id"], key)  # オーナーの強制終了
    assert not store.device_ok(t["id"], ids[4], dk) and t["devices"] == {}


def test_device_api_and_qr(tmp_path, monkeypatch):
    import app.league_api as api
    monkeypatch.setattr(api, "store", LeagueStore(tmp_path))
    client = TestClient(app)
    ids = [client.post("/api/league/players", json={"name": f"端末{i}", "emoji": "🐸"}).json()["id"] for i in range(3)]
    r = client.post("/api/league/tournaments", json={"players": ids, "blocks": 1, "owner_player": ids[0]}).json()
    tid, H = r["tournament"]["id"], {"X-Owner-Key": r["owner_key"]}
    assert client.post(f"/api/league/tournaments/{tid}/invite", json={"player": ids[1]}).status_code == 403
    tok = client.post(f"/api/league/tournaments/{tid}/invite", json={"player": ids[1]}, headers=H).json()["token"]
    dk = client.post(f"/api/league/tournaments/{tid}/join", json={"player": ids[1], "token": tok}).json()["device_key"]
    assert client.post(f"/api/league/tournaments/{tid}/whoami", json={"player": ids[1], "device_key": dk}).json()["ok"]
    t = client.get("/api/league").json()["tournaments"][0]
    assert ids[1] in t["devices"] and "key" not in str(t["devices"])
    r = client.post(f"/api/league/tournaments/{tid}/unbind", json={}, headers=H)
    assert r.status_code == 200 and r.json()["devices"] == {}
    assert not client.post(f"/api/league/tournaments/{tid}/whoami", json={"player": ids[1], "device_key": dk}).json()["ok"]
    q = client.get("/api/league/qr", params={"text": "https://example.test/taikai#join=x"})
    assert q.status_code == 200 and q.headers["content-type"].startswith("image/svg") and b"<svg" in q.content


def test_staff_owner_not_in_blocks_or_standings(store):
    ids = _players(store, 4)
    with pytest.raises(LeagueError):
        store.add_tournament("PC運営", ids[:3], 1, owner_player=ids[3])  # 参加していない人はオーナーにできない
    t, key = store.add_tournament("PC運営", ids, 1, owner_name="  はせけん  ")
    assert t["owner_player"] is None and t["owner_name"] == "はせけん"
    assert "はせけん" not in [store.data["players"][p]["name"] for b in t["blocks"] for p in b]
    assert [r["id"] for r in store.tour_standings(t)] and all(r["id"] in ids for r in store.tour_standings(t))
    store.start_tournament(t["id"], key)  # 運営だけのオーナーも操作できる
    # 参加者のオーナーへ切り替え・運営へ戻す
    store.edit_tournament(t["id"], key, owner_player=ids[2])
    assert t["owner_player"] == ids[2] and t["owner_name"] is None
    store.edit_tournament(t["id"], key, owner_player="", owner_name="運営さん")
    assert t["owner_player"] is None and t["owner_name"] == "運営さん"
    with pytest.raises(LeagueError):
        store.edit_tournament(t["id"], key, owner_player="")  # 名前なしで外すことはできない


def test_owner_leaving_entries_becomes_staff(store):
    ids = _players(store, 5)
    t, key = store.add_tournament("入れ替え", ids[:4], 1, owner_player=ids[0])
    store.change_entries(t["id"], key, ids[1:5], 1)
    assert t["owner_player"] is None and t["owner_name"] == "P0"


def test_api_staff_owner(tmp_path, monkeypatch):
    import app.league_api as api
    monkeypatch.setattr(api, "store", LeagueStore(tmp_path))
    client = TestClient(app)
    ids = [client.post("/api/league/players", json={"name": f"運営{i}", "emoji": "🐸"}).json()["id"] for i in range(3)]
    assert client.post("/api/league/tournaments", json={"players": ids, "blocks": 1, "owner_name": " "}).status_code == 422
    r = client.post("/api/league/tournaments", json={"players": ids, "blocks": 1, "owner_name": "PCの人"})
    assert r.status_code == 200 and r.json()["tournament"]["owner_name"] == "PCの人"
    s = client.get("/api/league").json()
    assert len(s["players"]) == 3  # 運営者はプレイヤーにも成績にも入らない
