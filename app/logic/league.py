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
START_POINTS = {4: 25000, 3: 35000, 2: 25000}  # 配給原点（雀魂と同じ。二麻は四麻と同じ）
KIND = {4: "四麻", 3: "三麻", 2: "二麻"}
# 二麻（2人麻雀）は四麻と同じルールで、アガリは役満だけ（子 32,000点・親 48,000点以上）
NIMA_YAKUMAN = {"child": 32000, "dealer": 48000}
MIN_PLAYERS, MAX_PLAYERS = 2, 16
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
    """n 人（2〜16人）で組める大会形式。

    - 2〜4人：ブロック分けなし。1卓（二麻・三麻・四麻）のトップがそのままキング
    - 5〜16人：2〜4ブロック（各2〜4人）に分け、各ブロックのトップ（＝ブロック数の人数）で決勝
      ブロック数が決勝の人数になる（2ブロック→二麻、3→三麻、4→四麻）
    おすすめ順：二麻の卓が少ない → ブロックが多い（決勝がにぎやか）の順。
    """
    if not MIN_PLAYERS <= n <= MAX_PLAYERS:
        return []
    if n <= 4:
        return [{"blocks": 1, "sizes": [n], "final_players": n,
                 "label": f"{KIND[n]}1卓で、そのままキングを決める（ブロック分けなし）"}]
    out = []
    for b in (4, 3, 2):
        if 2 * b <= n <= 4 * b:
            sizes = block_sizes(n, b)
            kinds = sorted(set(sizes), reverse=True)
            table = "・".join(f"{KIND[s]}{sizes.count(s)}卓" for s in kinds)
            out.append({
                "blocks": b,
                "sizes": sizes,
                "final_players": b,
                "label": f"{table} → 決勝は{KIND[b]}（各ブロックのトップ{b}人）",
            })
    out.sort(key=lambda f: (f["sizes"].count(2), -f["blocks"]))
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
        if len(player_ids) not in (2, 3, 4):
            raise LeagueError("対局は2人（二麻）・3人（三麻）・4人（四麻）のどれかです")
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

    def _build_hand(self, g: dict, hand: dict, dealer: int) -> dict:
        """1局の入力から点数の増減を計算した記録を作る（dealer＝その局の親の席）。

        hand = {kind: "ron"|"tsumo"|"other", winner, loser, points, pay_child, pay_dealer, riichi: [pid], deltas: {pid: int}}
        - ron   : 放銃者(loser)が points（本場込み）を和了者に払う
        - tsumo : 親は pay_dealer、子は pay_child を払う（和了者が親なら全員 pay_child＝「〇〇点オール」）
        - other : 流局・罰符など。deltas に各プレイヤーの増減を直接入れる
        リーチ棒（riichi に入れた人が 1000 点ずつ）はアガった人が受け取る。
        """
        pl = g["players"]
        kind = hand.get("kind")
        deltas = {pid: 0 for pid in pl}
        winner = hand.get("winner")
        loser = None
        riichi: list[str] = []
        pts = child = dealer_pay = None
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
                self._check_nima(pl, winner, dealer, pts)
                deltas[winner] += pts
                deltas[loser] -= pts
            elif len(pl) == 2:
                # 二麻のツモ：相手が役満の点数を全部払う（pay_child に入れる）
                child = self._amount(hand.get("pay_child"), "相手の支払い")
                if child == 0:
                    raise LeagueError("ツモの支払い点数を入力してください")
                self._check_nima(pl, winner, dealer, child)
                other = pl[1] if pl[0] == winner else pl[0]
                deltas[other] -= child
                deltas[winner] += child
            else:
                dealer_id = pl[dealer]
                child = self._amount(hand.get("pay_child"), "子の支払い")
                dealer_pay = child if winner == dealer_id else self._amount(hand.get("pay_dealer"), "親の支払い")
                if child == 0 or dealer_pay == 0:
                    raise LeagueError("ツモの支払い点数を入力してください")
                for pid in pl:
                    if pid != winner:
                        pay = dealer_pay if pid == dealer_id else child
                        deltas[pid] -= pay
                        deltas[winner] += pay
            riichi = sorted({pid for pid in (hand.get("riichi") or []) if pid in pl})
            for pid in riichi:
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
        return {
            "kind": kind,
            "winner": winner,
            "loser": loser,
            "points": pts,            # 直すときに入力欄へ戻すため、入力もそのまま残す
            "pay_child": child,
            "pay_dealer": dealer_pay,
            "riichi": riichi,
            "deltas": deltas,
            "dealer_before": dealer,
            "note": (hand.get("note") or "").strip()[:40],
            "at": int(time.time()),
        }

    @staticmethod
    def _check_nima(pl: list[str], winner: str, dealer: int, total: int) -> None:
        """二麻のアガリは役満だけ（子 32,000点・親 48,000点以上）。"""
        if len(pl) != 2:
            return
        need = NIMA_YAKUMAN["dealer"] if pl.index(winner) == dealer else NIMA_YAKUMAN["child"]
        if total < need:
            raise LeagueError(f"二麻のアガリは役満だけです（{'親' if need == 48000 else '子'}は{need:,}点以上）")

    @staticmethod
    def _next_dealer(g: dict, rec: dict) -> int:
        """子がアガったら親が次の人へ（親がアガったら連荘）。流局などは画面で親を選び直す。"""
        pl = g["players"]
        d = rec["dealer_before"]
        if rec["winner"] is not None and pl.index(rec["winner"]) != d:
            return (d + 1) % len(pl)
        return d

    @staticmethod
    def _recount(g: dict) -> None:
        """記録した局から持ち点を数え直す。"""
        g["points"] = {pid: g["start"] for pid in g["players"]}
        for h in g["hands"]:
            for pid, d in h["deltas"].items():
                g["points"][pid] += d

    def _editable(self, g: dict) -> None:
        if g["finished"]:
            raise LeagueError("この対局は終了しています。記録や修正をするには「対局を再開」を押してください")

    def add_hand(self, gid: str, hand: dict) -> dict:
        """1局の結果を記録する（入力の形は _build_hand）。"""
        with self.lock:
            g = self._game(gid)
            self._editable(g)
            rec = self._build_hand(g, hand, g["dealer"])
            g["hands"].append(rec)
            self._recount(g)
            g["dealer"] = self._next_dealer(g, rec)
            self._save()
            return g

    def _hand_index(self, g: dict, index) -> int:
        if not isinstance(index, int) or not 0 <= index < len(g["hands"]):
            raise LeagueError("その局の記録は見つかりません")
        return index

    def edit_hand(self, gid: str, index: int, hand: dict) -> dict:
        """記録した局を直す（ロンの相手を間違えた、点数を打ち間違えた など）。

        その局の親はそのまま。直したのが最後の局なら、次の親も直した結果で決め直す。
        """
        with self.lock:
            g = self._game(gid)
            self._editable(g)
            i = self._hand_index(g, index)
            old = g["hands"][i]
            rec = self._build_hand(g, hand, old["dealer_before"])
            rec["at"] = old.get("at", rec["at"])
            rec["edited"] = int(time.time())
            g["hands"][i] = rec
            self._recount(g)
            if i == len(g["hands"]) - 1 and g["dealer"] == self._next_dealer(g, old):
                g["dealer"] = self._next_dealer(g, rec)
            self._save()
            return g

    def delete_hand(self, gid: str, index: int) -> dict:
        """記録した局を消す（間違えて記録した局など）。"""
        with self.lock:
            g = self._game(gid)
            self._editable(g)
            i = self._hand_index(g, index)
            rec = g["hands"].pop(i)
            self._recount(g)
            if i == len(g["hands"]):  # 最後の局を消したら親も戻す
                g["dealer"] = rec["dealer_before"]
            self._save()
            return g

    def undo_hand(self, gid: str) -> dict:
        with self.lock:
            g = self._game(gid)
            if not g["hands"]:
                raise LeagueError("取り消す局がありません")
            return self.delete_hand(gid, len(g["hands"]) - 1)

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
                self._close_devices(t)  # 大会が終わったらスマホの紐づけも終わり
            self._save()
            return g

    def reopen_game(self, gid: str) -> dict:
        with self.lock:
            g = self._game(gid)
            if not g["finished"]:
                return g
            t = self.data["tournaments"].get(g["tournament"]) if g["tournament"] else None
            if t and t.get("ended_early"):
                raise LeagueError("終了した大会の卓は再開できません")
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
        return {str(n): check_start(sp.get(str(n), sp.get(n, START_POINTS[n]))) for n in (4, 3, 2)}

    @staticmethod
    def _staff_name(name: str | None) -> str:
        """参加しない運営者（オーナー）の名前。プレイヤー登録はしないので、組み分け・成績には入らない。"""
        return " ".join((name or "").split())[:16] or "運営"

    def _sync_owner(self, t: dict) -> None:
        # 参加者のオーナーが参加者から外れたら、運営だけのオーナーとして残す（大会の操作はそのままできる）
        pid = t.get("owner_player")
        if pid and pid not in t["players"]:
            p = self.data["players"].get(pid)
            t["owner_player"] = None
            t["owner_name"] = self._staff_name(p["name"] if p else None)

    def _unique_name(self, name: str | None, exclude: str | None = None) -> str:
        """大会は複数開けるので、名前がかぶったら（2）（3）…を付けて見分けられるようにする。"""
        base = " ".join((name or "").split())[:30] or "はせけん麻雀大会"
        used = {t["name"] for t in self.data["tournaments"].values() if t["id"] != exclude}
        out, i = base, 2
        while out in used:
            out, i = f"{base}（{i}）", i + 1
        return out

    def add_tournament(self, name: str, player_ids: list[str], blocks: int,
                       start_points: dict | None = None, owner_player: str | None = None,
                       owner_name: str | None = None) -> tuple[dict, str]:
        """大会を作る。オーナーは参加者から選ぶ（owner_player）か、参加しない運営者の名前（owner_name）にする。"""
        with self.lock:
            start_points = self._check_start_points(start_points)
            if owner_player:
                self._player(owner_player)
                if owner_player not in player_ids:
                    raise LeagueError("オーナーは参加者から選ぶか、「運営だけ（参加しない）」にしてください")
                owner_name = None
            else:
                owner_name = self._staff_name(owner_name) if owner_name is not None else None
            name = self._unique_name(name)
            if len(set(player_ids)) != len(player_ids):
                raise LeagueError("同じプレイヤーが2回選ばれています")
            for pid in player_ids:
                self._player(pid)
            n = len(player_ids)
            ok = [f["blocks"] for f in formats(n)]
            if not ok:
                raise LeagueError(f"{n}人では大会を組めません。大会は{MIN_PLAYERS}〜{MAX_PLAYERS}人です")
            if blocks not in ok:
                raise LeagueError(f"{n}人では{blocks}ブロックに分けられません")
            key = secrets.token_urlsafe(18)
            tid = _new_id()
            t = {
                "id": tid,
                "name": name,
                "players": list(player_ids),
                "blocks": self._draw(player_ids, blocks),
                "block_games": [],
                "final_game": None,
                "status": "setup",  # setup → blocks → final → done
                "king": None,
                "start_points": start_points,       # 開始前に決める持ち点 {"4": 25000, "3": 35000}
                "owner_player": owner_player or None,  # 参加者のオーナー（🇯🇵の旗を立てる）
                "owner_name": owner_name,              # 参加しない運営だけのオーナーの名前（PC で運営するときなど）
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
        if not isinstance(blocks, list) or not 1 <= len(blocks) <= 4:
            raise LeagueError("ブロックは1〜4つです")
        flat = [pid for b in blocks for pid in b]
        if len(set(flat)) != len(flat):
            raise LeagueError("同じプレイヤーが2つの席に入っています")
        for b in blocks:
            if len(b) not in (2, 3, 4):
                raise LeagueError("1ブロックは2人（二麻）・3人（三麻）・4人（四麻）のどれかです")
        if len(blocks) == 1 and len(flat) > 4:
            raise LeagueError("ブロック分けなしの大会は4人までです")
        for pid in flat:
            self._player(pid)
        return [list(b) for b in blocks]

    def edit_tournament(self, tid: str, key: str | None, name: str | None = None,
                        blocks: list[list[str]] | None = None, start_points: dict | None = None,
                        owner_player: str | None = None, owner_name: str | None = None) -> dict:
        """オーナーが大会を編集する。

        - オーナー：参加者の誰か（owner_player）か、参加しない運営者（owner_player="" と owner_name）

        - 大会名：いつでも変えられる
        - ブロック分け（席順も）：開始前は自由に。開始後は、まだ1局も記録していないブロックだけ
          入れ替え・差し替えができる（来られなくなった人の代わりなど）。決勝が始まったら変えられない
        """
        with self.lock:
            t = self._tour(tid)
            self._owner(t, key)
            if name is not None:
                if " ".join(name.split()):
                    t["name"] = self._unique_name(name, exclude=tid)
            if owner_player:
                self._player(owner_player)
                if owner_player not in t["players"]:
                    raise LeagueError("オーナーは参加者から選ぶか、「運営だけ（参加しない）」にしてください")
                t["owner_player"] = owner_player
                t["owner_name"] = None
            elif owner_player == "" or owner_name is not None:
                if owner_name is None:
                    raise LeagueError("大会ごとにオーナーを決めます。外すのではなく、別の人を選ぶか「運営だけ」にしてください")
                t["owner_player"] = None
                t["owner_name"] = self._staff_name(owner_name)
            if start_points is not None:
                sp = self._check_start_points(start_points)
                changed = sp != {str(n): self.tour_start(t, n) for n in (4, 3, 2)}
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
                self._sync_owner(t)
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
                raise LeagueError(f"{n}人では{blocks}ブロックに分けられません（大会は{MIN_PLAYERS}〜{MAX_PLAYERS}人）")
            t["players"] = list(player_ids)
            self._sync_owner(t)
            t["blocks"] = self._draw(player_ids, blocks)
            self._save()
            return t

    def start_tournament(self, tid: str, key: str | None) -> dict:
        with self.lock:
            t = self._tour(tid)
            self._owner(t, key)
            if t["status"] != "setup":
                raise LeagueError("この大会はもう始まっています")
            if len(t["blocks"]) == 1:
                # 2〜4人の大会：ブロック分けなしで、いきなり決勝（キングを決める1卓）
                members = t["blocks"][0]
                g = self._make_game(members, f"{t['name']} 決勝", tournament=tid, stage="final",
                                    start=self.tour_start(t, len(members)))
                t["final_game"] = g["id"]
                t["status"] = "final"
                self._save()
                return t
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
            out.append(g["ranks"][0] if g["finished"] and g["ranks"] else None)
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

    def _backup(self) -> str:
        """今の中身を league.backup-<時刻>.json に退避する（サーバーで戻せるように）。戻り値はファイル名。"""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.root.mkdir(parents=True, exist_ok=True)
        backup = self.root / f"league.backup-{stamp}.json"
        n = 2
        while backup.exists():  # 同じ秒に2回消しても上書きしない
            backup = self.root / f"league.backup-{stamp}-{n}.json"
            n += 1
        backup.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        return backup.name

    def delete_tournament(self, tid: str, key: str | None, confirmed: bool = False) -> dict:
        """大会をまるごと削除する（オーナーのみ）。

        開始前の大会はそのまま消す。始まった大会（終わった大会も）は confirmed が必要で、
        その大会の卓・局の記録もすべて消す＝各プレイヤーの通算成績・履歴・公開の成績ページからも消える
        （ほかの大会や大会以外の対局の成績は残る。プレイヤー登録も残る）。
        消す前の中身は league.backup-<時刻>.json に退避する。
        """
        with self.lock:
            t = self._tour(tid)
            self._owner(t, key)
            if t["status"] == "setup":
                del self.data["tournaments"][tid]
                self._save()
                return {"games": 0, "backup": None}
            if not confirmed:
                raise LeagueError("始まった大会を削除するには、確認のため「削除」と入力してください")
            backup = self._backup()
            gids = {gid for gid, g in self.data["games"].items() if g.get("tournament") == tid}
            gids |= {gid for gid in [*t["block_games"], t["final_game"]] if gid}
            for gid in gids:
                self.data["games"].pop(gid, None)
            del self.data["tournaments"][tid]
            self._save()
            return {"games": len(gids), "backup": backup}

    def end_tournament(self, tid: str, key: str | None) -> dict:
        """始まった大会を途中で終わらせる（オーナーのみ）。

        記録した局の点数（個人成績）はそのまま残す。終わっていない卓は「打ち切り」にして順位は付けない。
        決勝が終わる前なのでキングはなし。
        """
        with self.lock:
            t = self._tour(tid)
            self._owner(t, key)
            if t["status"] == "setup":
                raise LeagueError("まだ始まっていない大会は「この大会をやめる」で削除できます")
            if t["status"] == "done":
                return t
            for gid in [*t["block_games"], t["final_game"]]:
                g = self.data["games"].get(gid) if gid else None
                if g and not g["finished"]:
                    g["finished"] = True
                    g["ranks"] = None
                    g["aborted"] = True
            t["status"] = "done"
            self._close_devices(t)
            t["ended_early"] = True
            t["ended"] = int(time.time())
            self._save()
            return t

    # ---------- プレイヤーとスマホの紐づけ ----------
    # オーナーがプレイヤーごとに招待（リンク・QR）を作り、本人のスマホで開くと紐づく。
    # 1人につきスマホ1台。大会が終わる（決勝終了・途中終了）か、オーナーが解除するまで続く。
    # サーバーに残すのは合言葉のハッシュと時刻だけ（端末の情報は持たない）。
    @staticmethod
    def _close_devices(t: dict) -> None:
        t["devices"] = {}
        t["invites"] = {}

    def invite_device(self, tid: str, key: str | None, pid: str) -> str:
        with self.lock:
            t = self._tour(tid)
            self._owner(t, key)
            if t["status"] == "done":
                raise LeagueError("終わった大会にはスマホをつなげません")
            if pid not in t["players"]:
                raise LeagueError("その人はこの大会に参加していません")
            token = secrets.token_urlsafe(12)
            t.setdefault("invites", {})[pid] = {"token": _hash(token), "at": int(time.time())}
            self._save()
            return token

    def join_device(self, tid: str, pid: str, token: str) -> str:
        """招待リンクを開いたスマホを、そのプレイヤーとして紐づける（招待は1回だけ使える）。"""
        with self.lock:
            t = self._tour(tid)
            inv = (t.get("invites") or {}).get(pid)
            if t["status"] == "done" or not inv or not token or \
                    not secrets.compare_digest(_hash(token), inv["token"]):
                raise LeagueError("このリンクは使えません（使用済み・解除済み・大会終了のどれかです）。オーナーに新しいリンクをもらってください")
            device_key = secrets.token_urlsafe(18)
            # 前に紐づいていたスマホがあれば、そちらは外れる（1人につき1台）
            t.setdefault("devices", {})[pid] = {"key": _hash(device_key), "since": int(time.time())}
            del t["invites"][pid]
            self._save()
            return device_key

    def device_ok(self, tid: str, pid: str, device_key: str | None) -> bool:
        t = self.data["tournaments"].get(tid)
        d = (t.get("devices") or {}).get(pid) if t else None
        return bool(d and device_key and secrets.compare_digest(_hash(device_key), d["key"]))

    def leave_device(self, tid: str, pid: str, device_key: str | None) -> None:
        """スマホの持ち主が自分で紐づけを外す。"""
        with self.lock:
            if self.device_ok(tid, pid, device_key):
                del self.data["tournaments"][tid]["devices"][pid]
                self._save()

    def unbind_device(self, tid: str, key: str | None, pid: str | None = None) -> dict:
        """オーナーが紐づけを強制的に解除する（pid なしで全員）。招待中のリンクも無効にする。"""
        with self.lock:
            t = self._tour(tid)
            self._owner(t, key)
            if pid is None:
                self._close_devices(t)
            else:
                (t.get("devices") or {}).pop(pid, None)
                (t.get("invites") or {}).pop(pid, None)
            self._save()
            return t

    def _key_ok(self, t: dict, keys: dict) -> bool:
        k = keys.get(t["id"])
        return bool(k) and secrets.compare_digest(_hash(k), t["owner"])

    def reset_blockers(self, keys: dict | None) -> list[str]:
        """リセットに足りないオーナー権限（大会名の一覧）。空ならリセットしてよい。

        大会は複数開けるので、進行中（終了していない）の大会は全部のオーナー権限がいる
        （ほかのオーナーの大会を勝手に消さないため）。全部終わっているときは、どれか1つの大会のオーナーならよい。
        """
        keys = keys or {}
        ts = list(self.data["tournaments"].values())
        active = [t for t in ts if t["status"] != "done"]
        if active:
            return [t["name"] for t in active if not self._key_ok(t, keys)]
        if ts and not any(self._key_ok(t, keys) for t in ts):
            return ["（終わった大会のどれか）"]
        return []

    def reset(self, keys: dict | None, keep_players: bool = False) -> dict:
        """大会・対局・成績（と、keep_players でなければプレイヤー登録）を消して最初に戻す。

        権限は reset_blockers を参照。
        消す前の中身は league.backup-<時刻>.json（写真は avatars.backup-<時刻>/）に退避するので、サーバーで戻せる。
        """
        with self.lock:
            missing = self.reset_blockers(keys)
            if missing:
                raise Forbidden("リセットには、進行中のすべての大会のオーナー権限がいります（足りない大会："
                                + "・".join(missing) + "）。その大会のオーナーに「ほかの端末でもオーナー操作」のリンクをもらうか、大会を終了してもらってください")
            backup = self._backup()
            stamp = backup[len("league.backup-"):-len(".json")]
            players = self.data["players"] if keep_players else {}
            if not keep_players and self.avatar_dir.exists() and any(self.avatar_dir.iterdir()):
                os.replace(self.avatar_dir, self.root / f"avatars.backup-{stamp}")
            self.data = {"players": players, "games": {}, "tournaments": {}}
            self._save()
            return {"backup": backup, "players": len(players)}

    # ---------- 集計 ----------
    def stats(self, games: list[dict] | None = None, pids=None) -> dict[str, dict]:
        """個人成績（対局中の局も含めて随時集計）。

        games を渡すとその対局だけ（大会ごとの成績表など）、省略すると全部の対局（通算）を数える。
        """
        whole = games is None
        out = {pid: {"plus": 0, "minus": 0, "net": 0, "hands": 0, "wins": 0, "deal_ins": 0,
                     "games": 0, "finished": 0, "tops": 0, "rank_sum": 0, "kings": 0}
               for pid in (self.data["players"] if pids is None else pids)}
        for g in (self.data["games"].values() if whole else games):
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
        for t in self.data["tournaments"].values() if whole else ():
            if t.get("king") in out:
                out[t["king"]]["kings"] += 1
        for s in out.values():
            s["net"] = s["plus"] + s["minus"]
            s["avg_rank"] = round(s["rank_sum"] / s["finished"], 2) if s["finished"] else None
            del s["rank_sum"]
        return out

    def _tour_games(self, t: dict) -> list[dict]:
        gids = [*t["block_games"], t["final_game"]]
        return [self.data["games"][gid] for gid in gids if gid and gid in self.data["games"]]

    def tour_result(self, t: dict, pid: str) -> str:
        """その大会でのプレイヤーの結果（キング・決勝○位・Aブロック○位など）。"""
        if t.get("king") == pid:
            return "👑 キング"
        final = self.data["games"].get(t["final_game"]) if t["final_game"] else None
        single = len(t["blocks"]) == 1
        if final and pid in final["players"]:
            if final.get("aborted"):
                return "決勝（打ち切り）"
            if final["finished"] and final["ranks"]:
                return f"決勝{final['ranks'].index(pid) + 1}位"
            return "決勝 対局中"
        for i, members in enumerate(t["blocks"]):
            if pid not in members:
                continue
            label = "決勝" if single else f"{chr(65 + i)}ブロック"
            g = self.data["games"].get(t["block_games"][i]) if i < len(t["block_games"]) else None
            if not g:
                return "開始前" if t["status"] == "setup" else label
            if g.get("aborted"):
                return f"{label}（打ち切り）"
            if g["finished"] and g["ranks"]:
                return f"{label}{g['ranks'].index(pid) + 1}位"
            return f"{label} 対局中"
        return "—"

    def tour_standings(self, t: dict) -> list[dict]:
        """大会ごとの成績表。その大会の対局だけを数えるので、新しい大会は0から始まる。"""
        st = self.stats(self._tour_games(t), t["players"])
        rows = [{"id": pid, **st[pid], "result": self.tour_result(t, pid)} for pid in t["players"]]
        final = self.data["games"].get(t["final_game"]) if t["final_game"] else None
        block_rank = {}
        for gid in t["block_games"]:
            g = self.data["games"].get(gid)
            if g and g["finished"] and g["ranks"]:
                block_rank.update({pid: i for i, pid in enumerate(g["ranks"])})

        def order(r):
            # キング → 決勝の順位 → ブロックの順位 → 合計点
            pid = r["id"]
            if t.get("king") == pid:
                return (0, 0, -r["net"])
            if final and pid in final["players"]:
                rk = final["ranks"].index(pid) if final["finished"] and final["ranks"] else 9
                return (1, rk, -r["net"])
            return (2, block_rank.get(pid, 9), -r["net"])
        rows.sort(key=order)
        return rows

    def player_history(self, pid: str) -> dict:
        """プレイヤーの成績：通算・大会ごとの履歴・大会以外の対局。大会が終わったあとも見られる。"""
        with self.lock:
            p = self._player(pid)
            tours = []
            for t in sorted(self.data["tournaments"].values(), key=lambda t: -t["created"]):
                if pid not in t["players"]:
                    continue
                st = self.stats(self._tour_games(t), [pid])[pid]
                tours.append({"id": t["id"], "name": t["name"], "status": t["status"],
                              "ended_early": bool(t.get("ended_early")), "created": t["created"],
                              "players": len(t["players"]), "result": self.tour_result(t, pid), "stats": st})
            free = [g for g in self.data["games"].values() if not g["tournament"]]
            return {"id": pid, "name": p["name"], "stats": self.stats()[pid], "tournaments": tours,
                    "free": self.stats(free, [pid])[pid]}

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
                d = {k: v for k, v in t.items() if k not in ("owner", "devices", "invites")}  # 合言葉（ハッシュ）は出さない
                d["devices"] = {pid: {"since": x["since"]} for pid, x in (t.get("devices") or {}).items()}
                d["invites"] = sorted((t.get("invites") or {}).keys())
                d["winners"] = self.block_winners(t)
                d["formats"] = formats(len(t["players"]))
                d["standings"] = self.tour_standings(t)
                tours.append(d)
            tours.sort(key=lambda t: -t["created"])
            return {"players": players, "games": games, "tournaments": tours, "start_points": START_POINTS,
                    "formats": {n: formats(n) for n in range(MIN_PLAYERS, MAX_PLAYERS + 1)},
                    "nima_yakuman": NIMA_YAKUMAN}
