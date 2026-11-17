"""公開の成績ページ（/seiseki/）と、大会記録の Markdown ダウンロード。

ログインなしで誰でも見られる閲覧専用のページ。JavaScript を使わずサーバーで HTML を作る。
出すのは名前・アバター・点数・結果だけ。オーナーの合言葉・スマホの紐づけ・操作ボタンは出さない。
"""
from __future__ import annotations

from html import escape
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from .league_api import store
from .logic import league_report as R
from .logic.league import LeagueError

router = APIRouter()


def _md_response(fname: str, text: str, ascii_name: str) -> Response:
    # 日本語のファイル名は RFC 5987 の書き方（filename*）で渡す。読めないブラウザ向けに ASCII の名前も付ける
    disp = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(fname)}"
    return Response(text, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": disp, "Cache-Control": "no-store"})


@router.get("/api/league/tournaments/{tid}/export.md")
async def export_tournament(tid: str) -> Response:
    try:
        fname, text = await run_in_threadpool(R.tournament_markdown, store, tid)
    except LeagueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _md_response(fname, text, f"taikai_{fname[:8]}_{tid}.md")


@router.get("/api/league/export.md")
async def export_all() -> Response:
    fname, text = await run_in_threadpool(R.ranking_markdown, store)
    return _md_response(fname, text, f"seiseki_{fname[:8]}.md")


# ---------- 公開ページ ----------
CSS = """
:root{--bg:#f4f1ea;--card:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e2ddd2;--accent:#c8102e;--good:#17744a;--head:#134d32}
@media (prefers-color-scheme:dark){:root{--bg:#141614;--card:#1e221f;--ink:#ecebe6;--muted:#a3a39b;--line:#333a35;--accent:#ff6b7d;--good:#5fd19a;--head:#0e2c1e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif;line-height:1.5}
header{background:var(--head);color:#fff;padding:12px 16px;display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}
header h1{margin:0;font-size:1.15rem}header a{color:#fff}
main{max-width:960px;margin:0 auto;padding:12px 16px 32px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin:12px 0}
h2{margin:0 0 6px;font-size:1.1rem}h2 small,h3 small{color:var(--muted);font-weight:400;font-size:.8rem;margin-left:6px}h3{margin:14px 0 6px;font-size:.98rem}
.meta{color:var(--muted);font-size:.85rem;margin:2px 0}
.king{font-size:1.05rem;font-weight:700;margin:8px 0}
.wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:.88rem;font-variant-numeric:tabular-nums}
th,td{padding:6px 6px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th{color:var(--muted);font-size:.75rem;font-weight:600}
td.l,th.l{text-align:left}td.w{white-space:normal;text-align:left}
.who{display:inline-flex;align-items:center;gap:6px}.av{width:26px;height:26px;border-radius:50%;object-fit:cover;background:var(--bg);display:inline-flex;align-items:center;justify-content:center;font-size:.95rem}
.plus{color:var(--good)}.minus{color:var(--accent)}
.tag{display:inline-block;font-size:.72rem;padding:1px 8px;border-radius:999px;background:var(--bg);color:var(--muted);margin-left:6px}
.list a{display:flex;justify-content:space-between;gap:8px;padding:10px 0;border-bottom:1px solid var(--line);color:inherit;text-decoration:none}
.btn{display:inline-block;padding:6px 12px;border:1px solid var(--line);border-radius:10px;color:inherit;text-decoration:none;font-size:.85rem;background:var(--card)}
.grid{display:grid;gap:12px}.grid>*{min-width:0}h2 a{color:inherit}@media(min-width:760px){.grid{grid-template-columns:1fr 1fr}}
footer{color:var(--muted);font-size:.78rem;text-align:center;padding:16px}
"""


def _page(title: str, body: str, refresh: bool = True) -> HTMLResponse:
    meta = '<meta http-equiv="refresh" content="30">' if refresh else ""
    html = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">{meta}
<title>{escape(title)}</title><style>{CSS}</style></head><body>
<header><h1>🀄 {escape(title)}</h1><a href="/seiseki/">成績トップ</a></header>
<main>{body}</main>
<footer>はせけん麻雀大会の成績（閲覧専用・30秒ごとに自動で更新）。勝ち点＝受け取った点、マイナス＝払った点。</footer>
</body></html>"""
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def _who(pid: str | None) -> str:
    p = store.data["players"].get(pid or "")
    if not p:
        return "（削除）"
    av = (f'<img class="av" src="/api/league/avatars/{escape(p["photo"])}" alt="">' if p.get("photo")
          else f'<span class="av">{escape(p.get("emoji") or "🀄")}</span>')
    return f'<span class="who">{av}{escape(p["name"])}</span>'


def _n(v: int, sign: bool = False) -> str:
    cls = "plus" if v > 0 else "minus" if v < 0 else ""
    return f'<span class="{cls}">{R.signed(v) if sign else f"{v:,}"}</span>'


def _standings(t: dict) -> str:
    rows = "".join(
        f"<tr><td>{i + 1}</td><td class=l>{_who(r['id'])}</td><td class=l>{escape(r['result'])}</td>"
        f"<td>{_n(r['net'], True)}</td><td>{r['plus']:,}</td><td>{_n(r['minus'])}</td></tr>"
        for i, r in enumerate(store.tour_standings(t)))
    return ('<div class="wrap"><table><thead><tr><th>#</th><th class=l>プレイヤー</th><th class=l>結果</th>'
            f'<th>合計</th><th>勝ち点</th><th>マイナス</th></tr></thead><tbody>{rows}</tbody></table></div>')


def _tour_head(t: dict, link: bool) -> str:
    name = escape(t["name"])
    title = f'<a href="/seiseki/{escape(t["id"])}">{name}</a>' if link else name
    king = f'<div class="king">👑 キング：{_who(t["king"])}</div>' if t.get("king") else ""
    return (f'<h2>{title}<small>{escape(R.tour_status(t))}</small></h2>'
            f'<p class="meta">{escape(R.when(t.get("created"), "%Y/%m/%d"))}・{len(t["players"])}人・'
            f'オーナー：{escape(R.owner_label(store, t))}</p>{king}')


def index_html() -> HTMLResponse:
    with store.lock:
        ts = sorted(store.data["tournaments"].values(), key=lambda t: -t["created"])
        active = [t for t in ts if t["status"] != "done"]
        done = [t for t in ts if t["status"] == "done"]
        body = ""
        if active:
            body += "<h3>開催中の大会</h3><div class=grid>" + "".join(
                f'<section class=card>{_tour_head(t, True)}{_standings(t)}'
                f'<p><a class=btn href="/seiseki/{escape(t["id"])}">卓ごとの点数・記録を見る</a></p></section>' for t in active) + "</div>"
        if done:
            items = "".join(
                f'<a href="/seiseki/{escape(t["id"])}"><span><b>{escape(t["name"])}</b><span class=tag>{escape(R.tour_status(t))}</span>'
                f'<br><span class=meta>{escape(R.when(t["created"], "%Y/%m/%d"))}・{len(t["players"])}人</span></span>'
                f'<span>{"👑 " + _who(t["king"]) if t.get("king") else "キングなし"}</span></a>' for t in done)
            body += f'<section class=card><h2>終わった大会<small>{len(done)}件</small></h2><div class=list>{items}</div></section>'
        if not ts:
            body += '<section class=card><p class=meta>まだ大会はありません。</p></section>'
        st = store.stats()
        ps = sorted(store.data["players"].values(), key=lambda p: (-st[p["id"]]["net"], p["name"]))
        rows = "".join(
            f"<tr><td>{i + 1}</td><td class=l>{_who(p['id'])}{' ' + '👑' * min(3, st[p['id']]['kings']) if st[p['id']]['kings'] else ''}</td>"
            f"<td>{_n(st[p['id']]['net'], True)}</td><td>{st[p['id']]['plus']:,}</td><td>{_n(st[p['id']]['minus'])}</td>"
            f"<td>{st[p['id']]['games']}</td><td>{st[p['id']]['tops']}</td>"
            f"<td>{'—' if st[p['id']]['avg_rank'] is None else format(st[p['id']]['avg_rank'], '.2f')}</td></tr>"
            for i, p in enumerate(ps))
        body += ('<section class=card><h2>通算成績<small>大会が終わっても残ります</small></h2><div class=wrap><table><thead><tr>'
                 '<th>#</th><th class=l>プレイヤー</th><th>合計</th><th>勝ち点</th><th>マイナス</th><th>対局</th><th>トップ</th><th>平均順位</th>'
                 f'</tr></thead><tbody>{rows or "<tr><td colspan=8 class=l>まだプレイヤーがいません</td></tr>"}</tbody></table></div>'
                 '<p><a class=btn href="/api/league/export.md">通算成績を Markdown で保存</a></p></section>')
    return _page("はせけん麻雀大会 成績", body)


def tour_html(tid: str) -> HTMLResponse:
    with store.lock:
        t = store.data["tournaments"].get(tid)
        if not t:
            raise HTTPException(status_code=404, detail="その大会は見つかりません")
        body = f'<section class=card>{_tour_head(t, False)}<h3>大会の成績</h3>{_standings(t)}' \
               f'<p><a class=btn href="/api/league/tournaments/{escape(tid)}/export.md">この大会の記録を Markdown で保存</a></p></section>'
        for label, g in R.tour_games(store, t):
            n = len(g["players"])
            order = store.ranking(g)
            rows = "".join(f"<tr><td>{r + 1}</td><td class=l>{R.SEATS[g['players'].index(pid)]}</td><td class=l>{_who(pid)}</td>"
                           f"<td>{g['points'][pid]:,}</td></tr>" for r, pid in enumerate(order))
            hands = "".join(
                f"<tr><td>{k + 1}</td><td class=w>{escape(R.hand_text(store, g, h))}</td><td class=w>"
                + "、".join(f"{escape((store.data['players'].get(pid) or {}).get('name', '（削除）'))} {_n(d, True)}" for pid, d in h["deltas"].items() if d)
                + "</td></tr>" for k, h in enumerate(g["hands"]))
            log = (f'<h3>記録<small>{len(g["hands"])}局</small></h3><div class=wrap><table><thead><tr><th>局</th><th class=l>内容</th>'
                   f'<th class=l>点数の動き</th></tr></thead><tbody>{hands}</tbody></table></div>') if hands else ""
            body += (f'<section class=card><h2>{escape(label)}<small>{R.KIND.get(n, "")}・{escape(R.game_state(g))}</small></h2>'
                     f'<div class=wrap><table><thead><tr><th>順位</th><th class=l>席</th><th class=l>プレイヤー</th><th>持ち点</th></tr></thead>'
                     f'<tbody>{rows}</tbody></table></div>{log}</section>')
    return _page(t["name"], body, refresh=t["status"] != "done")


@router.get("/seiseki")
async def seiseki_redirect() -> RedirectResponse:
    return RedirectResponse("/seiseki/")


@router.get("/seiseki/", response_class=HTMLResponse)
async def seiseki_index() -> HTMLResponse:
    return await run_in_threadpool(index_html)


@router.get("/seiseki/{tid}", response_class=HTMLResponse)
async def seiseki_tour(tid: str) -> HTMLResponse:
    return await run_in_threadpool(tour_html, tid)
