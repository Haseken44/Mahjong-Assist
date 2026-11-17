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
    assert [x["blocks"] for x in formats(9)] == [3]
    assert [x["blocks"] for x in formats(16)] == [4]
    assert block_sizes(13, 4) == [4, 3, 3, 3]
    assert formats(8) == [] and formats(17) == []


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
        store.add_tournament("x", _players(store, 8), 3)


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

    r = client.post("/api/league/tournaments", json={"players": ids, "blocks": 4})
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
