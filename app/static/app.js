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
  img.src = `/static/tiles/${t}.webp?v=2`;
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
    dora_indicators: state.dora.slice(0, doraSlots()).filter(Boolean),
    ura_indicators: $("riichi").checked && !isOpen() ? state.ura.slice(0, uraSlots()).filter(Boolean) : [],
    win_tile: winTile,
  };
}
const SETTING_IDS = ["seatWind", "roundWind", "honba", "riichi", "tsumo", "ippatsu", "nukidora"];
const SANMA_EXCLUDED = new Set(["2m", "3m", "4m", "5m", "6m", "7m", "8m", "0m"]);

function playersValue() {
  const el = document.querySelector("input[name=players]:checked");
  return el && el.value === "3" ? 3 : 4;
}

// 四人／三人の切り替え：三麻では萬子2〜8と北家を使わない
function applyPlayers() {
  const sanma = playersValue() === 3;
  document.querySelectorAll(".sanma-only").forEach((el) => (el.hidden = !sanma));
  document.querySelectorAll("#palette .tile").forEach((el) => (el.hidden = sanma && SANMA_EXCLUDED.has(el.dataset.tile)));
  const north = $("seatWind").querySelector("option[value=north]");
  north.hidden = sanma;
  north.disabled = sanma;
  if (sanma && $("seatWind").value === "north") $("seatWind").value = "west";
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
    if (v.players === 3) document.querySelector("input[name=players][value='3']").checked = true;
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

function waitItem(w) {
  const pts = w.ok ? `${w.payment}${w.level ? "（" + w.level + "）" : ""}` : "役なし";
  let meta = w.ok ? `${w.han}翻${w.fu ? w.fu + "符" : ""} ${w.yaku.join("・")}` : (w.error || "");
  if (w.riichi_needed) meta = "※リーチが必要（役なし）　" + meta;
  const body = document.createElement("div");
  body.append(span(`残り${w.remaining}枚`, "meta nowrap"), document.createElement("br"), span(meta, "meta"));
  return li([tilesInline([w.tile]), body, span(pts, "pts")]);
}

function renderAnalysis(a) {
  ["score", "waits", "discards", "hints"].forEach((id) => $(id).replaceChildren());
  if (!a) {
    $("message").textContent = "手牌を映すか入力すると、ここに「何を切るか」「狙える役」「点数」が出ます。";
    return;
  }
  $("message").textContent = a.message || a.shanten_label || "";

  if (a.score) {
    const box = document.createElement("div");
    box.className = "score-box";
    if (a.score.ok) {
      box.append(span(`${a.score.total.toLocaleString()}点`, "big"));
      box.append(document.createElement("br"));
      box.append(span(`${a.score.payment}　${a.score.han}翻${a.score.fu ? a.score.fu + "符" : ""} ${a.score.level || ""}`));
      const ul = document.createElement("ul");
      a.score.yaku.forEach((y) => {
        const l = document.createElement("li");
        l.textContent = `${y.name}${y.yakuman ? "（役満）" : `　${y.han}翻`}`;
        ul.append(l);
      });
      box.append(ul);
    } else {
      box.append(span(a.score.error, "err"));
    }
    $("score").append(box);
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
      return li([d, body], "hint");
    });
    $("hints").append(section("狙える役", items));
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

function onDetection(msg) {
  drawBoxes(msg.detections || []);
  const status = $("camStatus");
  if (!msg.seen) status.textContent = "牌が見つかりません。手牌を横一列にして、画面の中央に映してください";
  else if (msg.unknown) status.textContent = `${msg.seen}枚を検出（判定できない牌 ${msg.unknown}枚）。下で正しい牌に直して「この並びで覚える」を押すと覚えます`;
  else status.textContent = `${msg.seen}枚を認識中`;
  if (state.manual) return;
  if (msg.hand && JSON.stringify(msg.hand) !== JSON.stringify(state.hand)) {
    // 手牌が変わった（プレイヤーがアシストと違う牌を切った場合も含む）→ 読み直して分析を更新
    state.hand = msg.hand.slice(0, maxHand());
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

async function toggleCamera() {
  if (state.stream) return stopCamera();
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return flash("このブラウザではカメラを使えません（HTTPS で開いてください）");
  }
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 960 } },
      audio: false,
    });
    video.srcObject = state.stream;
    $("cameraHint").hidden = true;
    $("cameraBtn").textContent = "カメラ停止";
    $("mode").classList.add("live");
    requestAnimationFrame(loop);
  } catch (e) {
    flash("カメラを起動できませんでした。ブラウザの設定でカメラを許可してください");
  }
}

function stopCamera() {
  state.stream.getTracks().forEach((t) => t.stop());
  state.stream = null;
  video.srcObject = null;
  $("cameraHint").hidden = false;
  $("cameraBtn").textContent = "カメラ開始";
  $("mode").classList.remove("live");
  overlay.getContext("2d").clearRect(0, 0, overlay.width, overlay.height);
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

function sendFrame() {
  const w = video.videoWidth, h = video.videoHeight;
  const scale = Math.min(1, 960 / Math.max(w, h));
  grab.width = Math.round(w * scale);
  grab.height = Math.round(h * scale);
  grab.getContext("2d").drawImage(video, 0, 0, grab.width, grab.height);
  state.waiting = true;
  grab.toBlob((blob) => {
    if (!blob || !state.ws || state.ws.readyState !== 1) { state.waiting = false; return; }
    blob.arrayBuffer().then((buf) => state.ws.send(buf));
  }, "image/jpeg", 0.75);
  // 応答が来ないまま固まらないよう、一定時間で次のフレームを許可する
  setTimeout(() => { state.waiting = false; }, 3000);
}

// object-fit: contain で表示された映像の上に検出枠を描く
function drawBoxes(dets) {
  const rect = overlay.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  overlay.width = rect.width * dpr;
  overlay.height = rect.height * dpr;
  const ctx = overlay.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  const vw = video.videoWidth, vh = video.videoHeight;
  if (!vw || !vh) return;
  const s = Math.min(rect.width / vw, rect.height / vh);
  const dw = vw * s, dh = vh * s, ox = (rect.width - dw) / 2, oy = (rect.height - dh) / 2;
  ctx.lineWidth = 2;
  ctx.font = "bold 12px sans-serif";
  dets.forEach((d) => {
    const [x1, y1, x2, y2] = d.box;
    const x = ox + x1 * dw, y = oy + y1 * dh, bw = (x2 - x1) * dw, bh = (y2 - y1) * dh;
    ctx.strokeStyle = d.tile ? "#39ff88" : "#ffb020";
    ctx.strokeRect(x, y, bw, bh);
    const label = d.tile ? tileName(d.tile) : "？";
    ctx.fillStyle = "rgba(0,0,0,.65)";
    ctx.fillRect(x, y - 16, ctx.measureText(label).width + 6, 16);
    ctx.fillStyle = "#fff";
    ctx.fillText(label, x + 3, y - 4);
  });
}

// 手で修正中は自動更新を止める。「自動に戻す」で再開
function setManual(v) {
  state.manual = v;
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
    if (playersValue() === 3) {
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
}
init();
