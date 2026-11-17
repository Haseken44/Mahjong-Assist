"""はせけん麻雀大会・個人成績の集計（プレイヤー・対局・大会）。

- プレイヤーは名前とアバター（写真か絵文字）を必ず登録する。
- 対局（卓）は3人か4人。1局ごとに点数のやり取りを記録し、持ち点と個人成績を随時更新する。
  - 勝ち点   ＝ 1局ごとに受け取った点の合計（アガリ・リーチ棒の回収など）
  - マイナス点数 ＝ 1局ごとに払った点の合計（放銃・ツモられ・リーチ棒など）
- 大会：参加者をブロック（卓）に分けて1半荘ずつ打ち、各ブロックのトップが決勝卓へ。
  三麻4ブロック → 決勝は四麻、四麻3ブロック → 決勝は三麻。決勝のトップが「キング」。

ここに入るのは名前・アバター・点数だけ。手牌や映像は一切入れない（手牌の秘密は PlayerSession の中だけ）。
データは data/league/league.json（コミットしない）に保存する。uvicorn は workers=1 なのでロック1つで足りる。
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import secrets
import threading
import time
from pathlib import Path

SEATS = ["東", "南", "西", "北"]
START_POINTS = {4: 25000, 3: 35000}  # 配給原点（雀魂と同じ）
MAX_NAME = 16
MAX_POINTS = 1_000_000
MIN_START, MAX_START = 1000, 200_000  # 持ち点として選べる範囲（100点単位）


class LeagueError(ValueError):
    """プレイヤーに見せてよい日本語のエラー。"""


class Forbidden(LeagueError):
    """大会のオーナー端末でないと操作できない。"""


def default_dir() -> Path:
    base = Path(os.environ.get("MAHJONG_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
    return base / "league"


def check_start(v) -> int:
    """開始前に決める持ち点（100点単位）。"""
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise LeagueError("持ち点を数字で入力してください") from None
    if not MIN_START <= v <= MAX_START or v % 100:
        raise LeagueError(f"持ち点は{MIN_START:,}〜{MAX_START:,}点の100点単位で入力してください")
    return v


def _new_id() -> str:
    return secrets.token_hex(4)


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def block_sizes(n: int, blocks: int) -> list[int]:
    """n 人を blocks 個のブロックに分けたときの各ブロックの人数（多い順）。"""
    base, extra = divmod(n, blocks)
    return [base + 1] * extra + [base] * (blocks - extra)


def formats(n: int) -> list[dict]:
    """n 人で組める大会形式。ブロック数＝決勝の人数なので 3 か 4。各ブロックは 3 人か 4 人。"""
    out = []
    for b in (4, 3):
        if 3 * b <= n <= 4 * b:
            sizes = block_sizes(n, b)
            kinds = sorted(set(sizes), reverse=True)
            table = "・".join(f"{'四麻' if s == 4 else '三麻'}{sizes.count(s)}卓" for s in kinds)
            out.append({
                "blocks": b,
                "sizes": sizes,
                "final_players": b,
                "label": f"{table} → 決勝は{'四麻' if b == 4 else '三麻'}（各ブロックのトップ{b}人）",
            })
    return out


class LeagueStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else default_dir()
        self.avatar_dir = self.root / "avatars"
        self.path = self.root / "league.json"
        self.lock = threading.RLock()
        self.data = {"players": {}, "games": {}, "tournaments": {}}
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                # 壊れていたら退避して空から始める（消さない）
                self.path.rename(self.path.with_suffix(f".broken-{int(time.time())}"))

    # ---------- 保存 ----------
    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    # ---------- プレイヤー ----------
    def _player(self, pid: str) -> dict:
        p = self.data["players"].get(pid)
        if not p:
            raise LeagueError("そのプレイヤーは登録されていません")
        return p

    def _check_name(self, name: str, exclude: str | None = None) -> str:
        name = " ".join((name or "").split())
        if not name:
            raise LeagueError("名前を入力してください")
        if len(name) > MAX_NAME:
            raise LeagueError(f"名前は{MAX_NAME}文字までです")
        for pid, p in self.data["players"].items():
            if pid != exclude and p["name"].casefold() == name.casefold():
                raise LeagueError(f"「{name}」はもう登録されています。別の名前にしてください")
        return name

    @staticmethod
    def _check_emoji(emoji: str | None) -> str | None:
        if emoji is None:
            return None
        emoji = emoji.strip()
        if not emoji or len(emoji) > 8:
            raise LeagueError("アバターの絵文字が正しくありません")
        return emoji

    def add_player(self, name: str, emoji: str | None = None, photo: bytes | None = None) -> dict:
        with self.lock:
            name = self._check_name(name)
            emoji = self._check_emoji(emoji)
            if not emoji and not photo:
                raise LeagueError("アバター（写真か絵文字）を選んでください")
            pid = _new_id()
            p = {"id": pid, "name": name, "emoji": emoji or "🀄", "photo": None, "created": int(time.time())}
            if photo:
                p["photo"] = self._save_photo(pid, photo)
            self.data["players"][pid] = p
            self._save()
            return dict(p)

    def update_player(self, pid: str, name: str | None = None, emoji: str | None = None,
                      photo: bytes | None = None, remove_photo: bool = False) -> dict:
        with self.lock:
            p = self._player(pid)
            if name is not None:
                p["name"] = self._check_name(name, exclude=pid)
            if emoji is not None:
                p["emoji"] = self._check_emoji(emoji)
            if photo:
                self._drop_photo(p)
                p["photo"] = self._save_photo(pid, photo)
            elif remove_photo:
                self._drop_photo(p)
            self._save()
            return dict(p)

    def delete_player(self, pid: str) -> None:
        with self.lock:
            p = self._player(pid)
            if any(pid in g["players"] for g in self.data["games"].values()) or \
                    any(pid in t["players"] for t in self.data["tournaments"].values()):
                raise LeagueError("対局・大会に参加したプレイヤーは削除できません（成績が合わなくなるため）")
            self._drop_photo(p)
            del self.data["players"][pid]
            self._save()

    def _save_photo(self, pid: str, raw: bytes) -> str:
        """写真を正方形に切り抜き 160px の JPEG にして保存する（位置情報などのメタデータは残らない）。"""
        import cv2
        import numpy as np

        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise LeagueError("写真を読み込めませんでした。別の写真を選んでください")
        h, w = img.shape[:2]
        s = min(h, w)
        img = img[(h - s) // 2:(h - s) // 2 + s, (w - s) // 2:(w - s) // 2 + s]
        img = cv2.resize(img, (160, 160), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise LeagueError("写真を保存できませんでした")
        self.avatar_dir.mkdir(parents=True, exist_ok=True)
        name = f"{pid}-{secrets.token_hex(3)}.jpg"
        (self.avatar_dir / name).write_bytes(buf.tobytes())
        return name

    def _drop_photo(self, p: dict) -> None:
        if p.get("photo"):
            try:
                (self.avatar_dir / p["photo"]).unlink()
            except OSError:
                pass
        p["photo"] = None

    def avatar_path(self, name: str) -> Path | None:
        if not name or "/" in name or "\\" in name or name.startswith("."):
            return None
        path = self.avatar_dir / name
        return path if path.is_file() else None

    # ---------- 対局 ----------
    def _game(self, gid: str) -> dict:
        g = self.data["games"].get(gid)
        if not g:
            raise LeagueError("その対局は見つかりません")
        return g

    def _make_game(self, player_ids: list[str], title: str, tournament: str | None = None,
                   stage: str | None = None, block: int | None = None, start: int | None = None) -> dict:
        if len(player_ids) not in (3, 4):
            raise LeagueError("対局は3人（三麻）か4人（四麻）です")
        if len(set(player_ids)) != len(player_ids):
            raise LeagueError("同じプレイヤーが2回選ばれています")
        for pid in player_ids:
            self._player(pid)
        n = len(player_ids)
        start = check_start(start) if start is not None else START_POINTS[n]
        gid = _new_id()
        g = {
            "id": gid,
            "title": (title or "").strip()[:30] or ("四麻" if n == 4 else "三麻"),
            "players": list(player_ids),  # 並び＝起家から順の席（東・南・西・北）
            "start": start,
            "points": {pid: start for pid in player_ids},
            "dealer": 0,
            "hands": [],
            "finished": False,
            "ranks": None,
            "tournament": tournament,
            "stage": stage,
            "block": block,
            "created": int(time.time()),
        }
        self.data["games"][gid] = g
        return g

    def add_game(self, player_ids: list[str], title: str = "", shuffle: bool = True, start: int | None = None) -> dict:
        """大会以外の対局。席順（東南西北）はこちらで抽選する（shuffle=False はテスト用）。"""
        with self.lock:
            order = list(player_ids)
            if shuffle:
                random.SystemRandom().shuffle(order)
            g = self._make_game(order, title, start=start)
            self._save()
            return g

    def set_game_start(self, gid: str, start: int, key: str | None = None) -> dict:
        """まだ1局も記録していない対局の持ち点を変える（大会の卓はオーナーだけ）。"""
        with self.lock:
            g = self._game(gid)
            if g["tournament"]:
                self._owner(self._tour(g["tournament"]), key)
            if g["hands"] or g["finished"]:
                raise LeagueError("点数を記録したあとは持ち点を変えられません（最後の局から取り消すと変えられます）")
            start = check_start(start)
            g["start"] = start
            g["points"] = {pid: start for pid in g["players"]}
            self._save()
            return g

    def delete_game(self, gid: str) -> None:
        with self.lock:
            g = self._game(gid)
            if g["tournament"]:
                raise LeagueError("大会の対局は削除できません")
            if g["hands"]:
                raise LeagueError("記録のある対局は削除できません。最後の局から取り消してください")
            del self.data["games"][gid]
            self._save()

    @staticmethod
    def _amount(v, what: str) -> int:
        try:
            v = int(v)
        except (TypeError, ValueError):
            raise LeagueError(f"{what}を数字で入力してください") from None
        if v < 0 or v > MAX_POINTS:
            raise LeagueError(f"{what}が大きすぎるか、マイナスです")
        return v

    def add_hand(self, gid: str, hand: dict) -> dict:
        """1局の結果を記録する。

        hand = {kind: "ron"|"tsumo"|"other", winner, loser, points, pay_child, pay_dealer, riichi: [pid], deltas: {pid: int}}
        - ron   : 放銃者(loser)が points（本場込み）を和了者に払う
        - tsumo : 親は pay_dealer、子は pay_child を払う（和了者が親なら全員 pay_child＝「〇〇点オール」）
        - other : 流局・罰符など。deltas に各プレイヤーの増減を直接入れる
        リーチ棒（riichi に入れた人が 1000 点ずつ）はアガった人が受け取る。
        """
        with self.lock:
            g = self._game(gid)
            if g["finished"]:
                raise LeagueError("この対局は終了しています。記録するには「対局を再開」を押してください")
            pl = g["players"]
            kind = hand.get("kind")
            deltas = {pid: 0 for pid in pl}
            winner = hand.get("winner")
            loser = None
            if kind in ("ron", "tsumo"):
                if winner not in pl:
                    raise LeagueError("アガった人を選んでください")
                if kind == "ron":
                    loser = hand.get("loser")
                    if loser not in pl or loser == winner:
                        raise LeagueError("振り込んだ人（放銃者）を選んでください")
                    pts = self._amount(hand.get("points"), "点数")
                    if pts == 0:
                        raise LeagueError("点数を入力してください")
                    deltas[winner] += pts
                    deltas[loser] -= pts
                else:
                    dealer_id = pl[g["dealer"]]
                    child = self._amount(hand.get("pay_child"), "子の支払い")
                    dealer_pay = child if winner == dealer_id else self._amount(hand.get("pay_dealer"), "親の支払い")
                    if child == 0 or dealer_pay == 0:
                        raise LeagueError("ツモの支払い点数を入力してください")
                    for pid in pl:
                        if pid != winner:
                            pay = dealer_pay if pid == dealer_id else child
                            deltas[pid] -= pay
                            deltas[winner] += pay
                riichi = [pid for pid in (hand.get("riichi") or []) if pid in pl]
                for pid in set(riichi):
                    deltas[pid] -= 1000
                    deltas[winner] += 1000
            elif kind == "other":
                raw = hand.get("deltas") or {}
                for pid in pl:
                    try:
                        v = int(raw.get(pid) or 0)
                    except (TypeError, ValueError):
                        raise LeagueError("点数の増減を数字で入力してください") from None
                    if abs(v) > MAX_POINTS:
                        raise LeagueError("点数の増減が大きすぎます")
                    deltas[pid] = v
                if not any(deltas.values()):
                    raise LeagueError("点数の増減を入力してください")
                winner = None
            else:
                raise LeagueError("ロン・ツモ・その他から選んでください")

            rec = {
                "kind": kind,
                "winner": winner,
                "loser": loser,
                "deltas": deltas,
                "dealer_before": g["dealer"],
                "note": (hand.get("note") or "").strip()[:40],
                "at": int(time.time()),
            }
            for pid, d in deltas.items():
                g["points"][pid] += d
            # 子がアガったら親が次の人へ（親がアガったら連荘）。流局などは画面で親を選び直す
            if winner is not None and pl.index(winner) != g["dealer"]:
                g["dealer"] = (g["dealer"] + 1) % len(pl)
            g["hands"].append(rec)
            self._save()
            return g

    def undo_hand(self, gid: str) -> dict:
        with self.lock:
            g = self._game(gid)
            if g["finished"]:
                raise LeagueError("終了した対局は取り消せません。先に「対局を再開」を押してください")
            if not g["hands"]:
                raise LeagueError("取り消す局がありません")
            rec = g["hands"].pop()
            for pid, d in rec["deltas"].items():
                g["points"][pid] -= d
            g["dealer"] = rec["dealer_before"]
            self._save()
            return g

    def set_dealer(self, gid: str, seat: int) -> dict:
        with self.lock:
            g = self._game(gid)
            if not isinstance(seat, int) or not 0 <= seat < len(g["players"]):
                raise LeagueError("親を選び直してください")
            g["dealer"] = seat
            self._save()
            return g

    @staticmethod
    def ranking(g: dict) -> list[str]:
        """持ち点の多い順。同点は起家に近い席が上（一般的な同点の扱い）。"""
        pl = g["players"]
        return sorted(pl, key=lambda pid: (-g["points"][pid], pl.index(pid)))

    def finish_game(self, gid: str) -> dict:
        with self.lock:
            g = self._game(gid)
            if g["finished"]:
                return g
            if not g["hands"]:
                raise LeagueError("まだ1局も記録されていません")
            g["finished"] = True
            g["ranks"] = self.ranking(g)
            if g["tournament"] and g["stage"] == "final":
                t = self.data["tournaments"][g["tournament"]]
                t["king"] = g["ranks"][0]
                t["status"] = "done"
            self._save()
            return g

    def reopen_game(self, gid: str) -> dict:
        with self.lock:
            g = self._game(gid)
            if not g["finished"]:
                return g
            t = self.data["tournaments"].get(g["tournament"]) if g["tournament"] else None
            if t and g["stage"] == "block" and t["status"] != "blocks":
                raise LeagueError("決勝が始まったので、ブロックの対局は再開できません")
            g["finished"] = False
            g["ranks"] = None
            if t and g["stage"] == "final":
                t["king"] = None
                t["status"] = "final"
            self._save()
            return g

    # ---------- 大会 ----------
    def _tour(self, tid: str) -> dict:
        t = self.data["tournaments"].get(tid)
        if not t:
            raise LeagueError("その大会は見つかりません")
        return t

    def _owner(self, t: dict, key: str | None) -> None:
        if not key or not secrets.compare_digest(_hash(key), t["owner"]):
            raise Forbidden("この操作は大会を作ったオーナーの端末でだけできます")

    @staticmethod
    def _draw(players: list[str], blocks: int) -> list[list[str]]:
        order = list(players)
        random.SystemRandom().shuffle(order)
        out, i = [], 0
        for size in block_sizes(len(order), blocks):
            out.append(order[i:i + size])
            i += size
        return out

    @staticmethod
    def tour_start(t: dict, n: int) -> int:
        return int((t.get("start_points") or {}).get(str(n), START_POINTS[n]))

    def _check_start_points(self, sp: dict | None) -> dict:
        sp = sp or {}
        return {str(n): check_start(sp.get(str(n), sp.get(n, START_POINTS[n]))) for n in (4, 3)}

    def add_tournament(self, name: str, player_ids: list[str], blocks: int,
                       start_points: dict | None = None, owner_player: str | None = None) -> tuple[dict, str]:
        with self.lock:
            start_points = self._check_start_points(start_points)
            if owner_player:
                self._player(owner_player)
            if len(set(player_ids)) != len(player_ids):
                raise LeagueError("同じプレイヤーが2回選ばれています")
            for pid in player_ids:
                self._player(pid)
            n = len(player_ids)
            ok = [f["blocks"] for f in formats(n)]
            if not ok:
                raise LeagueError(f"{n}人では大会を組めません。9〜16人で、3〜4ブロックに分けられる人数にしてください")
            if blocks not in ok:
                raise LeagueError(f"{n}人では{blocks}ブロックに分けられません")
            key = secrets.token_urlsafe(18)
            tid = _new_id()
            t = {
                "id": tid,
                "name": " ".join((name or "").split())[:30] or "はせけん麻雀大会",
                "players": list(player_ids),
                "blocks": self._draw(player_ids, blocks),
                "block_games": [],
                "final_game": None,
                "status": "setup",  # setup → blocks → final → done
                "king": None,
                "start_points": start_points,       # 開始前に決める持ち点 {"4": 25000, "3": 35000}
                "owner_player": owner_player or None,  # オーナーのプレイヤー（🇯🇵の旗を立てる）
                "owner": _hash(key),
                "created": int(time.time()),
            }
            self.data["tournaments"][tid] = t
            self._save()
            return t, key

    def redraw(self, tid: str, key: str | None) -> dict:
        with self.lock:
            t = self._tour(tid)
            self._owner(t, key)
            if t["status"] != "setup":
                raise LeagueError("大会が始まったので、抽選し直せません")
            t["blocks"] = self._draw(t["players"], len(t["blocks"]))
            self._save()
            return t

    def _check_blocks(self, blocks: list[list[str]]) -> list[list[str]]:
        if not isinstance(blocks, list) or len(blocks) not in (3, 4):
            raise LeagueError("ブロックは3つか4つです")
        flat = [pid for b in blocks for pid in b]
        if len(set(flat)) != len(flat):
            raise LeagueError("同じプレイヤーが2つの席に入っています")
        for b in blocks:
            if len(b) not in (3, 4):
                raise LeagueError("1ブロックは3人（三麻）か4人（四麻）です")
        for pid in flat:
            self._player(pid)
        return [list(b) for b in blocks]

    def edit_tournament(self, tid: str, key: str | None, name: str | None = None,
                        blocks: list[list[str]] | None = None, start_points: dict | None = None,
                        owner_player: str | None = None) -> dict:
        """オーナーが大会を編集する。

        - 大会名：いつでも変えられる
        - ブロック分け（席順も）：開始前は自由に。開始後は、まだ1局も記録していないブロックだけ
          入れ替え・差し替えができる（来られなくなった人の代わりなど）。決勝が始まったら変えられない
        """
        with self.lock:
            t = self._tour(tid)
            self._owner(t, key)
            if name is not None:
                t["name"] = " ".join(name.split())[:30] or t["name"]
            if owner_player is not None:
                if owner_player:
                    self._player(owner_player)
                t["owner_player"] = owner_player or None
            if start_points is not None:
                sp = self._check_start_points(start_points)
                changed = sp != {str(n): self.tour_start(t, n) for n in (4, 3)}
                if changed and t["status"] == "done":
                    raise LeagueError("終わった大会の持ち点は変えられません")
                t["start_points"] = sp
                # まだ点数を記録していない卓には新しい持ち点を反映する
                gids = list(t["block_games"]) + ([t["final_game"]] if t["final_game"] else [])
                for gid in gids:
                    g = self.data["games"][gid]
                    if not g["hands"] and not g["finished"]:
                        st = self.tour_start(t, len(g["players"]))
                        g["start"] = st
                        g["points"] = {pid: st for pid in g["players"]}
            if blocks is not None:
                blocks = self._check_blocks(blocks)
                if t["status"] == "setup":
                    t["blocks"] = blocks
                elif t["status"] == "blocks":
                    if len(blocks) != len(t["blocks"]):
                        raise LeagueError("開始後はブロックの数を変えられません")
                    games = [self.data["games"][gid] for gid in t["block_games"]]
                    for i, (old, new) in enumerate(zip(t["blocks"], blocks)):
                        if old != new and (games[i]["hands"] or games[i]["finished"]):
                            raise LeagueError(f"{chr(65 + i)}ブロックはもう点数を記録しているので、メンバーを変えられません")
                    for i, (old, new) in enumerate(zip(t["blocks"], blocks)):
                        if old != new:
                            g = games[i]
                            n = len(new)
                            st = self.tour_start(t, n)
                            g.update(players=list(new), start=st, points={pid: st for pid in new}, dealer=0)
                    t["blocks"] = blocks
                else:
                    raise LeagueError("決勝が始まったので、ブロック分けは変えられません")
                t["players"] = [pid for b in t["blocks"] for pid in b]
            for i, gid in enumerate(t["block_games"]):  # 卓の名前も大会名に合わせる
                self.data["games"][gid]["title"] = f"{t['name']} {chr(65 + i)}ブロック"
            if t["final_game"]:
                self.data["games"][t["final_game"]]["title"] = f"{t['name']} 決勝"
            self._save()
            return t

    def change_entries(self, tid: str, key: str | None, player_ids: list[str], blocks: int) -> dict:
        """開始前に参加者・ブロック数を変えて抽選し直す。"""
        with self.lock:
            t = self._tour(tid)
            self._owner(t, key)
            if t["status"] != "setup":
                raise LeagueError("開始後は参加者を増やしたり減らしたりできません（ブロックの入れ替えはできます）")
            if len(set(player_ids)) != len(player_ids):
                raise LeagueError("同じプレイヤーが2回選ばれています")
            for pid in player_ids:
                self._player(pid)
            n = len(player_ids)
            if blocks not in [f["blocks"] for f in formats(n)]:
                raise LeagueError(f"{n}人では{blocks}ブロックに分けられません（9〜16人）")
            t["players"] = list(player_ids)
            t["blocks"] = self._draw(player_ids, blocks)
            self._save()
            return t

    def start_tournament(self, tid: str, key: str | None) -> dict:
        with self.lock:
            t = self._tour(tid)
            self._owner(t, key)
            if t["status"] != "setup":
                raise LeagueError("この大会はもう始まっています")
            for i, members in enumerate(t["blocks"]):
                g = self._make_game(members, f"{t['name']} {chr(65 + i)}ブロック", tournament=tid, stage="block", block=i,
                                    start=self.tour_start(t, len(members)))
                t["block_games"].append(g["id"])
            t["status"] = "blocks"
            self._save()
            return t

    def block_winners(self, t: dict) -> list[str | None]:
        out = []
        for gid in t["block_games"]:
            g = self.data["games"][gid]
            out.append(g["ranks"][0] if g["finished"] else None)
        return out

    def start_final(self, tid: str, key: str | None) -> dict:
        with self.lock:
            t = self._tour(tid)
            self._owner(t, key)
            if t["status"] != "blocks":
                raise LeagueError("決勝はブロックの対局がすべて終わってから始めます")
            winners = self.block_winners(t)
            if None in winners:
                left = [chr(65 + i) for i, w in enumerate(winners) if w is None]
                raise LeagueError(f"まだ終わっていないブロックがあります（{'・'.join(left)}ブロック）")
            order = list(winners)
            random.SystemRandom().shuffle(order)  # 決勝の席順も抽選
            g = self._make_game(order, f"{t['name']} 決勝", tournament=tid, stage="final",
                                start=self.tour_start(t, len(order)))
            t["final_game"] = g["id"]
            t["status"] = "final"
            self._save()
            return t

    def delete_tournament(self, tid: str, key: str | None) -> None:
        with self.lock:
            t = self._tour(tid)
            self._owner(t, key)
            if t["status"] != "setup":
                raise LeagueError("始まった大会は削除できません")
            del self.data["tournaments"][tid]
            self._save()

    # ---------- 集計 ----------
    def stats(self) -> dict[str, dict]:
        """個人成績（対局中の局も含めて随時集計）。"""
        out = {pid: {"plus": 0, "minus": 0, "net": 0, "hands": 0, "wins": 0, "deal_ins": 0,
                     "games": 0, "finished": 0, "tops": 0, "rank_sum": 0, "kings": 0}
               for pid in self.data["players"]}
        for g in self.data["games"].values():
            for pid in g["players"]:
                if pid in out:
                    out[pid]["games"] += 1
            for h in g["hands"]:
                for pid, d in h["deltas"].items():
                    s = out.get(pid)
                    if s is None:
                        continue
                    s["hands"] += 1
                    if d > 0:
                        s["plus"] += d
                    else:
                        s["minus"] += d
                if h.get("winner") in out:
                    out[h["winner"]]["wins"] += 1
                if h.get("loser") in out:
                    out[h["loser"]]["deal_ins"] += 1
            if g["finished"] and g["ranks"]:
                for i, pid in enumerate(g["ranks"]):
                    if pid in out:
                        out[pid]["finished"] += 1
                        out[pid]["rank_sum"] += i + 1
                        out[pid]["tops"] += i == 0
        for t in self.data["tournaments"].values():
            if t.get("king") in out:
                out[t["king"]]["kings"] += 1
        for s in out.values():
            s["net"] = s["plus"] + s["minus"]
            s["avg_rank"] = round(s["rank_sum"] / s["finished"], 2) if s["finished"] else None
            del s["rank_sum"]
        return out

    # ---------- 画面用のまとめ ----------
    def snapshot(self) -> dict:
        with self.lock:
            stats = self.stats()
            players = []
            for p in self.data["players"].values():
                players.append({
                    "id": p["id"], "name": p["name"], "emoji": p["emoji"],
                    "avatar": f"/api/league/avatars/{p['photo']}" if p.get("photo") else None,
                    "stats": stats[p["id"]],
                })
            players.sort(key=lambda p: (-p["stats"]["net"], p["name"]))
            games = []
            for g in self.data["games"].values():
                games.append({**{k: v for k, v in g.items()}, "order": self.ranking(g)})
            games.sort(key=lambda g: (g["finished"], -g["created"]))
            tours = []
            for t in self.data["tournaments"].values():
                d = {k: v for k, v in t.items() if k != "owner"}  # オーナーの合言葉（ハッシュ）は出さない
                d["winners"] = self.block_winners(t)
                d["formats"] = formats(len(t["players"]))
                tours.append(d)
            tours.sort(key=lambda t: -t["created"])
            return {"players": players, "games": games, "tournaments": tours, "start_points": START_POINTS}
