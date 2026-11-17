"use strict";
// 麻雀アシスト フロントエンド（Vanilla JS）

const $ = (id) => document.getElementById(id);
const HONOR = { 1: "東", 2: "南", 3: "西", 4: "北", 5: "白", 6: "發", 7: "中" };
const SUIT = { m: "萬", p: "筒", s: "索" };
const KANJI = "一二三四五六七八九";
const FRAME_INTERVAL_MS = 350; // 最大でおよそ3フレーム/秒（前の結果が返ってから次を送る）
const MAX_TILES = 14;

const state = {
  hand: [],
  dora: [],            // ドラ表示牌（スロット順。未選択は null）
  ura: [],             // 裏ドラ表示牌
  melds: [],           // 鳴き [{type, tiles}]
  pick: null,          // 牌ボタンで何を選んでいるか {kind: "dora"|"ura"|"meld", index, type}
  rules: null,         // ルール設定
  winTile: null,      // 手牌中のアガリ牌の位置
  selected: null,
  manual: false,       // true: プレイヤーが手で修正中（自動更新を止める）
  mode: "unknown",
  kinds: 0,
  ws: null,
  waiting: false,
  stream: null,
  lastSent: 0,
};

// ---------- 牌の表示 ----------
function tileOrder(t) {
  const n = t[0] === "0" ? 5 : +t[0];
  return "mpsz".indexOf(t[1]) * 10 + n + (t[0] === "0" ? 0.5 : 0);
}
function tileName(t) {
  if (t[1] === "z") return HONOR[t[0]];
  const n = t[0] === "0" ? 5 : +t[0];
  return (t[0] === "0" ? "赤" : "") + KANJI[n - 1] + SUIT[t[1]];
}
function tileEl(t, opts = {}) {
  const el = document.createElement(opts.button ? "button" : "span");
  const red = t[0] === "0";
  el.className = `tile ${t[1]} ${t[1] === "z" ? "z" + t[0] : ""} ${red ? "red" : ""}`;
  el.setAttribute("aria-label", tileName(t));
  el.title = tileName(t);
  const n = document.createElement("span");
  n.className = "n";
  n.textContent = t[1] === "z" ? HONOR[t[0]] : (red ? "5" : t[0]);
  const s = document.createElement("span");
  s.className = "s";
  s.textContent = SUIT[t[1]] || "";
  el.append(n, s);
  // 実物の牌の写真（app/static/tiles/）。読めなければ文字表示のまま。
  const img = document.createElement("img");
  img.src = `/static/tiles/${t}.webp?v=4`;
  img.alt = "";
  img.draggable = false;
  img.decoding = "async";
  img.onerror = () => { img.remove(); el.classList.remove("img"); };
  el.classList.add("img");
  el.append(img);
  return el;
}
function tilesInline(tiles) {
  const wrap = document.createElement("span");
  wrap.className = "tiles small";
  tiles.forEach((t) => wrap.append(tileEl(t)));
  return wrap;
}

// ---------- 設定 ----------
function readSettings() {
  const winTile = state.winTile != null && state.hand[state.winTile] ? state.hand[state.winTile] : null;
  const players = playersValue();
  return {
    players,
    rules: state.rules,
    nukidora: players === 3 && state.rules.sanma_nukidora ? Math.max(0, Math.min(4, parseInt($("nukidora").value, 10) || 0)) : 0,
    melds: state.melds,
    table_kans: tableKans(),
    seat_wind: $("seatWind").value,
    round_wind: $("roundWind").value,
    honba: Math.max(0, Math.min(20, parseInt($("honba").value, 10) || 0)),
    is_riichi: $("riichi").checked && !isOpen(),
    is_tsumo: $("tsumo").checked,
    is_ippatsu: $("ippatsu").checked,
    is_double_riichi: $("dblRiichi").checked && !isOpen(),
    is_rinshan: $("rinshan").checked,
    is_chankan: $("chankan").checked,
    is_last_tile: $("lastTile").checked,
    is_first_draw: $("firstDraw").checked && !state.melds.length,
    dora_indicators: state.dora.slice(0, doraSlots()).filter(Boolean),
    ura_indicators: $("riichi").checked && !isOpen() ? state.ura.slice(0, uraSlots()).filter(Boolean) : [],
    win_tile: winTile,
  };
}
const SETTING_IDS = ["seatWind", "roundWind", "honba", "riichi", "tsumo", "ippatsu", "nukidora",
  "dblRiichi", "rinshan", "chankan", "lastTile", "firstDraw"];
const SANMA_EXCLUDED = new Set(["2m", "3m", "4m", "5m", "6m", "7m", "8m", "0m"]);

function playersValue() {
  const el = document.querySelector("input[name=players]:checked");
  return el ? (+el.value || 4) : 4;
}

// 四人／三人の切り替え：三麻では萬子2〜8と北家を使わない
function applyPlayers() {
  const sanma = playersValue() === 3;
  const nima = playersValue() === 2;
  document.querySelectorAll(".sanma-only").forEach((el) => (el.hidden = !sanma));
  document.querySelectorAll(".nima-only").forEach((el) => (el.hidden = !nima));
  // 二人麻雀の自風は東（親）か南（子）だけ
  const west = $("seatWind").querySelector("option[value=west]");
  west.hidden = nima;
  west.disabled = nima;
  document.querySelectorAll("#palette .tile").forEach((el) => (el.hidden = sanma && SANMA_EXCLUDED.has(el.dataset.tile)));
  const north = $("seatWind").querySelector("option[value=north]");
  north.hidden = sanma || nima;
  north.disabled = sanma || nima;
  if (sanma && $("seatWind").value === "north") $("seatWind").value = "west";
  if (nima && ["west", "north"].includes($("seatWind").value)) $("seatWind").value = "south";
  if (sanma) {
    state.hand = state.hand.filter((t) => !SANMA_EXCLUDED.has(t));
    state.dora = state.dora.map((t) => (t && SANMA_EXCLUDED.has(t) ? null : t));
    state.ura = state.ura.map((t) => (t && SANMA_EXCLUDED.has(t) ? null : t));
    state.melds = state.melds.filter((m) => !m.tiles.some((t) => SANMA_EXCLUDED.has(t)) && !(m.type === "chi" && !state.rules.sanma_chi));
  }
  $("chiBtn").hidden = sanma && !state.rules.sanma_chi;
}
function saveSettings() {
  try {
    const v = {};
    SETTING_IDS.forEach((id) => (v[id] = $(id).type === "checkbox" ? $(id).checked : $(id).value));
    v.players = playersValue();
    v.rules = state.rules;
    localStorage.setItem("mj-settings", JSON.stringify(v));
  } catch (_) { /* 保存できなくても動作に影響なし */ }
}
function loadSettings() {
  try {
    const v = JSON.parse(localStorage.getItem("mj-settings") || "{}");
    if (v.players === 3 || v.players === 2) document.querySelector(`input[name=players][value='${v.players}']`).checked = true;
    if (v.rules && typeof v.rules === "object") state.rules = { ...RULE_DEFAULTS, ...v.rules };
    SETTING_IDS.forEach((id) => {
      if (!(id in v)) return;
      if ($(id).type === "checkbox") $(id).checked = !!v[id]; else $(id).value = v[id];
    });
  } catch (_) { /* noop */ }
}

// ---------- 手牌の描画・編集 ----------
function renderHand() {
  const hand = $("hand");
  hand.replaceChildren();
  state.hand.forEach((t, i) => {
    const el = tileEl(t, { button: true });
    if (i === state.selected) el.classList.add("selected");
    if (state.unsure && state.unsure.has(i)) { el.classList.add("unsure"); el.title += "（自信なし。タップして直せます）"; }
    if (i === state.winTile || (state.winTile == null && state.hand.length === maxHand() && i === state.hand.length - 1)) el.classList.add("win");
    el.addEventListener("click", () => {
      state.selected = state.selected === i ? null : i;
      renderHand();
    });
    hand.append(el);
  });
  $("count").textContent = `${state.hand.length}枚`;
  $("tileActions").hidden = state.selected == null;
  $("count").textContent = `${state.hand.length}枚` + (state.melds.length ? `＋鳴き${state.melds.length}つ` : "");
  renderGlass();
  renderMelds();
  renderDora();
  $("riichi").disabled = isOpen();
  if (isOpen()) $("riichi").checked = false;
}

// ---------- 鳴き・ドラ ----------
const MELD_NAMES = { pon: "ポン", chi: "チー", kan: "明カン", ankan: "暗カン" };
const base5 = (x) => (x[0] === "0" ? "5" + x[1] : x);

function isOpen() { return state.melds.some((m) => m.type !== "ankan"); }
function ownKans() { return state.melds.filter((m) => m.type === "kan" || m.type === "ankan").length; }
function tableKans() {
  const v = Math.max(0, Math.min(4, parseInt($("tableKans").value, 10) || 0));
  return Math.min(4, Math.max(v, ownKans()));
}
function doraSlots() { return 1 + (state.rules.kan_dora ? tableKans() : 0); }
function uraSlots() { return state.rules.ura_dora ? 1 + (state.rules.kan_ura ? tableKans() : 0) : 0; }
function maxHand() { return MAX_TILES - 3 * state.melds.length; }

// ドラ表示牌 → ドラ（三麻は萬子が 1→9→1）
function doraOf(ind) {
  const t = base5(ind), n = +t[0], s = t[1];
  if (s === "z") return n <= 4 ? `${(n % 4) + 1}z` : `${((n - 5 + 1) % 3) + 5}z`;
  if (s === "m" && playersValue() === 3) return n === 1 ? "9m" : "1m";
  return `${(n % 9) + 1}${s}`;
}

function renderSlots(container, list, count, kind) {
  container.replaceChildren();
  for (let i = 0; i < count; i++) {
    const t = list[i];
    const slot = document.createElement("button");
    slot.className = "dora-slot" + (state.pick && state.pick.kind === kind && state.pick.index === i ? " picking" : "");
    if (t) {
      slot.append(tilesInline([t]), span(`→ ${tileName(doraOf(t))}`, "meta"));
    } else {
      slot.append(span(i === 0 ? "＋ 選ぶ" : `＋ カン${i}回目`, "meta"));
    }
    slot.addEventListener("click", () => startPick({ kind, index: i }));
    container.append(slot);
  }
}

function renderDora() {
  $("tableKans").value = tableKans();
  const k = tableKans(), own = ownKans();
  $("kanNote").hidden = k < 4;
  $("kanNote").textContent = own >= 4
    ? "4回とも自分のカンです。四槓子（役満）のチャンス！5回目のカンは誰もできません"
    : "カンが4回になりました。2人以上でのカンなら「四槓散了（スーカンサンラ）」で流局です。これ以上カンはできません";
  renderSlots($("doraSlots"), state.dora, doraSlots(), "dora");
  const showUra = $("riichi").checked && !isOpen() && uraSlots() > 0;
  $("uraBox").hidden = !showUra;
  if (showUra) renderSlots($("uraSlots"), state.ura, uraSlots(), "ura");
}

function renderMelds() {
  const box = $("melds");
  box.replaceChildren();
  state.melds.forEach((m, i) => {
    const el = document.createElement("button");
    el.className = "meld";
    el.title = "タップで取り消し";
    el.append(span(MELD_NAMES[m.type], "meta"), tilesInline(m.tiles));
    el.addEventListener("click", () => {
      state.melds.splice(i, 1);
      flash(`${MELD_NAMES[m.type]}を取り消しました`, false);
      setManual(true);
      changed();
    });
    box.append(el);
  });
}

function startPick(pick) {
  const same = state.pick && state.pick.kind === pick.kind && state.pick.index === pick.index && state.pick.type === pick.type;
  state.pick = same ? null : pick;
  const p = state.pick;
  $("pickBanner").hidden = !p;
  if (p) {
    const text = p.kind === "meld"
      ? (p.type === "chi" ? "チー：順子のいちばん小さい牌を選んでください（例：3萬なら3萬4萬5萬）" : `${MELD_NAMES[p.type]}する牌を選んでください`)
      : `${p.kind === "ura" ? "裏ドラ" : "ドラ"}表示牌${p.index + 1}枚目を選んでください`;
    $("pickText").textContent = text;
    const list = p.kind === "ura" ? state.ura : state.dora;
    $("pickClear").hidden = p.kind === "meld" || !list[p.index];
    $("palette").scrollIntoView({ behavior: "smooth", block: "center" });
  }
  renderDora();
}

function usedTiles() {
  return [...state.hand, ...state.dora.filter(Boolean), ...state.ura.filter(Boolean), ...state.melds.flatMap((m) => m.tiles)];
}
function countOf(t) {
  return usedTiles().filter((x) => base5(x) === base5(t)).length;
}

function removeFromHand(tiles) {
  // 鳴いた牌のうち手牌から出した分を取り除く（無ければそのまま）
  tiles.forEach((t) => {
    let i = state.hand.indexOf(t);
    if (i < 0) i = state.hand.findIndex((x) => base5(x) === base5(t));
    if (i >= 0) state.hand.splice(i, 1);
  });
}

function addMeld(type, t) {
  if (state.melds.length >= 4) return flash("鳴きは4つまでです");
  const isKan = type === "kan" || type === "ankan";
  // カンは卓全体で1局4回まで（5回目はできない）
  if (isKan && tableKans() >= state.rules.max_kans) return flash(`この局はすでにカンが${tableKans()}回あります。カンは1局${state.rules.max_kans}回までです`);
  let tiles;
  if (type === "chi") {
    const n = +base5(t)[0], s = t[1];
    if (s === "z" || n > 7) return flash("チーは数牌の連続3枚です。いちばん小さい牌（1〜7）を選んでください");
    tiles = [base5(t), `${n + 1}${s}`, `${n + 2}${s}`];
    if (playersValue() === 3 && tiles.some((x) => SANMA_EXCLUDED.has(x))) return flash("三人麻雀では萬子の2〜8は使いません");
    // 手牌にある赤五は赤のまま使う
    tiles = tiles.map((x) => (x[0] === "5" && state.hand.includes("0" + x[1]) ? "0" + x[1] : x));
  } else {
    const n = isKan ? 4 : 3;
    tiles = Array(n).fill(base5(t));
    if (base5(t)[0] === "5" && t[1] !== "z" && state.rules.aka_dora && (t[0] === "0" || state.hand.includes("0" + t[1]))) tiles[0] = "0" + t[1];
  }
  const counts = {};
  [...state.dora.filter(Boolean), ...state.ura.filter(Boolean), ...state.melds.flatMap((m) => m.tiles), ...tiles].forEach((x) => (counts[base5(x)] = (counts[base5(x)] || 0) + 1));
  if (Object.values(counts).some((c) => c > 4)) return flash("その牌はもう4枚使っています");
  // 手牌から出す枚数：ポン2・チー2・明カン3・暗カン4（鳴いた牌は他家の捨て牌）
  const fromHand = { pon: 2, chi: 2, kan: 3, ankan: 4 }[type];
  if (type === "chi") removeFromHand(tiles.filter((x) => base5(x) !== base5(t)).slice(0, 2));
  else removeFromHand(tiles.slice(0, fromHand));
  const kansAfter = tableKans() + (isKan ? 1 : 0);
  state.melds.push({ type, tiles });
  if (isKan) $("tableKans").value = kansAfter;
  if (isKan) flash("カンしたのでドラ表示牌が1枚増えました。新しいドラ表示牌を選んでください", false);
  setManual(true);
  changed();
}

function addTile(t) {
  if (playersValue() === 3 && SANMA_EXCLUDED.has(t)) return flash("三人麻雀では萬子の2〜8は使いません");
  if (t[0] === "0" && !state.rules.aka_dora) return flash("このルールでは赤ドラ（赤五）はありません");
  const pick = state.pick;
  if (pick && pick.kind === "meld") {
    state.pick = null;
    $("pickBanner").hidden = true;
    return addMeld(pick.type, t);
  }
  if (countOf(t) >= 4) return flash("その牌はもう4枚使っています");
  if (t[0] === "0" && usedTiles().includes(t)) return flash("赤五は各色1枚までです");
  if (pick) {
    (pick.kind === "ura" ? state.ura : state.dora)[pick.index] = t;
    state.pick = null;
    $("pickBanner").hidden = true;
    return changed();
  }
  if (state.selected != null) {
    state.hand[state.selected] = t; // 選んだ牌を置き換える（認識の修正）
    state.selected = null;
    setManual(true);
    return changed();
  }
  if (state.hand.length >= maxHand()) return flash(`手牌は${maxHand()}枚までです` + (state.melds.length ? "（鳴きの分を除く）" : ""));
  state.hand.push(t);
  setManual(true);
  changed();
}

// ---------- ルール設定 ----------
const RULE_DEFAULTS = {
  preset: "mahjongsoul", aka_dora: true, kuitan: true, ippatsu: true, ura_dora: true, kan_dora: true, kan_ura: true,
  kiriage: false, kazoe_yakuman: true, double_yakuman: true, honba_4p: 300, honba_3p: 200,
  sanma_chi: false, sanma_nukidora: true, sanma_tsumo_son: true, max_kans: 4,
};
let RULE_LABELS = {
  aka_dora: "赤ドラ（赤五）", kuitan: "喰いタン", ippatsu: "一発", ura_dora: "裏ドラ", kan_dora: "カンドラ", kan_ura: "カン裏",
  kiriage: "切り上げ満貫", kazoe_yakuman: "数え役満", double_yakuman: "ダブル役満", sanma_chi: "三麻のチー",
  sanma_nukidora: "三麻の北抜きドラ", sanma_tsumo_son: "三麻のツモ損",
};
let PRESETS = { mahjongsoul: { ...RULE_DEFAULTS } };

function renderRules() {
  const r = state.rules;
  const list = $("ruleList");
  list.replaceChildren();
  Object.entries(RULE_LABELS).forEach(([key, label]) => {
    const l = document.createElement("label");
    l.className = "check";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = !!r[key];
    cb.addEventListener("change", () => setRule(key, cb.checked));
    l.append(cb, document.createTextNode(" " + label + "あり"));
    list.append(l);
  });
  $("honba4").value = r.honba_4p;
  $("honba3").value = r.honba_3p;
  $("preset").value = r.preset in PRESETS ? r.preset : "custom";
  $("presetName").textContent = r.preset === "mahjongsoul" ? "雀魂（段位戦）" : "カスタム";
}

function setRule(key, value) {
  state.rules = { ...state.rules, [key]: value, preset: "custom" };
  renderRules();
  applyPlayers();
  changed();
}

async function loadRulePresets() {
  try {
    const res = await fetch("/api/rules");
    const data = await res.json();
    PRESETS = data.presets;
    RULE_LABELS = data.labels;
    renderRules();
  } catch (_) { /* 既定値のまま */ }
}

function buildPalette() {
  const p = $("palette");
  const tiles = [];
  for (const s of "mps") for (let n = 1; n <= 9; n++) tiles.push(`${n}${s}`);
  for (let n = 1; n <= 7; n++) tiles.push(`${n}z`);
  tiles.push("0m", "0p", "0s");
  tiles.forEach((t) => {
    const el = tileEl(t, { button: true });
    el.dataset.tile = t;
    el.addEventListener("click", () => addTile(t));
    p.append(el);
  });
}

function flash(msg, isError = true) {
  const el = $("toast");
  el.textContent = msg;
  el.className = "toast show" + (isError ? " err" : "");
  clearTimeout(flash.t);
  flash.t = setTimeout(() => (el.className = "toast"), 3500);
}

// ---------- 分析 ----------
let analyzeTimer = null;
function changed() {
  renderHand();
  saveSettings();
  sendSettings();
  clearTimeout(analyzeTimer);
  if (state.manual || state.mode === "mock" || !state.stream) analyzeTimer = setTimeout(requestAnalysis, 120);
}

function sendSettings() {
  if (state.ws && state.ws.readyState === 1) {
    state.ws.send(JSON.stringify({ type: "settings", settings: readSettings() }));
  }
}

async function requestAnalysis() {
  if (!state.hand.length) return renderAnalysis(null);
  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tiles: state.hand, settings: readSettings() }),
    });
    const data = await res.json();
    if (!res.ok) return flash(data.detail || "分析できませんでした");
    renderAnalysis(data);
  } catch (e) {
    flash("サーバーに接続できません");
  }
}

function li(children, cls) {
  const el = document.createElement("li");
  if (cls) el.className = cls;
  children.forEach((c) => el.append(typeof c === "string" ? document.createTextNode(c) : c));
  return el;
}
function span(text, cls) {
  const s = document.createElement("span");
  s.textContent = text;
  if (cls) s.className = cls;
  return s;
}
function section(title, items) {
  const frag = document.createDocumentFragment();
  const h = document.createElement("h3");
  h.textContent = title;
  const ul = document.createElement("ul");
  ul.className = "list";
  items.forEach((i) => ul.append(i));
  frag.append(h, ul);
  return frag;
}

function shortPay(r) {
  if (!r || !r.ok) return null;
  return `${r.total.toLocaleString()}点`;
}

function waitItem(w) {
  let pts;
  if (w.ron || w.tsumo) {
    const ron = shortPay(w.ron), tsu = w.tsumo && w.tsumo.ok ? w.tsumo.payment.replace(/^ツモ /, "").replace(/（.*$/, "") : null;
    const box = document.createElement("span");
    box.className = "pts two";
    box.append(span(ron ? `ロン ${ron}` : "ロン 役なし"), document.createElement("br"), span(tsu ? `ツモ ${tsu}` : "ツモ 役なし", "sub"));
    pts = box;
  } else {
    pts = span(w.ok ? `${w.payment}${w.level ? "（" + w.level + "）" : ""}` : "役なし", "pts");
  }
  let meta = w.ok ? `${w.han}翻${w.fu ? w.fu + "符" : ""}${w.level ? " " + w.level : ""} ${w.yaku.join("・")}` : (w.error || "");
  if (w.riichi_needed) meta = "※リーチが必要（役なし）　" + meta;
  if (w.nima_ok === false) meta = "※二麻では役満でないのでアガれません　" + meta;
  const body = document.createElement("div");
  body.append(span(`残り${w.remaining}枚`, "meta nowrap"), document.createElement("br"), span(meta, "meta"));
  return li([tilesInline([w.tile]), body, pts], w.nima_ok === false ? "no-nima" : "");
}

// 親・子を入れ替えた場合の点数を、参考としてカードに足す
function addOtherPay(card, o, kind) {
  if (!o || !o.ok) return;
  const ref = document.createElement("div");
  ref.className = "other-pay";
  const who = o.dealer ? "親" : "子";
  ref.append(span(`参考：${who}の${kind}なら ${o.total.toLocaleString()}点`, "meta"));
  const ul = document.createElement("ul");
  (o.pays || []).forEach((p) => {
    const l = document.createElement("li");
    l.textContent = `${p.who} ${p.points.toLocaleString()}点`;
    ul.append(l);
  });
  ref.append(ul);
  card.insertBefore(ref, card.querySelector(".hanfu"));
}

// アガリ形の点数（ロン・ツモの片方）を1枚のカードにする
function scoreCard(r, title, selected) {
  const box = document.createElement("div");
  box.className = "score-box" + (selected ? " selected" : "");
  const h = document.createElement("div");
  h.className = "score-title";
  h.textContent = title;
  box.append(h);
  if (!r.ok) {
    box.append(span(r.error, "err"));
    return box;
  }
  box.append(span(`${r.total.toLocaleString()}点`, "big"));
  const pays = document.createElement("ul");
  pays.className = "pays";
  (r.pays || []).forEach((p) => {
    const l = document.createElement("li");
    l.textContent = `${p.who} ${p.points.toLocaleString()}点`;
    pays.append(l);
  });
  box.append(pays);
  box.append(span(`${r.han}翻${r.fu ? " " + r.fu + "符" : ""}${r.level ? "　" + r.level : ""}`, "hanfu"));
  const ul = document.createElement("ul");
  r.yaku.forEach((y) => {
    const l = document.createElement("li");
    l.textContent = `${y.name}${y.yakuman ? "（役満）" : `　${y.han}翻`}`;
    ul.append(l);
  });
  box.append(ul);
  if (r.fu_details && r.fu_details.length) {
    const d = document.createElement("details");
    d.className = "fu";
    const sm = document.createElement("summary");
    sm.textContent = `符の計算（${r.fu}符）`;
    const t = document.createElement("table");
    r.fu_details.forEach((f) => {
      const tr = t.insertRow();
      tr.insertCell().textContent = f.name;
      tr.insertCell().textContent = `${f.fu}符`;
    });
    const sum = t.insertRow();
    sum.className = "sum";
    sum.insertCell().textContent = r.fu_raw !== r.fu ? `合計 ${r.fu_raw}符 → 10符単位に切り上げ` : "合計";
    sum.insertCell().textContent = `${r.fu}符`;
    d.append(sm, t);
    if (r.han >= 5) d.append(span("※5翻以上（満貫以上）は、符に関係なく点数が決まります", "meta"));
    box.append(d);
  }
  return box;
}

function renderAnalysis(a) {
  state.analysis = a;
  renderGlass();
  ["score", "waits", "discards", "hints"].forEach((id) => $(id).replaceChildren());
  if (!a) {
    $("message").textContent = "手牌を映すか入力すると、ここに「何を切るか」「狙える役」「点数」が出ます。";
    return;
  }
  $("message").textContent = a.message || a.shanten_label || "";

  if (a.scores) {
    const wrap = document.createElement("div");
    wrap.className = "score-pair";
    const me = a.scores.dealer ? "親" : "子";
    // 親か子かで点数が変わる（親は子の1.5倍）。ここで切り替えられるようにする
    const sw = document.createElement("div");
    sw.className = "dealer-switch";
    sw.append(span("あなたは", "meta"));
    [["親", "east"], ["子", "south"]].forEach(([label, wind]) => {
      const b = document.createElement("button");
      b.textContent = label === "親" ? "親（東）" : (playersValue() === 2 ? "子（南）" : playersValue() === 3 ? "子（南・西）" : "子（南・西・北）");
      b.setAttribute("aria-pressed", String(label === me));
      b.addEventListener("click", () => {
        if (label === me) return;
        $("seatWind").value = wind;
        changed();
      });
      sw.append(b);
    });
    $("score").append(sw);
    const ronCard = scoreCard(a.scores.ron, `ロンなら（${me}のロン）`, a.scores.selected === "ron");
    const tsumoCard = scoreCard(a.scores.tsumo, `ツモなら（${me}のツモ）`, a.scores.selected === "tsumo");
    addOtherPay(ronCard, a.scores.ron_other, "ロン");
    addOtherPay(tsumoCard, a.scores.tsumo_other, "ツモ");
    wrap.append(ronCard, tsumoCard);
    $("score").append(wrap);
  } else if (a.score) {
    $("score").append(scoreCard(a.score, a.score.tsumo ? "ツモ" : "ロン", true));
  }

  if (a.waits && a.waits.length) {
    $("waits").append(section("待ち牌とアガリ点数", a.waits.map(waitItem)));
  }

  if (a.discards && a.discards.length && !a.score) {
    const items = a.discards.slice(0, 5).map((o, i) => {
      const label = o.shanten === 0 ? "テンパイ" : `${o.shanten}向聴`;
      const effective = o.effective.slice(0, 8).map((e) => e.tile);
      const item = li([tilesInline([o.discard]), span(`切り → ${label}`), span(`受け入れ ${o.ukeire}枚`, "pts")], i === 0 ? "best" : "");
      if (effective.length) item.append(document.createElement("br"));
      const wrap = document.createElement("div");
      wrap.style.flexBasis = "100%";
      wrap.append(span("有効牌 ", "meta"), tilesInline(effective));
      if (effective.length) { item.style.flexWrap = "wrap"; item.append(wrap); }
      return item;
    });
    $("discards").append(section("何を切る？（おすすめ順）", items));
    const tenpai = a.discards.find((o) => o.waits);
    if (tenpai) {
      $("waits").append(section(`「${tileName(tenpai.discard)}」切りでテンパイ。待ちと点数`, tenpai.waits.map(waitItem)));
    }
  }

  if (a.effective && a.effective.length && !a.waits) {
    $("waits").append(section(`有効牌（受け入れ ${a.ukeire}枚）`, [li([tilesInline(a.effective.map((e) => e.tile))])]));
  }

  if (a.hints && a.hints.length) {
    const items = a.hints.map((h) => {
      const d = span(h.distance === 0 ? "成立/可能" : `あと${h.distance}`, "dist" + (h.distance === 0 ? " ok" : ""));
      const body = document.createElement("div");
      body.append(span(`${h.name}　${h.han}`), document.createElement("br"), span(h.note, "meta"));
      return li([d, body], "hint" + (h.yakuman ? " yakuman" : ""));
    });
    const sec = section(a.nima ? "狙える役満（二麻は役満だけアガれます）" : "狙える役", items);
    $("hints").append(sec);
    if (a.nima) {
      const b = document.createElement("button");
      b.className = "small-inline";
      b.textContent = "役満一覧を見る";
      b.addEventListener("click", openYakuman);
      $("hints").append(b);
    }
  } else if (a.nima) {
    $("hints").append(section("狙える役満", [li([span("いまの手牌から近い役満はまだありません。字牌や1・9の牌、同じ牌を集めてみましょう", "meta")])]));
  }
}

// ---------- 役満一覧 ----------
let yakumanCache = null;
async function openYakuman() {
  const dlg = $("yakumanDialog");
  if (!yakumanCache) {
    try {
      yakumanCache = (await (await fetch("/api/yakuman")).json()).yakuman;
    } catch (_) {
      flash("役満一覧を読み込めませんでした");
      return;
    }
    const list = $("yakumanList");
    list.replaceChildren();
    yakumanCache.forEach((y) => {
      const item = document.createElement("li");
      const name = document.createElement("div");
      name.className = "yn";
      name.textContent = y.name;
      const r = document.createElement("small");
      r.textContent = y.reading;
      name.append(r);
      item.append(name, span(y.cond, "cond"), span(y.desc, "meta"));
      if (y.example && y.example.length) item.append(tilesInline(y.example));
      list.append(item);
    });
  }
  if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
}
document.querySelectorAll(".yakuman-btn").forEach((b) => b.addEventListener("click", openYakuman));
$("yakumanClose").addEventListener("click", () => $("yakumanDialog").close());

// ---------- スマートグラス表示 ----------
// スマホの画面がそのままグラスに映る（ミラーリング）。黒はグラスでは透明に見えるので、背景は真っ黒にし、
// 手牌と「何を切るか・狙える役」だけを大きく出す。点数はタップしたときだけ。端末ごとに設定を覚える。
const GLASS_KEY = "mj-glasses";

function setGlasses(on) {
  state.glasses = on;
  document.body.classList.toggle("glasses", on);
  $("glassView").hidden = !on;
  try { localStorage.setItem(GLASS_KEY, on ? "1" : "0"); } catch (e) { /* 保存できない環境 */ }
  if (on) {
    state.glassScore = false;
    keepAwake(true);
    renderGlass();
  } else {
    keepAwake(false);
    drawBoxes([]);
  }
}

// グラス表示中は画面が消えないようにする（対応ブラウザのみ）
async function keepAwake(on) {
  try {
    if (on && navigator.wakeLock && !state.wakeLock) state.wakeLock = await navigator.wakeLock.request("screen");
    if (!on && state.wakeLock) { await state.wakeLock.release(); state.wakeLock = null; }
  } catch (e) { state.wakeLock = null; }
}

function gText(cls, text) {
  const d = document.createElement("div");
  d.className = cls;
  d.textContent = text;
  return d;
}

function renderGlass() {
  if (!state.glasses) return;
  const a = state.analysis;
  // 手牌（鳴きは小さく右に）
  const hand = $("gHand");
  hand.replaceChildren();
  state.hand.forEach((t) => hand.append(tileEl(t)));
  if (state.melds.length) {
    const m = document.createElement("span");
    m.className = "g-melds";
    state.melds.forEach((x) => m.append(tilesInline(x.tiles)));
    hand.append(m);
  }
  if (!state.hand.length) hand.append(gText("g-empty", "手牌をカメラに映してください"));

  // いちばん大事な一言：何を切るか／待ち／アガリ
  const main = $("gMain");
  main.replaceChildren();
  const sub = $("gSub");
  sub.replaceChildren();
  const score = $("gScore");
  score.replaceChildren();
  if (a) {
    if (a.scores || a.score) {
      main.append(gText("g-big ok", "アガリ！"));
      const sc = a.scores ? a.scores[a.scores.selected] : a.score;
      if (sc && sc.ok) main.append(gText("g-line", sc.yaku.map((y) => y.name).join("・")));
      fillGlassScore(score, a);
    } else if (a.waits && a.waits.length) {
      const line = document.createElement("div");
      line.className = "g-line";
      line.append(gText("g-big ok", "テンパイ　待ち"), tilesInline(a.waits.map((w) => w.tile)));
      main.append(line);
      fillGlassScore(score, a);
    } else if (a.discards && a.discards.length) {
      const best = a.discards[0];
      const label = best.shanten === 0 ? "テンパイ" : `${best.shanten}向聴`;
      const line = document.createElement("div");
      line.className = "g-line";
      line.append(tilesInline([best.discard]), gText("g-big", `を切る → ${label}（受け入れ${best.ukeire}枚）`));
      main.append(line);
      const tenpai = a.discards.find((o) => o.waits);
      if (tenpai) fillGlassScore(score, { waits: tenpai.waits });
    } else {
      main.append(gText("g-line", a.message || a.shanten_label || ""));
    }
    // 狙える役（成立しているもの・近いものを3つまで）
    (a.hints || []).slice(0, 3).forEach((h) => {
      sub.append(gText("g-hint" + (h.distance === 0 ? " ok" : ""), `${h.distance === 0 ? "◎" : `あと${h.distance}:`} ${h.name}`));
    });
  }
  if (!score.childNodes.length) score.append(gText("g-line", "点数はアガリ・テンパイのときに出ます"));
  score.hidden = !state.glassScore;
  $("gTap").textContent = state.glassScore ? "もう一度タップで点数を隠す" : "画面をタップすると点数を表示";
  $("gStatus").textContent = state.locked ? "確定済み（次の手牌は「読み直す」）" : state.stream ? $("camStatus").textContent : "カメラ停止中";
  $("gCam").textContent = state.stream ? "カメラ停止" : (state.hand.length ? "読み直す" : "カメラ開始");
  $("gOk").hidden = !(state.stream && state.hand.length);
}

function fillGlassScore(box, a) {
  if (a.scores) {
    [["ロン", a.scores.ron], ["ツモ", a.scores.tsumo]].forEach(([k, r]) => {
      if (!r || !r.ok) return box.append(gText("g-line", `${k}：${r ? r.error : "—"}`));
      const pays = (r.pays || []).map((p) => `${p.who} ${p.points.toLocaleString()}`).join(" / ");
      box.append(gText("g-line", `${k} ${r.total.toLocaleString()}点（${r.han}翻${r.fu ? r.fu + "符" : ""}${r.level ? " " + r.level : ""}）${pays}`));
    });
  } else if (a.waits) {
    a.waits.forEach((w) => {
      const ron = w.ron && w.ron.ok ? `ロン ${w.ron.total.toLocaleString()}` : "ロン 役なし";
      const tsu = w.tsumo && w.tsumo.ok ? `ツモ ${w.tsumo.payment.replace(/^ツモ /, "").replace(/（.*$/, "")}` : "";
      box.append(gText("g-line", `${tileName(w.tile)}（残り${w.remaining}）　${ron}　${tsu}${w.riichi_needed ? "　※要リーチ" : ""}`));
    });
  }
}

// ---------- WebSocket ----------
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = "arraybuffer";
  state.ws = ws;
  ws.onopen = () => sendSettings();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    switch (msg.type) {
      case "hello":
        setMode(msg.mode, msg.kinds);
        break;
      case "detection":
        state.waiting = false;
        onDetection(msg);
        break;
      case "analysis":
        if (!state.manual) renderAnalysis(msg.analysis);
        break;
      case "taught":
        state.kinds = msg.kinds;
        setMode(state.mode, msg.kinds);
        setManual(false);
        flash(`${msg.count}枚を覚えました（登録 ${msg.kinds}種類）。自動認識に戻ります`, false);
        break;
      case "error":
        state.waiting = false;
        flash(msg.message);
        break;
    }
  };
  ws.onclose = () => {
    state.waiting = false;
    $("mode").textContent = "再接続中…";
    setTimeout(connect, 2000);
  };
}

const HINTS = {
  dark: "暗すぎます。明るい場所で映してください",
  glare: "照明が反射して白く飛んでいます。スマホの角度を少し変えてください",
  none: "牌が見つかりません。緑の枠の中に、手牌を横一列に入れてください",
  small: "牌が小さく写っています。少し近づけるか、手牌が枠の幅いっぱいになるようにしてください",
  blurry: "ピントが合っていません。少し離すか、画面の牌をタップしてピントを合わせてください",
  partial: "手牌の一部しか写っていません。13〜14枚すべてが枠に入るようにしてください",
};

function onDetection(msg) {
  drawBoxes(msg.detections || []);
  if ($("debugChk").checked) {
    const dets = msg.detections || [];
    const px = dets.length ? Math.round(dets.map((d) => d.box[3] - d.box[1]).sort((a, b) => a - b)[dets.length >> 1] * grab.height) : 0;
    $("debugInfo").hidden = false;
    $("debugInfo").textContent = `送信 ${grab.width}×${grab.height} / 検出 ${dets.length}枚 / 牌の高さ 約${px}px（40px 以上が目安） / 見本 ${state.kinds}種 / ヒント ${(msg.hints || []).join(",") || "なし"}`;
  } else $("debugInfo").hidden = true;
  const status = $("camStatus");
  const hint = (msg.hints || []).map((h) => HINTS[h]).find(Boolean);
  status.classList.toggle("warn", Boolean(hint || msg.unknown));
  if (hint) status.textContent = (msg.seen ? `${msg.seen}枚を検出。` : "") + hint;
  else if (msg.unknown) status.textContent = `${msg.seen}枚を読み取り中（自信のない牌 ${msg.unknown}枚は点線で表示。違っていたらタップして直せます）`;
  else status.textContent = `${msg.seen}枚を認識中`;
  if (state.locked) return;  // 「OK」で確定済み（カメラ停止の直前に届いた結果は無視）
  if (state.glasses) setTimeout(renderGlass, 0);
  updateSteps(msg.seen > 0 && state.hand.length > 0);
  $("okBtn").hidden = !(state.stream && state.hand.length);
  if (state.manual) return;
  if (msg.hand && JSON.stringify(msg.hand) !== JSON.stringify(state.hand)) {
    // 手牌が変わった（プレイヤーがアシストと違う牌を切った場合も含む）→ 読み直して分析を更新
    state.hand = msg.hand.slice(0, maxHand());
    const dets = msg.detections || [];
    state.unsure = new Set(dets.length === msg.hand.length ? dets.map((d, i) => (d.tile ? -1 : i)).filter((i) => i >= 0) : []);
    state.selected = null;
    state.winTile = null;
    renderHand();
    if (msg.analysis) renderAnalysis(msg.analysis); else requestAnalysis();
  } else if (msg.unknown && msg.seen && !state.hand.length) {
    // まだ何も覚えていない：検出枚数ぶんの空欄を出し、入力を促す
    $("message").textContent = "この牌の見本がまだありません。映っている牌を左から順に入力して「この並びで覚える」を押してください";
  }
}

function setMode(mode, kinds) {
  state.mode = mode;
  state.kinds = kinds || 0;
  const label = { yolo: "AI認識", template: `自動認識（見本${state.kinds}/37種）`, mock: "手動入力モード" }[mode] || mode;
  $("mode").textContent = label;
  $("modeNote").hidden = mode !== "template" || state.kinds >= 37;
}

// ---------- カメラ ----------
const video = $("video");
const overlay = $("overlay");
const grab = document.createElement("canvas");
const CAM_KEY = "mj-camera";

// 手牌を読み取る枠（映像の中の横長の帯）。縦持ちでも横持ちでも、映像の横幅いっぱいを使う
function guideBand() {
  const w = video.videoWidth, h = video.videoHeight;
  const bh = Math.min(h, Math.round(Math.max(h * 0.22, w * 0.32)));
  return { x: Math.round(w * 0.02), y: Math.round((h - bh) / 2), w: Math.round(w * 0.96), h: bh };
}

async function openCamera(deviceId) {
  const video = deviceId
    ? { deviceId: { exact: deviceId }, width: { ideal: 1920 }, height: { ideal: 1080 } }
    : { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } };
  return navigator.mediaDevices.getUserMedia({ video, audio: false });
}

async function toggleCamera() {
  if (state.stream) return stopCamera();
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return flash("このブラウザではカメラを使えません（HTTPS で開いてください）");
  }
  let saved = null;
  try { saved = localStorage.getItem(CAM_KEY); } catch (e) { /* 保存できない環境 */ }
  try {
    try {
      state.stream = await openCamera(saved);
    } catch (e) {
      if (!saved) throw e;
      state.stream = await openCamera(null);  // 前回のカメラが無い → 既定の背面カメラ
    }
    video.srcObject = state.stream;
    video.play().catch(() => {});  // 明示的に再生（画面外でも止まらないように）
    setLocked(false);
    setManual(false);
    $("cameraHint").hidden = true;
    $("cameraBtn").textContent = "カメラ停止";
    $("mode").classList.add("live");
    $("camControls").hidden = false;
    video.onloadedmetadata = fitViewport;
    await setupCameraControls(!saved);
    updateSteps(false);
    $("viewport").scrollIntoView({ behavior: "smooth", block: "start" });
    requestAnimationFrame(loop);
  } catch (e) {
    flash("カメラを起動できませんでした。ブラウザの設定でカメラを許可してください");
  }
}

// 背面カメラが複数あれば選べるようにする（超広角があれば最初はそれを使う）。ズームできる機種は一番広く
async function setupCameraControls(autoWide) {
  const track = state.stream.getVideoTracks()[0];
  const current = track.getSettings ? track.getSettings().deviceId : null;
  let cams = [];
  try {
    cams = (await navigator.mediaDevices.enumerateDevices())
      .filter((d) => d.kind === "videoinput" && !/front|前面|user|facetime/i.test(d.label));
  } catch (e) { cams = []; }
  const sel = $("camSelect");
  sel.innerHTML = "";
  cams.forEach((d, i) => {
    const o = document.createElement("option");
    o.value = d.deviceId;
    o.textContent = d.label ? d.label.replace(/camera/i, "カメラ") : `カメラ ${i + 1}`;
    if (/ultra ?wide|超広角/i.test(d.label)) o.textContent += "（広く写る）";
    o.selected = d.deviceId === current;
    sel.append(o);
  });
  $("camSelectBox").hidden = cams.length < 2;
  const wide = cams.find((d) => /ultra ?wide|超広角/i.test(d.label));
  if (autoWide && wide && wide.deviceId !== current) {
    return switchCamera(wide.deviceId, false);
  }
  setupZoom(track);
}

function setupZoom(track) {
  const caps = track.getCapabilities ? track.getCapabilities() : {};
  // ライト（対応機種のみ）
  $("torchBtn").hidden = !caps.torch;
  $("torchBtn").setAttribute("aria-pressed", "false");
  // ピント合わせ（連続オートフォーカスに対応していれば使う）
  const modes = caps.focusMode || [];
  $("focusBtn").hidden = !modes.length;
  if (modes.includes("continuous")) track.applyConstraints({ advanced: [{ focusMode: "continuous" }] }).catch(() => {});
  const box = $("zoomBox"), input = $("zoom");
  if (!caps.zoom) { box.hidden = true; return; }
  box.hidden = false;
  input.min = caps.zoom.min; input.max = caps.zoom.max; input.step = caps.zoom.step || 0.1;
  input.value = caps.zoom.min;  // 一番広く写す
  $("zoomVal").textContent = `${(+input.value).toFixed(1)}倍`;
  track.applyConstraints({ advanced: [{ zoom: +input.value }] }).catch(() => {});
}

async function switchCamera(deviceId, remember = true) {
  if (state.stream) state.stream.getTracks().forEach((t) => t.stop());
  try {
    state.stream = await openCamera(deviceId);
  } catch (e) {
    flash("このカメラは使えませんでした");
    state.stream = await openCamera(null);
  }
  video.srcObject = state.stream;
  video.play().catch(() => {});  // 明示的に再生（画面外でも止まらないように）
  if (remember) { try { localStorage.setItem(CAM_KEY, deviceId); } catch (e) { /* 無視 */ } }
  $("camSelect").value = deviceId;
  setupZoom(state.stream.getVideoTracks()[0]);
}

// 映像の縦横比に合わせて表示枠の形を変える（縦持ちなら縦長で表示）
function fitViewport() {
  const vw = video.videoWidth, vh = video.videoHeight;
  if (vw && vh) $("viewport").style.aspectRatio = `${vw} / ${vh}`;
  drawBoxes([]);
}

function stopCamera() {
  state.stream.getTracks().forEach((t) => t.stop());
  state.stream = null;
  video.srcObject = null;
  $("cameraHint").hidden = false;
  $("cameraBtn").textContent = state.hand.length ? "読み直す（カメラ再開）" : "カメラ開始";
  $("okBtn").hidden = true;
  $("mode").classList.remove("live");
  $("camControls").hidden = true;
  $("viewport").style.aspectRatio = "";
  overlay.getContext("2d").clearRect(0, 0, overlay.width, overlay.height);
  updateSteps(false);
  renderGlass();
}

function loop(ts) {
  if (!state.stream) return;
  const ready = video.readyState >= 2 && state.ws && state.ws.readyState === 1;
  if (ready && state.mode !== "mock" && !state.waiting && ts - state.lastSent > FRAME_INTERVAL_MS) {
    sendFrame();
    state.lastSent = ts;
  }
  requestAnimationFrame(loop);
}

// 枠の部分だけを切り出して送る（縮小しすぎないので、小さく写った牌も読みやすい）
function sendFrame() {
  const b = guideBand();
  const scale = Math.min(1, 1280 / b.w);
  grab.width = Math.round(b.w * scale);
  grab.height = Math.round(b.h * scale);
  grab.getContext("2d").drawImage(video, b.x, b.y, b.w, b.h, 0, 0, grab.width, grab.height);
  state.waiting = true;
  grab.toBlob((blob) => {
    if (!blob || !state.ws || state.ws.readyState !== 1) { state.waiting = false; return; }
    blob.arrayBuffer().then((buf) => state.ws.send(buf));
  }, "image/jpeg", 0.8);
  // 応答が来ないまま固まらないよう、一定時間で次のフレームを許可する
  setTimeout(() => { state.waiting = false; }, 3000);
}

// 映像の上に、読み取り枠と検出した牌の枠を描く（検出枠の座標は読み取り枠の中の 0〜1）
function drawBoxes(dets) {
  const rect = overlay.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  overlay.width = rect.width * dpr;
  overlay.height = rect.height * dpr;
  const ctx = overlay.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  const vw = video.videoWidth, vh = video.videoHeight;
  if (!vw || !vh || !state.stream) return;
  const s = Math.min(rect.width / vw, rect.height / vh);
  const dw = vw * s, dh = vh * s, ox = (rect.width - dw) / 2, oy = (rect.height - dh) / 2;
  const b = guideBand();
  const gx = ox + b.x * s, gy = oy + b.y * s, gw = b.w * s, gh = b.h * s;
  // 枠の外を暗くする
  ctx.fillStyle = "rgba(0,0,0,.45)";
  ctx.fillRect(ox, oy, dw, gy - oy);
  ctx.fillRect(ox, gy + gh, dw, oy + dh - gy - gh);
  ctx.strokeStyle = "#39ff88";
  ctx.lineWidth = 3;
  ctx.setLineDash([10, 6]);
  ctx.strokeRect(gx, gy, gw, gh);
  ctx.setLineDash([]);
  ctx.font = "bold 13px sans-serif";
  if (!dets.length) {
    const t = "ここに手牌を横一列に";
    ctx.fillStyle = "rgba(0,0,0,.6)";
    ctx.fillRect(gx + 6, gy + 6, ctx.measureText(t).width + 10, 20);
    ctx.fillStyle = "#fff";
    ctx.fillText(t, gx + 11, gy + 21);
  }
  ctx.lineWidth = 2;
  ctx.font = "bold 12px sans-serif";
  dets.forEach((d, i) => {
    const [x1, y1, x2, y2] = d.box;
    const x = gx + x1 * gw, y = gy + y1 * gh, bw = (x2 - x1) * gw, bh = (y2 - y1) * gh;
    ctx.strokeStyle = d.tile ? "#39ff88" : "#ffb020";
    ctx.strokeRect(x, y, bw, bh);
    let label = d.tile ? tileName(d.tile) : "？";
    if ($("debugChk").checked) label += ` ${Math.round((d.confidence || 0) * 100)}%`;
    // 隣どうしの文字が重ならないよう、上下交互に書く
    const ly = i % 2 ? y + bh + 16 : y;
    ctx.fillStyle = "rgba(0,0,0,.65)";
    ctx.fillRect(x, ly - 16, ctx.measureText(label).width + 6, 16);
    ctx.fillStyle = "#fff";
    ctx.fillText(label, x + 3, ly - 4);
  });
}

// 使い方の「いまどのステップか」を強調する
function updateSteps(recognized) {
  const step = state.locked ? 3 : !state.stream ? 1 : recognized ? 3 : 2;
  [1, 2, 3].forEach((i) => $(`step${i}`).classList.toggle("now", i === step));
}

// 「OK」：いま並んでいる手牌で確定。カメラを止め、スマホを動かしても手牌が変わらないようにする
function confirmHand() {
  if (!state.hand.length) return flash("まだ手牌が読めていません");
  setLocked(true);
  if (state.stream) stopCamera();
  state.unsure = null;
  renderHand();
  requestAnalysis();
  updateSteps(true);
  flash("手牌を確定しました。次のツモ・打牌のあとは「読み直す」を押してください", false);
  $("result").scrollIntoView({ behavior: "smooth", block: "start" });
}

function setLocked(v) {
  state.locked = v;
  $("lockBadge").hidden = !v;
  $("viewport").hidden = v;  // 確定中は映像の枠を畳んで、手牌とアシストを見やすくする
  if (v) $("camStatus").textContent = "手牌を確定しました（カメラ停止中）。次の手牌は「読み直す」で映します。";
}

// 手で修正中は自動更新を止める。「自動に戻す」で再開
function setManual(v) {
  state.manual = v;
  if (v) state.unsure = null;
  $("autoBtn").hidden = !v;
  $("teachBtn").hidden = !(v && state.mode === "template");
  $("manualBadge").hidden = !v;
}

// ---------- イベント ----------
function init() {
  state.rules = { ...RULE_DEFAULTS };
  loadSettings();
  buildPalette();
  renderRules();
  loadRulePresets();
  applyPlayers();
  renderHand();
  connect();
  $("cameraBtn").addEventListener("click", toggleCamera);
  $("okBtn").addEventListener("click", confirmHand);
  $("glassBtn").addEventListener("click", () => setGlasses(true));
  $("gExit").addEventListener("click", () => setGlasses(false));
  $("gCam").addEventListener("click", () => toggleCamera().then(renderGlass));
  $("gOk").addEventListener("click", () => { confirmHand(); renderGlass(); });
  $("gFrame").addEventListener("click", () => { state.glassScore = !state.glassScore; renderGlass(); });
  document.addEventListener("visibilitychange", () => { if (state.glasses && !document.hidden) keepAwake(true); });
  try { if (localStorage.getItem(GLASS_KEY) === "1") setGlasses(true); } catch (e) { /* 保存できない環境 */ }
  $("camSelect").addEventListener("change", (e) => switchCamera(e.target.value));
  $("zoom").addEventListener("input", (e) => {
    const track = state.stream && state.stream.getVideoTracks()[0];
    $("zoomVal").textContent = `${(+e.target.value).toFixed(1)}倍`;
    if (track) track.applyConstraints({ advanced: [{ zoom: +e.target.value }] }).catch(() => {});
  });
  window.addEventListener("resize", () => drawBoxes([]));
  $("torchBtn").addEventListener("click", () => {
    const track = state.stream && state.stream.getVideoTracks()[0];
    if (!track) return;
    const on = $("torchBtn").getAttribute("aria-pressed") !== "true";
    track.applyConstraints({ advanced: [{ torch: on }] })
      .then(() => $("torchBtn").setAttribute("aria-pressed", String(on)))
      .catch(() => flash("この機種ではライトを使えませんでした"));
  });
  $("focusBtn").addEventListener("click", () => {
    const track = state.stream && state.stream.getVideoTracks()[0];
    if (!track) return;
    // 一度だけピントを合わせ直し、そのあと連続オートフォーカスに戻す
    track.applyConstraints({ advanced: [{ focusMode: "single-shot" }] })
      .catch(() => {})
      .finally(() => setTimeout(() => track.applyConstraints({ advanced: [{ focusMode: "continuous" }] }).catch(() => {}), 800));
    flash("ピントを合わせ直しました", false);
  });
  // 読み取り枠の映像をそのまま画像で保存（うまく読めないときに、開発者に送って調べてもらう用。サーバーには保存しない）
  $("saveFrameBtn").addEventListener("click", () => {
    if (!state.stream || !video.videoWidth) return flash("カメラを開始してから押してください");
    const b = guideBand();
    const c = document.createElement("canvas");
    c.width = b.w; c.height = b.h;
    c.getContext("2d").drawImage(video, b.x, b.y, b.w, b.h, 0, 0, b.w, b.h);
    c.toBlob((blob) => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `mahjong-frame-${new Date().toISOString().replace(/[:.]/g, "-")}.jpg`;
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      flash("画像を保存しました（スマホの写真またはダウンロードに入ります）", false);
    }, "image/jpeg", 0.92);
  });
  updateSteps(false);
  try {
    const box = $("guideBox");
    if (localStorage.getItem("mj-guide-closed") === "1") box.open = false;
    box.addEventListener("toggle", () => localStorage.setItem("mj-guide-closed", box.open ? "0" : "1"));
  } catch (e) { /* 保存できない環境 */ }
  $("autoBtn").addEventListener("click", () => { setManual(false); flash("自動認識に戻しました", false); });
  $("teachBtn").addEventListener("click", () => {
    if (!state.stream) return flash("カメラを開始して、入力した手牌と同じ並びを映してください");
    if (!state.hand.length) return flash("映っている牌を左から順に入力してください");
    state.ws.send(JSON.stringify({ type: "teach", tiles: state.hand }));
  });
  $("sortBtn").addEventListener("click", () => {
    const win = state.winTile != null ? state.hand[state.winTile] : null;
    state.hand.sort((a, b) => tileOrder(a) - tileOrder(b));
    state.winTile = win ? state.hand.indexOf(win) : null;
    state.selected = null;
    changed();
  });
  $("clearBtn").addEventListener("click", () => {
    state.hand = []; state.dora = []; state.ura = []; state.melds = []; state.selected = null; state.winTile = null;
    $("tableKans").value = 0; changed();
  });
  $("demoBtn").addEventListener("click", () => {
    if (playersValue() === 2) {
      // 二麻の例：大三元まであと少しの配牌
      state.hand = ["5z", "5z", "6z", "6z", "6z", "7z", "2m", "3m", "4m", "1p", "2p", "3p", "9s", "9s"];
      state.dora = ["1m"];
    } else if (playersValue() === 3) {
      state.hand = ["1m", "1m", "0p", "6p", "7p", "2p", "3p", "4p", "3s", "4s", "6s", "7s", "8s", "4z"];
      state.dora = ["1m"];
    } else {
      state.hand = ["2m", "3m", "4m", "0p", "6p", "7p", "3s", "4s", "6s", "7s", "8s", "5z", "5z", "1z"];
      state.dora = ["1m"];
    }
    state.melds = []; state.ura = [];
    state.selected = null; state.winTile = null;
    setManual(true); changed();
  });
  $("removeTileBtn").addEventListener("click", () => {
    if (state.selected == null) return;
    state.hand.splice(state.selected, 1);
    setManual(true);
    if (state.winTile === state.selected) state.winTile = null;
    else if (state.winTile != null && state.winTile > state.selected) state.winTile--;
    state.selected = null;
    changed();
  });
  $("winTileBtn").addEventListener("click", () => {
    if (state.selected == null) return;
    state.winTile = state.selected;
    state.selected = null;
    changed();
  });
  SETTING_IDS.forEach((id) => $(id).addEventListener("change", changed));
  $("tableKans").addEventListener("change", changed);
  document.querySelectorAll("[data-meld]").forEach((b) =>
    b.addEventListener("click", () => startPick({ kind: "meld", type: b.dataset.meld })));
  $("pickCancel").addEventListener("click", () => startPick(state.pick));
  $("pickClear").addEventListener("click", () => {
    const p = state.pick;
    if (p) (p.kind === "ura" ? state.ura : state.dora)[p.index] = null;
    startPick(p);
    changed();
  });
  $("preset").addEventListener("change", () => {
    const v = $("preset").value;
    if (PRESETS[v]) state.rules = { ...PRESETS[v], preset: v };
    else state.rules = { ...state.rules, preset: "custom" };
    renderRules(); applyPlayers(); changed();
  });
  $("honba4").addEventListener("change", () => setRule("honba_4p", Math.max(0, parseInt($("honba4").value, 10) || 0)));
  $("honba3").addEventListener("change", () => setRule("honba_3p", Math.max(0, parseInt($("honba3").value, 10) || 0)));
  document.querySelectorAll("input[name=players]").forEach((el) =>
    el.addEventListener("change", () => { applyPlayers(); changed(); }));
  window.addEventListener("resize", () => drawBoxes([]));
  $("torchBtn").addEventListener("click", () => {
    const track = state.stream && state.stream.getVideoTracks()[0];
    if (!track) return;
    const on = $("torchBtn").getAttribute("aria-pressed") !== "true";
    track.applyConstraints({ advanced: [{ torch: on }] })
      .then(() => $("torchBtn").setAttribute("aria-pressed", String(on)))
      .catch(() => flash("この機種ではライトを使えませんでした"));
  });
  $("focusBtn").addEventListener("click", () => {
    const track = state.stream && state.stream.getVideoTracks()[0];
    if (!track) return;
    // 一度だけピントを合わせ直し、そのあと連続オートフォーカスに戻す
    track.applyConstraints({ advanced: [{ focusMode: "single-shot" }] })
      .catch(() => {})
      .finally(() => setTimeout(() => track.applyConstraints({ advanced: [{ focusMode: "continuous" }] }).catch(() => {}), 800));
    flash("ピントを合わせ直しました", false);
  });
  // 読み取り枠の映像をそのまま画像で保存（うまく読めないときに、開発者に送って調べてもらう用。サーバーには保存しない）
  $("saveFrameBtn").addEventListener("click", () => {
    if (!state.stream || !video.videoWidth) return flash("カメラを開始してから押してください");
    const b = guideBand();
    const c = document.createElement("canvas");
    c.width = b.w; c.height = b.h;
    c.getContext("2d").drawImage(video, b.x, b.y, b.w, b.h, 0, 0, b.w, b.h);
    c.toBlob((blob) => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `mahjong-frame-${new Date().toISOString().replace(/[:.]/g, "-")}.jpg`;
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      flash("画像を保存しました（スマホの写真またはダウンロードに入ります）", false);
    }, "image/jpeg", 0.92);
  });
}
init();
