"use strict";
// はせけん麻雀大会・個人成績（Vanilla JS）
// 名前・アバター・点数だけを扱う。手牌やカメラ映像はこの画面では一切使わない。

const $ = (id) => document.getElementById(id);
const SEATS = ["東", "南", "西", "北"];
const KIND = { 4: "四麻", 3: "三麻", 2: "二麻" };
const KIND_LONG = { 4: "四麻（4人卓）", 3: "三麻（3人卓）", 2: "二麻（2人卓・役満のみ）" };
const DEFAULT_START = { 4: 25000, 3: 35000, 2: 25000 };
const EMOJIS = ["🀄", "🐉", "🐯", "🐼", "🦊", "🐸", "🐙", "🦁", "🐧", "🐱", "🐶", "🦉", "🐻", "🐰", "🐵", "🐨",
  "🌸", "⭐", "🔥", "⚡", "🍀", "🍣", "🍺", "🎯"];
const POLL_MS = 4000;

const ui = {
  data: { players: [], games: [], tournaments: [] },
  tab: load("mj-league-tab", "tour"),
  game: load("mj-league-game", null),     // 開いている対局
  tourPick: new Set(),                      // 大会の参加者
  tourBlocks: null,                         // 選んだブロック数
  newPick: [],                              // 新しい対局の席順
  showSetup: false,                         // 大会が終わったあと「新しい大会」を押した
  formKey: null,                            // 入力欄を作り直すかの目印
  winner: null,                             // この局でアガった人
  loser: null,                              // ロンで振り込んだ人（必ず選ぶ）
  editHand: null,                           // 直している局の番号（0から）。null は新しく記録
  reg: null,                                // 登録ダイアログの状態
  edit: null,                               // オーナーが編集中の大会 {tid, name, blocks, sel, entries, pick, nb}
};

// ---------- 小物 ----------
function load(key, def) {
  try { const v = localStorage.getItem(key); return v == null ? def : JSON.parse(v); } catch (_) { return def; }
}
function save(key, v) {
  try { localStorage.setItem(key, JSON.stringify(v)); } catch (_) { /* 保存できなくても動く */ }
}
function ownerKeys() { return load("mj-owner-keys", {}); }
function ownerKey(tid) { return ownerKeys()[tid] || null; }
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
function fmt(n) { return (n > 0 ? "+" : "") + n.toLocaleString("ja-JP"); }
function pts(n) { return n.toLocaleString("ja-JP"); }
function flash(msg, isError = true) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (isError ? " err" : "");
  clearTimeout(flash.t);
  flash.t = setTimeout(() => (t.className = "toast"), 3500);
}
async function api(method, path, body, headers = {}) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", ...headers },
    body: body == null ? undefined : JSON.stringify(body),
  });
  let json = null;
  try { json = await res.json(); } catch (_) { /* noop */ }
  if (!res.ok) {
    const d = json && json.detail;
    throw new Error(typeof d === "string" ? d : "うまくいきませんでした。通信を確認してもう一度");
  }
  return json;
}
function player(pid) { return ui.data.players.find((p) => p.id === pid) || { id: pid, name: "（削除）", emoji: "？", stats: {} }; }
function game(gid) { return ui.data.games.find((g) => g.id === gid); }
function avatarEl(p, size = "") {
  const a = el("span", "avatar " + size);
  if (p.avatar) {
    const img = document.createElement("img");
    img.src = p.avatar;
    img.alt = "";
    img.loading = "lazy";
    a.append(img);
  } else {
    a.textContent = p.emoji || "🀄";
  }
  return a;
}
function whoEl(pid, size = "") {
  const p = player(pid);
  const w = el("span", "who");
  w.append(avatarEl(p, size), el("span", "name", p.name));
  if (ownerFlags().has(pid)) {
    const f = el("span", "flag", "🇯🇵");
    f.title = "大会のオーナー";
    w.append(f);
  }
  return w;
}
// 大会のオーナーのプレイヤー（名前の横に日本の旗を立てる）
function ownerFlags() {
  const ts = ui.data.tournaments;
  const shown = ts.filter((t) => t.status !== "done");
  if (ts[0] && !shown.includes(ts[0])) shown.push(ts[0]);
  return new Set(shown.map((t) => t.owner_player).filter(Boolean));
}
function startInput(id) {
  const v = $(id).value.trim();
  return v === "" ? null : parseInt(v, 10);
}
function ownerOptions(select, value) {
  options(select, [["", "（選ばない）"], ...ui.data.players.slice().sort((a, b) => a.name.localeCompare(b.name, "ja")).map((p) => [p.id, p.name])], false);
  select.value = value || "";
}
function seatName(g, i) {
  const n = g.players.length;
  return SEATS[(i - g.dealer + n) % n];
}

// ---------- 読み込み ----------
async function refresh() {
  try {
    ui.data = await api("GET", "/api/league");
  } catch (e) {
    flash(e.message);
    return;
  }
  render();
}
function render() {
  renderTabs();
  renderTour();
  renderGames();
  renderRank();
  renderPlayers();
}

// ---------- タブ ----------
function renderTabs() {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === ui.tab));
  document.querySelectorAll(".tab").forEach((s) => (s.hidden = s.id !== "tab-" + ui.tab));
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
  ui.tab = b.dataset.tab;
  save("mj-league-tab", ui.tab);
  renderTabs();
  window.scrollTo({ top: 0 });
}));

// ---------- 参加者を選ぶボタン ----------
function pickButtons(container, isOn, orderOf, onToggle) {
  container.replaceChildren();
  if (!ui.data.players.length) {
    container.append(el("p", "tip", "まだプレイヤーがいません。「＋プレイヤー登録」から名前とアバターを登録してください。"));
    return;
  }
  ui.data.players.slice().sort((a, b) => a.name.localeCompare(b.name, "ja")).forEach((p) => {
    const b = el("button");
    b.type = "button";
    b.setAttribute("aria-pressed", isOn(p.id));
    b.append(avatarEl(p), el("span", "name", p.name));
    const o = orderOf ? orderOf(p.id) : null;
    if (o) b.append(el("span", "order", o));
    b.addEventListener("click", () => onToggle(p.id));
    container.append(b);
  });
}

// ---------- 大会 ----------
function formats(n) {
  // 組み方はサーバー（app/logic/league.py の formats）が決める。おすすめ順に並んでいる
  return (ui.data.formats && ui.data.formats[n]) || [];
}

function renderTour() {
  // 進行中の大会はすべて表示。なければ最後に終わった大会（キング）と「新しい大会」
  const ts = ui.data.tournaments;
  const active = ts.filter((t) => t.status !== "done");
  const last = ts.find((t) => t.status === "done") || null;
  const showSetup = !active.length && (!last || ui.showSetup);
  $("tourSetup").hidden = !showSetup;
  const view = $("tourView");
  view.replaceChildren();
  if (last && !showSetup) view.append(tourCard(last));
  active.forEach((t) => view.append(tourCard(t)));
  if (showSetup) renderSetup();
}

function renderSetup() {
  if (!$("tourOwner").matches(":focus")) ownerOptions($("tourOwner"), $("tourOwner").value || load("mj-owner-player", ""));
  // 消えたプレイヤーは外す
  [...ui.tourPick].forEach((pid) => { if (!ui.data.players.some((p) => p.id === pid)) ui.tourPick.delete(pid); });
  pickButtons($("tourPick"), (pid) => ui.tourPick.has(pid), null, (pid) => {
    if (ui.tourPick.has(pid)) ui.tourPick.delete(pid); else ui.tourPick.add(pid);
    renderSetup();
  });
  const n = ui.tourPick.size;
  $("tourCount").textContent = `${n}人`;
  const fs = formats(n);
  if (!fs.some((f) => f.blocks === ui.tourBlocks)) ui.tourBlocks = fs.length ? fs[0].blocks : null;
  const box = $("tourFormats");
  box.replaceChildren();
  if (!fs.length) {
    box.append(el("p", "none", n < 9
      ? `大会は2〜16人で組めます（いま${n}人）。2〜4人なら1卓でそのままキングを決め、5人以上はブロックに分けて各ブロックのトップで決勝をします。`
      : `${n}人だと3〜4ブロックに分けられません（16人まで）。`));
  }
  fs.forEach((f) => {
    const l = el("label");
    const r = document.createElement("input");
    r.type = "radio";
    r.name = "tourFormat";
    r.checked = f.blocks === ui.tourBlocks;
    r.addEventListener("change", () => { ui.tourBlocks = f.blocks; });
    l.append(r, el("span", null, f.label));
    box.append(l);
  });
  $("tourCreate").disabled = !fs.length;
}

$("tourCreate").addEventListener("click", async () => {
  try {
    const r = await api("POST", "/api/league/tournaments", {
      name: $("tourName").value, players: [...ui.tourPick], blocks: ui.tourBlocks,
      owner_player: $("tourOwner").value || null,
      start_points: { 4: startInput("tourStart4") ?? 25000, 3: startInput("tourStart3") ?? 35000, 2: startInput("tourStart2") ?? 25000 },
    });
    save("mj-owner-player", $("tourOwner").value);
    const keys = ownerKeys();
    keys[r.tournament.id] = r.owner_key;  // このスマホがオーナー
    save("mj-owner-keys", keys);
    ui.showSetup = false;
    ui.tourPick.clear();
    flash("抽選しました。よければ「大会開始」を押してください", false);
    await refresh();
  } catch (e) { flash(e.message); }
});

async function ownerAction(t, path, method = "POST", okMsg = null) {
  try {
    await api(method, `/api/league/tournaments/${t.id}${path}`, null, { "X-Owner-Key": ownerKey(t.id) || "" });
    if (okMsg) flash(okMsg, false);
    await refresh();
  } catch (e) { flash(e.message); }
}

const STATUS = { setup: "抽選済み・開始前", blocks: "ブロック戦", final: "決勝", done: "終了" };

function tourCard(t) {
  const card = el("div", "card");
  const head = el("div", "section-head");
  const h = el("h2", null, t.name);
  h.append(el("small", null, STATUS[t.status]));
  if (ownerKey(t.id)) h.append(el("span", "owner-tag", "オーナー"));
  head.append(h);
  card.append(head);
  const owner = !!ownerKey(t.id);
  // オーナー（🇯🇵）と編集ボタン
  const ol = el("div", "owner-line");
  ol.append(el("span", "lbl", "オーナー"));
  if (t.owner_player) ol.append(whoEl(t.owner_player)); else ol.append(el("span", "lbl", "（未設定）🇯🇵"));
  if (!(ui.edit && ui.edit.tid === t.id)) {
    const eb = btn("編集", () => {
      if (!ownerKey(t.id)) { flash("編集はオーナーの端末でできます。オーナーに「ほかの端末でもオーナー操作」のリンクをもらってください"); return; }
      startEdit(t);
    }, "small-btn" + (owner ? " primary" : ""));
    ol.append(eb);
  }
  card.append(ol);
  const sp = t.start_points || { 4: 25000, 3: 35000 };
  const sizes = new Set([...t.blocks.map((b) => b.length), t.blocks.length > 1 ? t.blocks.length : 0]);
  card.append(el("p", "tip", "持ち点：" + [4, 3, 2].filter((k) => sizes.has(k)).map((k) => `${KIND[k]} ${pts(+(sp[k] ?? DEFAULT_START[k]))}点`).join("・")
    + (sizes.has(2) ? "（二麻のアガリは役満だけ）" : "")));

  if (owner && ui.edit && ui.edit.tid === t.id) {
    card.append(editView(t));
    return card;
  }

  if (t.status === "done" && t.king) {
    const k = el("div", "king");
    k.append(el("div", "crown", "👑"), avatarEl(player(t.king), "huge"), el("div", "title", "キング"), el("div", "name", player(t.king).name));
    card.append(k);
  }

  const n = t.blocks.length;
  const info = el("p", "tip", n === 1
    ? `${t.players.length}人・ブロック分けなし。${KIND[t.players.length]}1卓のトップが「キング」です。`
    : `${t.players.length}人・${n}ブロック。各ブロックのトップ${n}人が${KIND[n]}で決勝を打ち、トップが「キング」です。`);
  card.append(info);

  if (t.final_game) {
    card.append(el("h3", "sub", "決勝"));
    card.append(gameBlock(game(t.final_game), "決勝", null));
  }

  const single = t.blocks.length === 1;
  const blocks = el("div", "blocks");
  if (!single || t.status === "setup") card.append(el("h3", "sub", t.status !== "setup" ? "ブロック" : single ? "席順（抽選結果）" : "ブロック分け（抽選結果）"));
  t.blocks.forEach((members, i) => {
    if (single && t.status !== "setup") return;  // ブロックなしの大会は決勝の卓だけ
    const label = single ? `決勝（${KIND[members.length]}）` : `${String.fromCharCode(65 + i)}ブロック（${KIND[members.length]}）`;
    if (t.status === "setup") {
      const b = el("div", "block");
      b.append(el("h3", null, label));
      members.forEach((pid, s) => {
        const m = el("div", "member");
        m.append(whoEl(pid), el("span", "meta", SEATS[s]));
        b.append(m);
      });
      blocks.append(b);
    } else {
      blocks.append(gameBlock(game(t.block_games[i]), label, t.winners[i]));
    }
  });
  card.append(blocks);

  const row = el("div", "row");
  if (owner && t.status === "setup") {
    row.append(btn("抽選し直す", () => ownerAction(t, "/draw", "POST", "抽選し直しました")));
    row.append(btn("大会開始", () => ownerAction(t, "/start", "POST", "大会を開始しました。各卓で「点数をつける」を押してください"), "primary"));
  } else if (owner && t.status === "blocks") {
    const left = t.winners.filter((w) => !w).length;
    const b = btn(left ? `決勝を始める（あと${left}ブロック）` : "決勝を始める", () => ownerAction(t, "/final", "POST", "決勝の卓を作りました"), "primary");
    b.disabled = left > 0;
    row.append(b);
  } else if (t.status === "done" && !ui.data.tournaments.some((x) => x.status !== "done")) {
    row.append(btn("新しい大会を作る", () => { ui.showSetup = true; renderTour(); }, "primary"));
  }
  if (row.children.length) card.append(row);
  if (owner) {
    const tools = el("div", "row");
    tools.append(btn("ほかの端末でもオーナー操作", () => shareOwner(t)));
    card.append(tools);
  }
  if (owner && t.status === "setup") {
    const del = btn("この大会をやめる", async () => {
      if (!confirm("この大会を削除しますか？（まだ始まっていないので成績には影響しません）")) return;
      await ownerAction(t, "", "DELETE", "大会を削除しました");
    });
    del.className = "small-btn";
    card.append(del);
  }
  if (!owner && t.status === "setup") card.append(el("p", "tip", "オーナーが「大会開始」を押すと、各卓の点数表ができます。"));
  if (!owner && t.status === "blocks") card.append(el("p", "tip", "全ブロックが終わったら、オーナーが決勝を始めます。"));
  return card;
}

function btn(text, onClick, cls = "") {
  const b = el("button", cls, text);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

// 大会の1卓（ブロックまたは決勝）：いまの持ち点の順に並べる
function gameBlock(g, label, winner) {
  const b = el("div", "block");
  if (!g) return b;
  const h = el("h3", null, label);
  h.append(el("span", "state-tag " + (g.finished ? "done" : g.hands.length ? "live" : ""), g.finished ? "終了" : g.hands.length ? `対局中・${g.hands.length}局` : "開始前"));
  b.append(h);
  g.order.forEach((pid, r) => {
    const m = el("div", "member" + (pid === winner ? " win" : (!g.finished && r === 0 && g.hands.length ? " top" : "")));
    m.append(whoEl(pid), el("span", "pts-s", pts(g.points[pid])));
    b.append(m);
  });
  b.append(btn(g.finished ? "結果を見る" : "点数をつける", () => openGame(g.id), g.finished ? "" : "primary"));
  return b;
}

// ---------- 対局 ----------
function openGame(gid) {
  ui.game = gid;
  ui.formKey = null;
  save("mj-league-game", gid);
  ui.tab = "game";
  save("mj-league-tab", "game");
  render();
  window.scrollTo({ top: 0 });
}

function renderGames() {
  const g = ui.game && game(ui.game);
  $("gameDetail").hidden = !g;
  $("gameList").hidden = !!g;
  if (g) { renderGameDetail(g); return; }
  ui.newPick = ui.newPick.filter((pid) => ui.data.players.some((p) => p.id === pid));
  pickButtons($("newPick"), (pid) => ui.newPick.includes(pid), null, (pid) => {
    const i = ui.newPick.indexOf(pid);
    if (i >= 0) ui.newPick.splice(i, 1);
    else if (ui.newPick.length < 4) ui.newPick.push(pid);
    else flash("1卓は4人までです");
    renderGames();
  });
  const n = ui.newPick.length;
  $("newGame").disabled = n < 2;
  $("newGame").textContent = n < 2 ? `対局を始める（あと${2 - n}人以上）` : `${KIND[n]}で対局を始める（席は抽選）`;

  const list = $("games");
  list.replaceChildren();
  if (!ui.data.games.length) list.append(el("p", "tip", "まだ対局はありません。"));
  ui.data.games.forEach((g) => {
    const b = el("button", "game-item");
    b.type = "button";
    const head = el("span", "head");
    head.append(el("span", null, g.title), el("span", "state-tag " + (g.finished ? "done" : g.hands.length ? "live" : ""),
      g.finished ? "終了" : g.hands.length ? `対局中・${g.hands.length}局` : "開始前"));
    const line = el("span", "line");
    g.order.forEach((pid, r) => line.append(el("span", null, `${r + 1}. ${player(pid).name} ${pts(g.points[pid])}`)));
    b.append(head, line);
    b.addEventListener("click", () => openGame(g.id));
    list.append(b);
  });
}

$("newGame").addEventListener("click", async () => {
  try {
    const g = await api("POST", "/api/league/games", { players: ui.newPick, start: startInput("newStart") });
    $("newStart").value = "";
    ui.newPick = [];
    await refresh();
    openGame(g.id);
  } catch (e) { flash(e.message); }
});
$("gBack").addEventListener("click", () => {
  ui.game = null;
  save("mj-league-game", null);
  renderGames();
});

function options(select, items, keep = true) {
  const prev = select.value;
  select.replaceChildren();
  items.forEach(([v, text]) => {
    const o = document.createElement("option");
    o.value = v;
    o.textContent = text;
    select.append(o);
  });
  if (keep && items.some(([v]) => String(v) === prev)) select.value = prev;
}

function hkind() { return document.querySelector("input[name=hkind]:checked").value; }

function renderGameDetail(g) {
  $("gTitle").textContent = g.title;
  $("gYakuman").hidden = g.players.length !== 2;
  const board = $("gBoard");
  board.replaceChildren();
  g.players.forEach((pid, i) => {
    const s = el("div", "seat" + (i === g.dealer ? " dealer" : ""));
    const rank = g.order.indexOf(pid) + 1;
    s.append(whoEl(pid));
    s.append(el("span", "meta", `${seatName(g, i)}家${i === g.dealer ? "（親）" : ""}・${rank}位`));
    s.append(el("span", "pts", pts(g.points[pid])));
    const d = g.points[pid] - g.start;
    s.append(el("span", "diff " + (d > 0 ? "plus" : d < 0 ? "minus" : ""), `持ち点から ${fmt(d)}`));
    board.append(s);
  });

  // 入力欄は、対局や参加者が変わったときだけ作り直す（入力中の値を消さないため）
  const key = g.id + ":" + g.players.join(",");
  if (ui.formKey !== key) {
    ui.formKey = key;
    ui.winner = null;
    ui.loser = null;
    ui.editHand = null;
    const rc = $("hRiichi");
    rc.replaceChildren();
    const dl = $("hDeltas");
    dl.replaceChildren();
    g.players.forEach((pid) => {
      const l = el("label");
      const c = document.createElement("input");
      c.type = "checkbox";
      c.value = pid;
      l.append(c, el("span", null, player(pid).name));
      rc.append(l);
      const dlab = el("label");
      const inp = document.createElement("input");
      inp.type = "number";
      inp.step = "100";
      inp.inputMode = "numeric";
      inp.dataset.pid = pid;
      inp.placeholder = "0";
      dlab.append(whoEl(pid), inp);
      dl.append(dlab);
    });
  }
  renderWhoPick(g);
  options($("gDealer"), g.players.map((pid, i) => [i, `${player(pid).name}`]), false);
  $("gDealer").value = String(g.dealer);
  updateKind();

  // 持ち点：1局目を記録するまで変えられる（大会の卓はオーナーの端末だけ）
  const canStart = !g.hands.length && !g.finished && (!g.tournament || !!ownerKey(g.tournament));
  $("gStartBox").hidden = !canStart;
  if (canStart && !$("gStart").matches(":focus")) $("gStart").value = g.start;
  if (ui.editHand != null && (g.finished || ui.editHand >= g.hands.length)) ui.editHand = null;
  const editing = ui.editHand != null;
  $("gEntry").classList.toggle("editing", editing);
  $("hTitle").textContent = editing ? `${ui.editHand + 1}局目の記録を直す` : "この局の結果を記録";
  $("hEditBar").hidden = !editing;
  if (editing) $("hEditBar").textContent = "直したい所（ロンの相手・点数など）を変えて「この局を直す」を押してください。持ち点と個人成績は自動で数え直します。";
  $("hSave").textContent = editing ? "この局を直す" : "記録する";
  $("hCancel").hidden = !editing;
  $("hDelete").hidden = !editing;
  $("gEntry").hidden = g.finished;
  $("gDealer").disabled = g.finished;
  $("gUndo").hidden = g.finished;
  $("gUndo").disabled = !g.hands.length;
  $("gFinish").hidden = g.finished;
  $("gReopen").hidden = !g.finished;

  $("gHandCount").textContent = `${g.hands.length}局`;
  const hl = $("gHands");
  hl.replaceChildren();
  g.hands.forEach((h, idx) => {
    const li = el("li", idx === ui.editHand ? "fixing" : "");
    let text;
    if (h.kind === "ron") text = `${player(h.winner).name} が ${player(h.loser).name} からロン`;
    else if (h.kind === "tsumo") text = `${player(h.winner).name} のツモ`;
    else text = h.note || "流局・その他";
    li.append(el("span", null, text));
    Object.entries(h.deltas).filter(([, d]) => d).forEach(([pid, d]) => {
      li.append(el("span", d > 0 ? "plus" : "minus", `${player(pid).name}${fmt(d)}`));
    });
    if (h.edited) li.append(el("span", "edited", "（修正済み）"));
    if (!g.finished) li.append(btn(idx === ui.editHand ? "修正中" : "直す", () => startHandEdit(g, idx), "fix"));
    hl.append(li);
  });
  if (g.finished && g.ranks) {
    const li = el("li");
    li.append(el("span", null, "終了：" + g.ranks.map((pid, i) => `${i + 1}位 ${player(pid).name}`).join("、")));
    hl.append(li);
  }
}

// アガった人・振り込んだ人はアバターのボタンで選ぶ（ロンは振り込んだ人を必ず選ぶ）
function renderWhoPick(g) {
  const make = (box, isOn, isOff, onPick) => {
    box.replaceChildren();
    g.players.forEach((pid, i) => {
      const b = el("button");
      b.type = "button";
      b.setAttribute("aria-pressed", isOn(pid));
      b.disabled = isOff(pid);
      b.append(avatarEl(player(pid)), el("span", "name", player(pid).name), el("span", "meta", `${seatName(g, i)}家`));
      b.addEventListener("click", () => { onPick(pid); renderWhoPick(g); updateKind(); });
      box.append(b);
    });
  };
  make($("hWinner"), (pid) => ui.winner === pid, () => false, (pid) => {
    ui.winner = ui.winner === pid ? null : pid;
    if (ui.loser === ui.winner) ui.loser = null;
  });
  $("hLoser").classList.add("loser");
  make($("hLoser"), (pid) => ui.loser === pid, (pid) => pid === ui.winner, (pid) => { ui.loser = ui.loser === pid ? null : pid; });
}

// 直している局ならその局の親、そうでなければいまの親
function dealerSeat(g) {
  const h = ui.editHand != null && g.hands[ui.editHand];
  return h ? h.dealer_before : g.dealer;
}

function clearEntry() {
  ["hPoints", "hChild", "hDealerPay", "hNote"].forEach((id) => ($(id).value = ""));
  ui.winner = null;
  ui.loser = null;
  document.querySelectorAll("#hRiichi input, #hDeltas input").forEach((i) => { if (i.type === "checkbox") i.checked = false; else i.value = ""; });
}

// 記録した局を入力欄に戻して直す
function startHandEdit(g, idx) {
  if (ui.editHand === idx) { cancelHandEdit(); return; }
  const h = g.hands[idx];
  clearEntry();
  ui.editHand = idx;
  document.querySelector(`input[name=hkind][value=${h.kind}]`).checked = true;
  ui.winner = h.winner;
  ui.loser = h.loser;
  const pays = Object.fromEntries(Object.entries(h.deltas).map(([pid, d]) => [pid, -d]));
  if (h.kind === "ron") $("hPoints").value = h.points ?? pays[h.loser];
  if (h.kind === "tsumo") {
    const dealerId = g.players[h.dealer_before];
    const others = g.players.filter((pid) => pid !== h.winner && pid !== dealerId);
    $("hChild").value = h.pay_child ?? (others.length ? pays[others[0]] : pays[dealerId]);
    $("hDealerPay").value = h.winner === dealerId ? "" : (h.pay_dealer ?? pays[dealerId]);
  }
  (h.riichi || []).forEach((pid) => {
    const c = document.querySelector(`#hRiichi input[value="${pid}"]`);
    if (c) c.checked = true;
  });
  if (h.kind === "other") {
    document.querySelectorAll("#hDeltas input").forEach((i) => (i.value = h.deltas[i.dataset.pid] || ""));
    $("hNote").value = h.note || "";
  }
  renderGameDetail(g);
  $("gEntry").scrollIntoView({ behavior: "smooth", block: "start" });
}
function cancelHandEdit() {
  ui.editHand = null;
  clearEntry();
  const g = game(ui.game);
  if (g) renderGameDetail(g);
}
$("hCancel").addEventListener("click", cancelHandEdit);
$("hDelete").addEventListener("click", async () => {
  const i = ui.editHand;
  if (i == null || !confirm(`${i + 1}局目の記録を削除しますか？（持ち点と個人成績は数え直します）`)) return;
  try {
    await api("DELETE", `/api/league/games/${ui.game}/hands/${i}`);
    cancelHandEdit();
    flash(`${i + 1}局目の記録を削除しました`, false);
    await refresh();
  } catch (e) { flash(e.message); }
});

function updateKind() {
  const k = hkind();
  document.querySelectorAll("#gEntry [class*=kind-]").forEach((e) => (e.hidden = !e.classList.contains("kind-" + k)));
  const g = ui.game && game(ui.game);
  if (!g) return;
  const winnerIsDealer = ui.winner === g.players[dealerSeat(g)];
  const nima = g.players.length === 2;
  $("hNima").hidden = !nima || k === "other";
  $("hDealerBox").hidden = nima || winnerIsDealer || k !== "tsumo";
  $("hChildBox").firstChild.textContent = nima ? "相手の支払い（役満の点数・本場込み） "
    : winnerIsDealer ? "全員の支払い（〇〇点オール） " : "子の支払い（1人あたり） ";
  // 二麻は役満だけなので、役満の点数をボタンで入れられるようにする
  const quick = $("hYakuman");
  quick.hidden = !nima || k !== "ron";
  const tq = $("hYakumanT") || (() => {
    const d = el("div", "quick");
    d.id = "hYakumanT";
    $("hChildBox").after(d);
    return d;
  })();
  tq.hidden = !nima || k !== "tsumo";
  if (nima) {
    const base = winnerIsDealer ? 48000 : 32000;
    [[quick, "hPoints"], [tq, "hChild"]].forEach(([box, id]) => {
      box.replaceChildren();
      [[1, "役満"], [2, "ダブル役満"], [3, "トリプル役満"]].forEach(([m, name]) => {
        box.append(btn(`${name} ${pts(base * m)}`, () => { $(id).value = base * m; }));
      });
    });
  }
}
document.querySelectorAll("input[name=hkind]").forEach((r) => r.addEventListener("change", updateKind));

$("gStartSave").addEventListener("click", async () => {
  const g = game(ui.game);
  try {
    await api("POST", `/api/league/games/${ui.game}/start`, { start: startInput("gStart") },
      g && g.tournament ? { "X-Owner-Key": ownerKey(g.tournament) || "" } : {});
    flash("持ち点を変えました", false);
    await refresh();
  } catch (e) { flash(e.message); }
});

$("gDealer").addEventListener("change", async () => {
  try {
    await api("POST", `/api/league/games/${ui.game}/dealer`, { seat: parseInt($("gDealer").value, 10) });
    await refresh();
  } catch (e) { flash(e.message); }
});

$("hSave").addEventListener("click", async () => {
  const k = hkind();
  const body = { kind: k };
  if (k === "other") {
    body.deltas = {};
    document.querySelectorAll("#hDeltas input").forEach((i) => (body.deltas[i.dataset.pid] = parseInt(i.value, 10) || 0));
    body.note = $("hNote").value;
  } else {
    if (!ui.winner) { flash("アガった人をタップして選んでください"); return; }
    if (k === "ron" && !ui.loser) { flash("ロンは、振り込んだ人（放銃者）を必ず選んでください"); return; }
    body.winner = ui.winner;
    body.riichi = [...document.querySelectorAll("#hRiichi input:checked")].map((c) => c.value);
    if (k === "ron") {
      body.loser = ui.loser;
      body.points = parseInt($("hPoints").value, 10) || 0;
    } else {
      body.pay_child = parseInt($("hChild").value, 10) || 0;
      body.pay_dealer = parseInt($("hDealerPay").value, 10) || 0;
    }
  }
  try {
    const fixing = ui.editHand;
    if (fixing != null) await api("PUT", `/api/league/games/${ui.game}/hands/${fixing}`, body);
    else await api("POST", `/api/league/games/${ui.game}/hands`, body);
    clearEntry();
    ui.editHand = null;
    flash(fixing != null
      ? `${fixing + 1}局目を直しました。持ち点と個人成績も数え直しました`
      : "記録しました。間違えたときは下の「記録」の「直す」で直せます", false);
    await refresh();
  } catch (e) { flash(e.message); }
});

$("gUndo").addEventListener("click", async () => {
  if (!confirm("最後の局の記録を取り消しますか？")) return;
  try { await api("DELETE", `/api/league/games/${ui.game}/hands/last`); await refresh(); flash("取り消しました", false); } catch (e) { flash(e.message); }
});
$("gFinish").addEventListener("click", async () => {
  if (!confirm("対局を終了して順位を確定しますか？（同点は起家に近い人が上）")) return;
  try { await api("POST", `/api/league/games/${ui.game}/finish`); await refresh(); flash("対局を終了しました", false); } catch (e) { flash(e.message); }
});
$("gReopen").addEventListener("click", async () => {
  try { await api("POST", `/api/league/games/${ui.game}/reopen`); await refresh(); flash("対局を再開しました", false); } catch (e) { flash(e.message); }
});

// ---------- 成績 ----------
function renderRank() {
  const body = $("rankBody");
  body.replaceChildren();
  ui.data.players.forEach((p, i) => {
    const s = p.stats;
    const tr = el("tr");
    const who = el("td");
    who.append(whoEl(p.id));
    if (s.kings) who.append(el("span", null, " " + "👑".repeat(Math.min(3, s.kings))));
    tr.append(el("td", null, String(i + 1)), who,
      el("td", s.plus ? "plus" : "", pts(s.plus)), el("td", s.minus ? "minus" : "", pts(s.minus)),
      el("td", s.net > 0 ? "plus" : s.net < 0 ? "minus" : "", fmt(s.net)),
      el("td", null, String(s.games)), el("td", null, String(s.tops)));
    body.append(tr);
  });
  if (!ui.data.players.length) {
    const tr = el("tr");
    const td = el("td", null, "まだプレイヤーがいません");
    td.colSpan = 7;
    tr.append(td);
    body.append(tr);
  }
}

// ---------- プレイヤー ----------
function renderPlayers() {
  $("playerCount").textContent = `${ui.data.players.length}人`;
  const list = $("playerList");
  list.replaceChildren();
  ui.data.players.slice().sort((a, b) => a.name.localeCompare(b.name, "ja")).forEach((p) => {
    const b = el("button");
    b.type = "button";
    b.append(avatarEl(p), el("span", "name", p.name), el("span", "sub", `対局${p.stats.games}・合計${fmt(p.stats.net)}`));
    b.addEventListener("click", () => openRegister(p));
    list.append(b);
  });
  if (!ui.data.players.length) list.append(el("p", "tip", "名前とアバターを登録すると、大会や対局に参加できます。"));
}

// ---------- 登録ダイアログ ----------
let regTarget = null; // 登録後に自動で選ぶ先（"tour" | "new"）

function openRegister(p = null, target = null) {
  regTarget = target;
  ui.reg = { id: p ? p.id : null, emoji: p ? (p.avatar ? null : p.emoji) : null, photo: null, keepPhoto: !!(p && p.avatar), avatar: p && p.avatar };
  $("regTitle").textContent = p ? "プレイヤーを編集" : "プレイヤー登録";
  $("regSave").textContent = p ? "保存する" : "登録する";
  $("regDelete").hidden = !p;
  $("regName").value = p ? p.name : "";
  $("regError").hidden = true;
  $("regPhoto").value = "";
  renderReg();
  $("regDialog").showModal();
  if (!p) $("regName").focus();
}
function renderReg() {
  const r = ui.reg;
  const prev = $("regPreview");
  prev.replaceChildren();
  if (r.photo || r.keepPhoto) {
    const img = document.createElement("img");
    img.src = r.photo || r.avatar;
    img.alt = "";
    prev.append(img);
  } else {
    prev.textContent = r.emoji || "？";
  }
  $("regPhotoClear").hidden = !(r.photo || r.keepPhoto);
  const box = $("regEmojis");
  box.replaceChildren();
  EMOJIS.forEach((e) => {
    const b = el("button", null, e);
    b.type = "button";
    b.setAttribute("aria-pressed", !r.photo && !r.keepPhoto && r.emoji === e);
    b.addEventListener("click", () => { r.emoji = e; r.photo = null; r.keepPhoto = false; renderReg(); });
    box.append(b);
  });
}
document.querySelectorAll("[data-open-register]").forEach((b) => b.addEventListener("click", () => {
  openRegister(null, b.closest("#tab-tour") ? "tour" : b.closest("#tab-game") ? "new" : null);
}));
$("regCancel").addEventListener("click", () => $("regDialog").close());
$("regPhotoClear").addEventListener("click", () => { ui.reg.photo = null; ui.reg.keepPhoto = false; renderReg(); });

// 写真は端末側で正方形・320px に縮めてから送る（サーバーでさらに 160px にし、位置情報などは残さない）
$("regPhoto").addEventListener("change", () => {
  const f = $("regPhoto").files[0];
  if (!f) return;
  const url = URL.createObjectURL(f);
  const img = new Image();
  img.onload = () => {
    const s = Math.min(img.naturalWidth, img.naturalHeight);
    const c = document.createElement("canvas");
    c.width = c.height = 320;
    c.getContext("2d").drawImage(img, (img.naturalWidth - s) / 2, (img.naturalHeight - s) / 2, s, s, 0, 0, 320, 320);
    ui.reg.photo = c.toDataURL("image/jpeg", 0.85);
    ui.reg.keepPhoto = false;
    URL.revokeObjectURL(url);
    renderReg();
  };
  img.onerror = () => { URL.revokeObjectURL(url); flash("写真を読み込めませんでした"); };
  img.src = url;
});

$("regForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const r = ui.reg;
  const name = $("regName").value.trim();
  const err = (m) => { $("regError").textContent = m; $("regError").hidden = false; };
  if (!name) return err("名前を入力してください");
  if (!r.photo && !r.keepPhoto && !r.emoji) return err("アバター（写真か絵文字）を選んでください");
  const body = { name, emoji: r.emoji || "🀄" };
  if (r.photo) body.photo = r.photo;
  if (r.id && !r.photo && !r.keepPhoto) body.remove_photo = true;
  try {
    const p = r.id ? await api("PUT", `/api/league/players/${r.id}`, body) : await api("POST", "/api/league/players", body);
    $("regDialog").close();
    if (!r.id && regTarget === "tour") ui.tourPick.add(p.id);
    if (!r.id && regTarget === "new" && ui.newPick.length < 4) ui.newPick.push(p.id);
    flash(r.id ? "保存しました" : `${p.name} さんを登録しました`, false);
    await refresh();
  } catch (e) { err(e.message); }
});
$("regDelete").addEventListener("click", async () => {
  const r = ui.reg;
  if (!r.id || !confirm("このプレイヤーを削除しますか？")) return;
  try {
    await api("DELETE", `/api/league/players/${r.id}`);
    $("regDialog").close();
    await refresh();
  } catch (e) { $("regError").textContent = e.message; $("regError").hidden = false; }
});


// ---------- オーナーの編集 ----------
function startEdit(t) {
  ui.edit = {
    tid: t.id, name: t.name, blocks: t.blocks.map((b) => [...b]), sel: null,
    owner: t.owner_player || "", start: { ...DEFAULT_START, ...(t.start_points || {}) },
    entries: false, pick: new Set(t.players), nb: t.blocks.length,
  };
  renderTour();
}
function blockLocked(t, i) {
  if (t.status === "setup") return false;
  if (t.status !== "blocks") return true;
  const g = game(t.block_games[i]);
  return !!(g && (g.hands.length || g.finished));
}
function editView(t) {
  const e = ui.edit;
  const box = el("div", "edit-box");
  const nameField = el("label", "field", "大会名");
  const name = document.createElement("input");
  name.type = "text";
  name.maxLength = 30;
  name.value = e.name;
  name.addEventListener("input", () => (e.name = name.value));
  nameField.append(name);
  box.append(nameField);

  const ownerField = el("label", "field", "オーナー（🇯🇵の旗を立てる人）");
  const os = document.createElement("select");
  ownerOptions(os, e.owner);
  os.addEventListener("change", () => (e.owner = os.value));
  ownerField.append(os);
  box.append(ownerField);

  if (t.status !== "done") {
    box.append(el("h3", "sub", "持ち点"));
    if (t.status !== "setup") box.append(el("p", "tip", "開始後は、まだ点数を記録していない卓にだけ反映されます。"));
    const spBox = el("div", "start-points");
    [4, 3, 2].forEach((n) => {
      const f = el("label", "field", KIND_LONG[n]);
      const inp = document.createElement("input");
      inp.type = "number";
      inp.step = "1000";
      inp.min = "1000";
      inp.max = "200000";
      inp.inputMode = "numeric";
      inp.value = e.start[n] ?? DEFAULT_START[n];
      inp.addEventListener("input", () => (e.start[n] = parseInt(inp.value, 10) || 0));
      f.append(inp);
      spBox.append(f);
    });
    box.append(spBox);
  }

  const canBlocks = t.status === "setup" || t.status === "blocks";
  if (canBlocks) {
    box.append(el("h3", "sub", "ブロック分け・席順"));
    box.append(el("p", "tip", "入れ替えたい2人を続けてタップすると、席（ブロックや東南西北）が入れ替わります。来られなくなった人は、タップしてから下の「控え」の人をタップすると交代します。"
      + (t.status === "blocks" ? "開始後は、まだ点数を記録していないブロックだけ変えられます。" : "")));
    const blocks = el("div", "blocks");
    e.blocks.forEach((members, i) => {
      const locked = blockLocked(t, i);
      const b = el("div", "block" + (locked ? " locked" : ""));
      const h = el("h3", null, e.blocks.length === 1 ? `決勝（${KIND[members.length]}）` : `${String.fromCharCode(65 + i)}ブロック（${KIND[members.length]}）`);
      if (locked) h.append(el("span", "state-tag", "記録あり・変更不可"));
      b.append(h);
      members.forEach((pid, si) => {
        const m = el("button", "member edit-member");
        m.type = "button";
        m.disabled = locked;
        m.setAttribute("aria-pressed", !!(e.sel && e.sel[0] === i && e.sel[1] === si));
        m.append(whoEl(pid), el("span", "meta", SEATS[si]));
        m.addEventListener("click", () => tapMember(t, i, si));
        b.append(m);
      });
      blocks.append(b);
    });
    box.append(blocks);

    const inUse = new Set(e.blocks.flat());
    const bench = ui.data.players.filter((p) => !inUse.has(p.id));
    box.append(el("h3", "sub", `控え（参加していない人） ${bench.length}人`));
    const list = el("div", "pick-list");
    bench.forEach((p) => {
      const b = el("button");
      b.type = "button";
      b.append(avatarEl(p), el("span", "name", p.name));
      b.addEventListener("click", () => {
        if (!e.sel) { flash("先に、交代するメンバーをタップしてください"); return; }
        e.blocks[e.sel[0]][e.sel[1]] = p.id;
        e.sel = null;
        renderTour();
      });
      list.append(b);
    });
    if (!bench.length) list.append(el("p", "tip", "控えの人はいません。"));
    box.append(list);
  } else {
    box.append(el("p", "tip", "決勝が始まったので、変えられるのは大会名だけです。"));
  }

  if (t.status === "setup") {
    const more = btn(e.entries ? "人数・ブロック数の変更を閉じる" : "参加者の人数・ブロック数を変える", () => { e.entries = !e.entries; renderTour(); });
    more.className = "small-btn";
    box.append(more);
    if (e.entries) box.append(entriesView(t));
  }

  const row = el("div", "row");
  row.append(btn("やめる", () => { ui.edit = null; renderTour(); }));
  row.append(btn("保存する", async () => {
    const body = { name: e.name, owner_player: e.owner };
    if (canBlocks) body.blocks = e.blocks;
    if (t.status !== "done") body.start_points = e.start;
    try {
      await api("PATCH", `/api/league/tournaments/${t.id}`, body, { "X-Owner-Key": ownerKey(t.id) || "" });
      ui.edit = null;
      flash("大会を更新しました", false);
      await refresh();
    } catch (err) { flash(err.message); }
  }, "primary"));
  box.append(row);
  return box;
}
function tapMember(t, i, si) {
  const e = ui.edit;
  if (!e.sel) e.sel = [i, si];
  else if (e.sel[0] === i && e.sel[1] === si) e.sel = null;
  else {
    const [a, b] = e.sel;
    [e.blocks[a][b], e.blocks[i][si]] = [e.blocks[i][si], e.blocks[a][b]];
    e.sel = null;
  }
  renderTour();
}
function entriesView(t) {
  const e = ui.edit;
  const box = el("div", "entries");
  box.append(el("p", "tip", `参加者を選び直して、ブロック数を選んでから「この参加者で抽選し直す」を押します（いま${e.pick.size}人）。`));
  const list = el("div", "pick-list");
  pickButtons(list, (pid) => e.pick.has(pid), null, (pid) => {
    if (e.pick.has(pid)) e.pick.delete(pid); else e.pick.add(pid);
    renderTour();
  });
  box.append(list);
  const fs = formats(e.pick.size);
  if (!fs.some((f) => f.blocks === e.nb)) e.nb = fs.length ? fs[0].blocks : null;
  const fbox = el("div", "formats");
  if (!fs.length) fbox.append(el("p", "none", "大会は2〜16人です。"));
  fs.forEach((f) => {
    const l = el("label");
    const r = document.createElement("input");
    r.type = "radio";
    r.name = "editFormat";
    r.checked = f.blocks === e.nb;
    r.addEventListener("change", () => (e.nb = f.blocks));
    l.append(r, el("span", null, f.label));
    fbox.append(l);
  });
  box.append(fbox);
  const go = btn("この参加者で抽選し直す", async () => {
    try {
      const H = { "X-Owner-Key": ownerKey(t.id) || "" };
      await api("POST", `/api/league/tournaments/${t.id}/entries`, { players: [...e.pick], blocks: e.nb }, H);
      await api("PATCH", `/api/league/tournaments/${t.id}`, { name: e.name, owner_player: e.owner, start_points: e.start }, H);
      ui.edit = null;
      flash("参加者を変えて抽選し直しました", false);
      await refresh();
    } catch (err) { flash(err.message); }
  }, "primary");
  go.disabled = !fs.length;
  box.append(go);
  return box;
}

// オーナーの合言葉入りリンク。PC など別の端末で開くと、その端末でもオーナーとして操作できる
async function shareOwner(t) {
  const url = `${location.origin}/taikai#owner=${t.id}.${ownerKey(t.id)}`;
  let copied = false;
  try { await navigator.clipboard.writeText(url); copied = true; } catch (_) { /* 下で表示 */ }
  prompt(copied
    ? "オーナー用リンクをコピーしました。別の端末で開くと、その端末でも大会を操作できます（他の人には教えないでください）"
    : "このリンクを別の端末で開くと、その端末でも大会を操作できます（他の人には教えないでください）", url);
}
function takeOwnerLink() {
  const m = location.hash.match(/owner=([0-9a-f]+)\.([A-Za-z0-9_-]+)/);
  if (!m) return;
  const keys = ownerKeys();
  keys[m[1]] = m[2];
  save("mj-owner-keys", keys);
  history.replaceState(null, "", location.pathname);  // 合言葉をアドレス欄に残さない
  ui.tab = "tour";
  flash("この端末でもオーナーとして操作できるようになりました", false);
}

// ---------- 役満一覧（二麻はアガリが役満だけ） ----------
let yakumanLoaded = false;
async function openYakuman() {
  if (!yakumanLoaded) {
    try {
      const { yakuman } = await api("GET", "/api/yakuman");
      const list = $("yakumanList");
      list.replaceChildren();
      yakuman.forEach((y) => {
        const item = el("li");
        const name = el("div", "yn", y.name);
        name.append(el("small", null, y.reading));
        item.append(name, el("span", "cond", y.cond), el("span", null, y.desc));
        if (y.example && y.example.length) {
          const ex = el("div", "ex");
          y.example.forEach((t) => {
            const img = document.createElement("img");
            img.src = `/static/tiles/${t}.webp?v=4`;
            img.alt = t;
            img.loading = "lazy";
            ex.append(img);
          });
          item.append(ex);
        }
        list.append(item);
      });
      yakumanLoaded = true;
    } catch (e) { flash(e.message); return; }
  }
  $("yakumanDialog").showModal();
}
document.querySelectorAll("[data-yakuman], #gYakuman").forEach((b) => b.addEventListener("click", openYakuman));
$("yakumanClose").addEventListener("click", () => $("yakumanDialog").close());

// ---------- 起動 ----------
takeOwnerLink();
refresh();
// 他の卓の点数も随時反映（画面を見ているときだけ）
setInterval(() => { if (!document.hidden && !$("regDialog").open && !$("yakumanDialog").open && !ui.edit) refresh(); }, POLL_MS);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
