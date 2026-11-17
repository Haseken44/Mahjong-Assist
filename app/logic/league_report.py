"""大会記録の Markdown 書き出しと、公開の成績ページ（/seiseki/）の中身。

どちらも閲覧専用。出すのは名前・アバター・点数・結果だけで、オーナーの合言葉やスマホの紐づけは出さない。
"""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .league import LeagueStore

JST = ZoneInfo("Asia/Tokyo")
KIND = {4: "四麻", 3: "三麻", 2: "二麻"}
SEATS = "東南西北"
STATUS = {"setup": "開始前", "blocks": "ブロック戦", "final": "決勝", "done": "終了"}


def when(ts: int | None, fmt: str = "%Y/%m/%d %H:%M") -> str:
    return datetime.fromtimestamp(ts, JST).strftime(fmt) if ts else ""


def signed(n: int) -> str:
    return f"{n:+,}" if n else "0"


def tour_status(t: dict) -> str:
    return "途中で終了" if t.get("ended_early") else STATUS.get(t["status"], t["status"])


def owner_label(store: LeagueStore, t: dict) -> str:
    if t.get("owner_player"):
        p = store.data["players"].get(t["owner_player"])
        return f"{p['name'] if p else '（削除）'}（参加者）"
    return f"{t['owner_name']}（運営・参加しない）" if t.get("owner_name") else "（未設定）"


def tour_games(store: LeagueStore, t: dict) -> list[tuple[str, dict]]:
    """大会の卓を（見出し, 対局）で並べる。"""
    out = []
    single = len(t["blocks"]) == 1
    for i, gid in enumerate(t["block_games"]):
        g = store.data["games"].get(gid)
        if g:
            out.append(("決勝" if single else f"{chr(65 + i)}ブロック", g))
    if t["final_game"] and t["final_game"] in store.data["games"] and t["final_game"] not in t["block_games"]:
        out.append(("決勝", store.data["games"][t["final_game"]]))
    return out


def game_state(g: dict) -> str:
    if g.get("aborted"):
        return "打ち切り"
    if g["finished"]:
        return "終了"
    return f"対局中・{len(g['hands'])}局" if g["hands"] else "開始前"


def hand_text(store: LeagueStore, g: dict, h: dict) -> str:
    name = lambda pid: (store.data["players"].get(pid) or {}).get("name", "（削除）")  # noqa: E731
    seat = SEATS[h["dealer_before"]] if h.get("dealer_before") is not None and h["dealer_before"] < 4 else ""
    if h["kind"] == "ron":
        s = f"{name(h['winner'])} が {name(h['loser'])} からロン"
    elif h["kind"] == "tsumo":
        s = f"{name(h['winner'])} がツモ"
    else:
        s = "その他（流局など）"
    if h.get("note"):
        s += f"（{h['note']}）"
    return f"親{seat}家・{s}" if seat else s


def tournament_markdown(store: LeagueStore, tid: str) -> tuple[str, str]:
    """大会の記録を Markdown にする。戻り値は（ファイル名, 本文）。"""
    with store.lock:
        t = store._tour(tid)
        P = store.data["players"]
        name = lambda pid: (P.get(pid) or {}).get("name", "（削除）")  # noqa: E731
        L: list[str] = [f"# {t['name']}", ""]
        L += [
            f"- 状態：{tour_status(t)}",
            f"- 作成：{when(t.get('created'))}" + (f"／終了：{when(t.get('ended'))}" if t.get("ended") else ""),
            f"- オーナー：{owner_label(store, t)}",
            f"- 参加者：{len(t['players'])}人・" + ("ブロック分けなし" if len(t["blocks"]) == 1 else f"{len(t['blocks'])}ブロック"),
        ]
        sizes = sorted({len(b) for b in t["blocks"]} | ({len(t["blocks"])} if len(t["blocks"]) > 1 else set()), reverse=True)
        L.append("- 持ち点：" + "・".join(f"{KIND[n]} {store.tour_start(t, n):,}点" for n in sizes))
        if t.get("king"):
            L.append(f"- 👑 キング：**{name(t['king'])}**")
        L += ["", "## 大会の成績", "", "| # | プレイヤー | 結果 | 合計 | 勝ち点 | マイナス | アガリ | 放銃 |", "|---|---|---|---:|---:|---:|---:|---:|"]
        for i, r in enumerate(store.tour_standings(t)):
            L.append(f"| {i + 1} | {name(r['id'])} | {r['result']} | {signed(r['net'])} | {r['plus']:,} | {r['minus']:,} | {r['wins']} | {r['deal_ins']} |")
        for label, g in tour_games(store, t):
            n = len(g["players"])
            L += ["", f"## {label}（{KIND.get(n, '')}・{game_state(g)}）", "",
                  "| 順位 | 席 | プレイヤー | 持ち点 |", "|---:|---|---|---:|"]
            for r, pid in enumerate(store.ranking(g)):
                L.append(f"| {r + 1} | {SEATS[g['players'].index(pid)]} | {name(pid)} | {g['points'][pid]:,} |")
            if g["hands"]:
                L += ["", "| 局 | 内容 | 点数の動き |", "|---:|---|---|"]
                for k, h in enumerate(g["hands"]):
                    moves = "、".join(f"{name(pid)} {signed(d)}" for pid, d in h["deltas"].items() if d)
                    L.append(f"| {k + 1} | {hand_text(store, g, h)} | {moves} |")
        L += ["", "---", f"はせけん麻雀大会（麻雀アシスト）から {when(int(time.time()))} に書き出し。"
              "勝ち点＝受け取った点、マイナス＝払った点。", ""]
        stamp = when(t.get("created"), "%Y%m%d")
        safe = "".join(c for c in t["name"] if c not in '\\/:*?"<>|').strip() or "大会"
        return f"{stamp}_{safe}.md", "\n".join(L)


def ranking_markdown(store: LeagueStore) -> tuple[str, str]:
    """通算成績と、すべての大会の結果を1つの Markdown にする。"""
    with store.lock:
        st = store.stats()
        P = store.data["players"]
        L = ["# はせけん麻雀大会 通算成績", "", f"{when(int(time.time()))} 時点。勝ち点＝受け取った点、マイナス＝払った点。", "",
             "| # | プレイヤー | 合計 | 勝ち点 | マイナス | 対局 | トップ | 平均順位 | キング |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
        rows = sorted(P.values(), key=lambda p: (-st[p["id"]]["net"], p["name"]))
        for i, p in enumerate(rows):
            s = st[p["id"]]
            avg = f"{s['avg_rank']:.2f}" if s["avg_rank"] is not None else "—"
            L.append(f"| {i + 1} | {p['name']} | {signed(s['net'])} | {s['plus']:,} | {s['minus']:,} | {s['games']} | {s['tops']} | {avg} | {s['kings']} |")
        L += ["", "## 大会の一覧", "", "| 大会 | 作成 | 状態 | キング |", "|---|---|---|---|"]
        for t in sorted(store.data["tournaments"].values(), key=lambda t: -t["created"]):
            king = (P.get(t.get("king")) or {}).get("name", "—") if t.get("king") else "—"
            L.append(f"| {t['name']} | {when(t['created'], '%Y/%m/%d')} | {tour_status(t)} | {king} |")
        L.append("")
        return f"{when(int(time.time()), '%Y%m%d')}_通算成績.md", "\n".join(L)
