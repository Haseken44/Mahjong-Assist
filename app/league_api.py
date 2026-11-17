"""はせけん麻雀大会・個人成績の API（/api/league/...）と画面（/taikai）。

ここで扱うのは名前・アバター・点数だけで、手牌や映像は扱わない。
大会の抽選・開始・決勝は、大会を作った端末（オーナー）だけが X-Owner-Key で操作できる。
"""
from __future__ import annotations

import base64
import binascii
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .logic.league import Forbidden, LeagueError, LeagueStore

STATIC = Path(__file__).parent / "static"
MAX_PHOTO_BYTES = 3 * 1024 * 1024

router = APIRouter()
store = LeagueStore()


def _err(e: LeagueError) -> HTTPException:
    return HTTPException(status_code=403 if isinstance(e, Forbidden) else 400, detail=str(e))


def _photo(data: str | None) -> bytes | None:
    """data:image/jpeg;base64,... または base64 文字列を画像のバイト列にする。"""
    if not data:
        return None
    if "," in data[:100]:
        data = data.split(",", 1)[1]
    if len(data) > MAX_PHOTO_BYTES * 4 // 3 + 4:
        raise HTTPException(status_code=400, detail="写真が大きすぎます")
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="写真を読み込めませんでした") from None


async def _run(fn, *args, **kwargs):
    try:
        return await run_in_threadpool(fn, *args, **kwargs)
    except LeagueError as e:
        raise _err(e) from e


@router.get("/taikai")
async def taikai_page() -> FileResponse:
    return FileResponse(STATIC / "league.html", headers={"Cache-Control": "no-cache"})


@router.get("/api/league")
async def league_state() -> dict:
    return await run_in_threadpool(store.snapshot)


@router.get("/api/league/avatars/{name}")
async def avatar(name: str) -> FileResponse:
    path = store.avatar_path(name)
    if path is None:
        raise HTTPException(status_code=404, detail="ありません")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})


class PlayerIn(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    emoji: str | None = Field(default=None, max_length=16)
    photo: str | None = None  # data URL
    remove_photo: bool = False


@router.post("/api/league/players")
async def add_player(req: PlayerIn) -> dict:
    return await _run(store.add_player, req.name or "", req.emoji, _photo(req.photo))


@router.put("/api/league/players/{pid}")
async def update_player(pid: str, req: PlayerIn) -> dict:
    return await _run(store.update_player, pid, req.name, req.emoji, _photo(req.photo), req.remove_photo)


@router.get("/api/league/players/{pid}/history")
async def player_history(pid: str) -> dict:
    return await _run(store.player_history, pid)


@router.delete("/api/league/players/{pid}")
async def delete_player(pid: str) -> dict:
    await _run(store.delete_player, pid)
    return {"ok": True}


class GameIn(BaseModel):
    players: list[str] = Field(min_length=2, max_length=4)
    title: str = Field(default="", max_length=60)
    start: int | None = None  # 持ち点（省略で四麻25000・三麻35000）


@router.post("/api/league/games")
async def add_game(req: GameIn) -> dict:
    return await _run(store.add_game, req.players, req.title, True, req.start)


class StartIn(BaseModel):
    start: int


@router.post("/api/league/games/{gid}/start")
async def set_game_start(gid: str, req: StartIn, x_owner_key: str | None = Header(default=None)) -> dict:
    return await _run(store.set_game_start, gid, req.start, x_owner_key)


@router.delete("/api/league/games/{gid}")
async def delete_game(gid: str) -> dict:
    await _run(store.delete_game, gid)
    return {"ok": True}


class HandIn(BaseModel):
    kind: str
    winner: str | None = None
    loser: str | None = None
    points: int | None = None
    pay_child: int | None = None
    pay_dealer: int | None = None
    riichi: list[str] = Field(default_factory=list, max_length=4)
    deltas: dict[str, int] = Field(default_factory=dict)
    note: str = Field(default="", max_length=80)


@router.post("/api/league/games/{gid}/hands")
async def add_hand(gid: str, req: HandIn) -> dict:
    return await _run(store.add_hand, gid, req.model_dump())


@router.delete("/api/league/games/{gid}/hands/last")
async def undo_hand(gid: str) -> dict:
    return await _run(store.undo_hand, gid)


@router.put("/api/league/games/{gid}/hands/{index}")
async def edit_hand(gid: str, index: int, req: HandIn) -> dict:
    return await _run(store.edit_hand, gid, index, req.model_dump())


@router.delete("/api/league/games/{gid}/hands/{index}")
async def delete_hand(gid: str, index: int) -> dict:
    return await _run(store.delete_hand, gid, index)


class DealerIn(BaseModel):
    seat: int


@router.post("/api/league/games/{gid}/dealer")
async def set_dealer(gid: str, req: DealerIn) -> dict:
    return await _run(store.set_dealer, gid, req.seat)


@router.post("/api/league/games/{gid}/finish")
async def finish_game(gid: str) -> dict:
    return await _run(store.finish_game, gid)


@router.post("/api/league/games/{gid}/reopen")
async def reopen_game(gid: str) -> dict:
    return await _run(store.reopen_game, gid)


class TournamentIn(BaseModel):
    name: str = Field(default="はせけん麻雀大会", max_length=60)
    players: list[str] = Field(max_length=32)
    blocks: int
    start_points: dict[str, int] | None = None  # {"4": 25000, "3": 35000}
    # 大会ごとに必ずオーナーを決める：参加者から選ぶか、参加しない運営者の名前（PC で運営するときなど）
    owner_player: str | None = Field(default=None, max_length=40)
    owner_name: str | None = Field(default=None, max_length=16)


def _public(t: dict) -> dict:
    out = {k: v for k, v in t.items() if k not in ("owner", "devices", "invites")}
    out["devices"] = {pid: {"since": x["since"]} for pid, x in (t.get("devices") or {}).items()}
    out["invites"] = sorted((t.get("invites") or {}).keys())
    return out


@router.post("/api/league/tournaments")
async def add_tournament(req: TournamentIn) -> dict:
    if not req.owner_player and not (req.owner_name or "").strip():
        raise HTTPException(status_code=422, detail="オーナーを参加者から選ぶか、「運営だけ（参加しない）」にして名前を入れてください")
    t, key = await _run(store.add_tournament, req.name, req.players, req.blocks,
                        req.start_points, req.owner_player, req.owner_name if not req.owner_player else None)
    # 合言葉はこの1回だけ返す。オーナーの端末が保存しておき、以後の操作で X-Owner-Key に付ける
    return {"tournament": _public(t), "owner_key": key}


@router.post("/api/league/tournaments/{tid}/draw")
async def redraw(tid: str, x_owner_key: str | None = Header(default=None)) -> dict:
    return _public(await _run(store.redraw, tid, x_owner_key))


@router.post("/api/league/tournaments/{tid}/start")
async def start_tournament(tid: str, x_owner_key: str | None = Header(default=None)) -> dict:
    return _public(await _run(store.start_tournament, tid, x_owner_key))


@router.post("/api/league/tournaments/{tid}/final")
async def start_final(tid: str, x_owner_key: str | None = Header(default=None)) -> dict:
    return _public(await _run(store.start_final, tid, x_owner_key))


class TournamentEdit(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    blocks: list[list[str]] | None = Field(default=None, max_length=4)
    start_points: dict[str, int] | None = None
    owner_player: str | None = None  # オーナーを別の参加者に変える。"" と owner_name で参加しない運営者に
    owner_name: str | None = Field(default=None, max_length=16)


@router.patch("/api/league/tournaments/{tid}")
async def edit_tournament(tid: str, req: TournamentEdit, x_owner_key: str | None = Header(default=None)) -> dict:
    return _public(await _run(store.edit_tournament, tid, x_owner_key, req.name, req.blocks,
                           req.start_points, req.owner_player, req.owner_name))


class EntriesIn(BaseModel):
    players: list[str] = Field(max_length=32)
    blocks: int


@router.post("/api/league/tournaments/{tid}/entries")
async def change_entries(tid: str, req: EntriesIn, x_owner_key: str | None = Header(default=None)) -> dict:
    return _public(await _run(store.change_entries, tid, x_owner_key, req.players, req.blocks))


@router.delete("/api/league/tournaments/{tid}")
async def delete_tournament(tid: str, x_owner_key: str | None = Header(default=None)) -> dict:
    """開始前の大会を消す（始まった大会は下の /delete で確認つき）。"""
    return {"ok": True, **await _run(store.delete_tournament, tid, x_owner_key)}


class DeleteTourIn(BaseModel):
    confirm: str  # 誤操作よけ：「削除」と入力してもらう


@router.post("/api/league/tournaments/{tid}/delete")
async def delete_tournament_all(tid: str, req: DeleteTourIn, x_owner_key: str | None = Header(default=None)) -> dict:
    """大会をまるごと削除する（その大会の対局と、個人成績に入っていたその大会の点数も消える）。"""
    if req.confirm.strip() != "削除":
        raise HTTPException(status_code=400, detail="確認のため「削除」と入力してください")
    return {"ok": True, **await _run(store.delete_tournament, tid, x_owner_key, True)}


@router.post("/api/league/tournaments/{tid}/end")
async def end_tournament(tid: str, x_owner_key: str | None = Header(default=None)) -> dict:
    return _public(await _run(store.end_tournament, tid, x_owner_key))


class ResetIn(BaseModel):
    confirm: str  # 誤操作よけ：「リセット」と入力してもらう
    keep_players: bool = False
    owner_keys: dict[str, str] = Field(default_factory=dict, max_length=200)  # {大会ID: 合言葉}（この端末が持っている分）


@router.post("/api/league/reset")
async def reset(req: ResetIn) -> dict:
    if req.confirm.strip() != "リセット":
        raise HTTPException(status_code=400, detail="確認のため「リセット」と入力してください")
    return await _run(store.reset, req.owner_keys, req.keep_players)


# ---------- プレイヤーとスマホの紐づけ ----------
class PidIn(BaseModel):
    player: str = Field(min_length=1, max_length=40)


@router.post("/api/league/tournaments/{tid}/invite")
async def invite_device(tid: str, req: PidIn, x_owner_key: str | None = Header(default=None)) -> dict:
    token = await _run(store.invite_device, tid, x_owner_key, req.player)
    return {"token": token}


class JoinIn(BaseModel):
    player: str = Field(min_length=1, max_length=40)
    token: str = Field(min_length=1, max_length=64)


@router.post("/api/league/tournaments/{tid}/join")
async def join_device(tid: str, req: JoinIn) -> dict:
    # 端末の合言葉はこの1回だけ返す。スマホが保存しておき、自分の確認に使う
    return {"device_key": await _run(store.join_device, tid, req.player, req.token)}


class DeviceIn(BaseModel):
    player: str = Field(min_length=1, max_length=40)
    device_key: str = Field(default="", max_length=64)


@router.post("/api/league/tournaments/{tid}/whoami")
async def whoami(tid: str, req: DeviceIn) -> dict:
    return {"ok": await run_in_threadpool(store.device_ok, tid, req.player, req.device_key)}


@router.post("/api/league/tournaments/{tid}/leave")
async def leave_device(tid: str, req: DeviceIn) -> dict:
    await _run(store.leave_device, tid, req.player, req.device_key)
    return {"ok": True}


class UnbindIn(BaseModel):
    player: str | None = None  # 省略で全員


@router.post("/api/league/tournaments/{tid}/unbind")
async def unbind_device(tid: str, req: UnbindIn, x_owner_key: str | None = Header(default=None)) -> dict:
    return _public(await _run(store.unbind_device, tid, x_owner_key, req.player))


@router.get("/api/league/qr")
async def qr(text: str = Query(min_length=1, max_length=400)) -> Response:
    """招待リンクの QR コード（SVG）。外部サービスは使わずサーバーで作る。"""
    import io

    import segno

    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="svg", scale=6, border=2, dark="#111", light="#fff")
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})
